"""
Stage 14c -- does the choice of simulator change WHERE WE BUILD?

`fno_compare.py` answers a prediction question: which model reproduces measured
RSRP on held-out geography. That is necessary but it is not the decision. The
planner does not ship RMSE, it ships a pin on a map, and two models with the
same RMSE can disagree about where the tower goes.

So this runs the whole siting chain -- availability calibration, service
threshold, per-candidate coverage surface, greedy max-coverage solve, shadow
fading robustness -- once per candidate simulator, through IDENTICAL code, and
reports what each one would tell you to build.

WHAT IS HELD FIXED, so that only the propagation model varies:

  * the demand grid and its route-km / area weights
  * the candidate set (627 sites, built from the non-terrain fit for both, since
    it only defines where we are allowed to look)
  * the greedy solver, the asset definitions, the fading draws and the seed

WHAT EACH SIMULATOR SUPPLIES: RSRP from the existing sectorised macro to every
demand cell, and RSRP from an arbitrary new omni node at an arbitrary mast
height. Nothing else.

ONE THING IS DELIBERATELY NOT SHARED. Each simulator calibrates its OWN
availability curve against its OWN predicted RSRP. Reusing one curve across
models would repeat the exact bug MODEL.md documents -- a curve fitted on one
definition of RSRP and read with another, up to 6.9 dB apart -- and would hand
whichever model the curve was fitted on an unearned advantage.
"""
import argparse
import json
import time

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from config import (DATA, GRID_M, N_ROBUSTNESS_DRAWS, RANDOM_SEED, REPORTS,
                    SERVING_SITE)
from coverage import (AVAIL_TARGET, W_AREA, W_ROUTE, Scorer, build_candidates,
                      build_grid)
from coverage_terrain import (ASSETS, DUAL_BREAK_M, avail_threshold,
                              fit_with_terrain, macro_rsrp, rsrp_from_node)
from features import haversine_m, load_sites
from fno_compare import (EPOCHS, backbone_pred, fit_backbone, train_operator)
from model import fit_pathloss
from profiles import profiles
from propagation import DEM, TX_AGL, link_features


# ==========================================================================
# Simulators: each is (macro RSRP over cells, node RSRP over cells)
# ==========================================================================

class Parametric:
    """The shipped model: fitted two-slope law plus P.526 and Fresnel terms."""

    name = "parametric"
    label = "Fitted physics (MODEL.md)"

    def __init__(self, df, dem):
        self.dem, self.pl = dem, fit_with_terrain(df)
        self.sigma = self.pl["sigma"]

    def macro(self, lat, lon):
        return macro_rsrp(self.pl, self.dem, lat, lon)

    def node(self, tx_lat, tx_lon, agl, deficit, lat, lon):
        F = link_features(self.dem, tx_lat, tx_lon, lat, lon, tx_agl=agl)
        d = haversine_m(tx_lat, tx_lon, lat, lon)
        return rsrp_from_node(self.pl, d, F["diff_db"], deficit, F["fresnel_frac"])


class Learned:
    """Distance-and-azimuth backbone plus a neural operator on the profile.

    The split of labour mirrors the parametric model exactly. The macro carries
    the azimuth harmonic because it is sectorised; a new omni node does not,
    exactly as `rsrp_from_node` omits it. Everything terrain then comes from the
    operator instead of from b_diff*J(v) + b_fres*F.
    """

    def __init__(self, df, dem, arch="fno", epochs=EPOCHS, verbose=True):
        from fno_compare import _data
        self.name, self.arch, self.dem = f"{arch}_residual", arch, dem
        self.label = f"{arch.upper()} on the terrain profile"
        D = _data()
        self.c = fit_backbone(D["ld"], D["az"], D["y"])
        res = D["y"] - backbone_pred(self.c, D["ld"], D["az"])
        t0 = time.time()
        self.net = train_operator(D["Xa"], res, epochs, arch=arch)
        self.sites = load_sites()[0]
        # Its own residual spread, for its own fading draws. Borrowing the
        # parametric sigma would let a worse-fitting model inherit a tighter
        # uncertainty band than it earned.
        self.sigma = float((res - self.net(D["Xa"])).std())
        if verbose:
            print(f"[sim] trained {arch} on {len(res):,} rows in "
                  f"{time.time() - t0:.0f} s, residual sigma "
                  f"{self.sigma:.2f} dB", flush=True)

    def _terrain_db(self, tx_lat, tx_lon, agl, lat, lon, chunk=20000):
        out = np.empty(len(lat), np.float32)
        for a in range(0, len(lat), chunk):
            b = min(len(lat), a + chunk)
            hb, _, _ = profiles(self.dem, tx_lat, tx_lon, lat[a:b], lon[a:b],
                                tx_agl=agl)
            out[a:b] = self.net(hb[:, None, :].astype(np.float32))
        return out

    def macro(self, lat, lon):
        tl, to = self.sites[SERVING_SITE]
        d = haversine_m(tl, to, lat, lon)
        az = np.arctan2(
            np.sin(np.radians(lon - to)) * np.cos(np.radians(lat)),
            np.cos(np.radians(tl)) * np.sin(np.radians(lat))
            - np.sin(np.radians(tl)) * np.cos(np.radians(lat))
            * np.cos(np.radians(lon - to)))
        return (backbone_pred(self.c, np.log10(np.clip(d, 30, None)), az)
                + self._terrain_db(tl, to, TX_AGL, lat, lon))

    def node(self, tx_lat, tx_lon, agl, deficit, lat, lon):
        d = haversine_m(tx_lat, tx_lon, lat, lon)
        ld = np.log10(np.clip(d, 30.0, None))
        dual = np.maximum(0.0, ld - np.log10(DUAL_BREAK_M))
        return (self.c[0] + self.c[1] * ld + self.c[4] * dual - deficit
                + self._terrain_db(tx_lat, tx_lon, agl, lat, lon))


# ==========================================================================
# The chain, run once per simulator
# ==========================================================================

def fit_avail(df, rsrp_fn, min_n=1):
    """Isotonic availability against THIS simulator's own predicted RSRP.

    Cell aggregates, weighted by sample count -- the same construction as
    `fit_avail_terrain`, generalised to take any RSRP function. See that
    docstring for why both the aggregation and the weighting are necessary.
    """
    ma = GRID_M / 111_320.0
    mo = GRID_M / (111_320.0 * np.cos(np.radians(42.0)))
    g = df.assign(gy=np.round(df.lat / ma).astype(int),
                  gx=np.round(df.lon / mo).astype(int))
    agg = g.groupby(["gy", "gx"]).agg(
        lat=("lat", "mean"), lon=("lon", "mean"), n=("outage", "size"),
        avail=("outage", lambda s: 1 - s.mean())).reset_index()
    agg = agg[agg.n >= min_n]
    iso = IsotonicRegression(increasing=True, out_of_bounds="clip",
                             y_min=0, y_max=1)
    iso.fit(rsrp_fn(agg.lat.to_numpy(), agg.lon.to_numpy()),
            agg.avail.to_numpy(), sample_weight=agg.n.to_numpy())
    return iso


def site_with(sim, df, cells, cand, scorer, dem, draws=N_ROBUSTNESS_DRAWS,
              verbose=True):
    """Availability, threshold, coverage surface, greedy solve, robustness."""
    rng = np.random.default_rng(RANDOM_SEED)
    clat, clon = cells.lat.to_numpy(), cells.lon.to_numpy()
    av = fit_avail(df, sim.macro)
    thr = avail_threshold(av, AVAIL_TARGET)
    base_r = sim.macro(clat, clon)
    b_km, b_ar = scorer.parts(base_r >= thr)

    out = {"label": sim.label, "rsrp_threshold_dbm": float(thr),
           "baseline": {"route_km": b_km, "area_km2": b_ar,
                        "route_pct": 100 * b_km / scorer.tot_rk,
                        "area_pct": 100 * b_ar / scorer.tot_ar,
                        "score": scorer(base_r >= thr)},
           "assets": {}}
    if verbose:
        print(f"\n=== {sim.label} ===", flush=True)
        print(f"    service test RSRP >= {thr:.1f} dBm | before: "
              f"{out['baseline']['route_pct']:.1f}% route, "
              f"{out['baseline']['area_pct']:.1f}% area", flush=True)

    # Two mast heights cover all three asset classes, and RSRP from a node
    # differs between classes only by the constant EIRP deficit -- so the
    # expensive per-candidate terrain pass runs twice, not three times.
    by_agl = {}
    for agl in sorted({a["agl"] for a in ASSETS.values()}):
        t0 = time.time()
        R = np.empty((len(cand), len(cells)), np.float32)
        for i, c in enumerate(cand.itertuples()):
            R[i] = sim.node(c.lat, c.lon, agl, 0.0, clat, clon)
        by_agl[agl] = R
        if verbose:
            print(f"    {agl:.0f} m mast: {len(cand)} candidate surfaces in "
                  f"{time.time() - t0:.0f} s", flush=True)

    for key, A in ASSETS.items():
        feas = (cand.donor_rsrp.to_numpy() >= A["donor_min"]
                if A["donor_min"] is not None else np.ones(len(cand), bool))
        R = by_agl[A["agl"]][feas] - A["deficit"]
        cf = cand[feas].reset_index(drop=True)

        cur, chosen, gains = base_r.copy(), [], []
        base = scorer(cur >= thr)
        for _ in range(3):
            best, bg, br = None, 1e-12, None
            for i in range(len(cf)):
                nr = np.maximum(cur, R[i])
                s = scorer(nr >= thr) - base
                if s > bg:
                    best, bg, br = i, s, nr
            if best is None:
                break
            chosen.append(best); cur = br; gains.append(bg)
        if not chosen:
            out["assets"][key] = {"label": A["label"], "sites": []}
            continue

        km1, ar1 = scorer.parts(np.maximum(base_r, R[chosen[0]]) >= thr)
        rec = {"label": A["label"], "agl_m": A["agl"], "deficit_db": A["deficit"],
               "n_feasible": int(len(cf)),
               "sites": [{"rank": i + 1, "lat": float(cf.loc[c, "lat"]),
                          "lon": float(cf.loc[c, "lon"]), "kind": cf.loc[c, "kind"],
                          "dist_from_macro_m": round(float(cf.loc[c, "d_macro"])),
                          "cumulative_gain": g}
                         for i, (c, g) in enumerate(zip(chosen, gains))],
               "one_asset": {"route_km": km1, "area_km2": ar1,
                             "route_km_added": km1 - b_km,
                             "area_km2_added": ar1 - b_ar,
                             "route_pct": 100 * km1 / scorer.tot_rk,
                             "area_pct": 100 * ar1 / scorer.tot_ar}}

        sigma = float(np.std(df.rsrp.dropna())) if not hasattr(sim, "pl") \
            else sim.pl["sigma"]
        wins = np.zeros(len(cf), int)
        for _ in range(draws):
            sh = rng.normal(0, sigma, len(cells)).astype(np.float32)
            bb = base_r + sh
            bs = scorer(bb >= thr)
            sc = np.array([scorer(np.maximum(bb, R[i] + sh) >= thr) - bs
                           for i in range(len(cf))])
            wins[int(np.argmax(sc))] += 1
        freq = wins / draws
        dref = haversine_m(cf.loc[chosen[0], "lat"], cf.loc[chosen[0], "lon"],
                           cf.lat.to_numpy(), cf.lon.to_numpy())
        rec["robustness"] = {"exact": float(freq[chosen[0]]),
                             "within_2km": float(freq[dref <= 2000].sum())}
        out["assets"][key] = rec
        if verbose:
            s0 = rec["sites"][0]
            print(f"    {A['label']:<24} {s0['lat']:.5f},{s0['lon']:.5f}  "
                  f"route {rec['one_asset']['route_pct']:5.1f}%  "
                  f"area {rec['one_asset']['area_pct']:5.1f}%  "
                  f"({100*rec['robustness']['within_2km']:.0f}% within 2 km)",
                  flush=True)
    return out


def run(archs=("fno",), epochs=EPOCHS, draws=N_ROBUSTNESS_DRAWS, verbose=True):
    t0 = time.time()
    dem = DEM()
    df = pd.read_csv(DATA / "labeled_terrain.csv", dtype={"cellid": str})
    df["outage"] = df.cellid.isna() | df.cellid.eq("FFFFFFFFF")
    cells = build_grid(df)
    scorer = Scorer(cells)
    cand = build_candidates(df, cells, fit_pathloss(df))
    if verbose:
        print(f"[site] {len(cells):,} cells | {scorer.tot_rk:.1f} route-km | "
              f"{scorer.tot_ar:.1f} km2 | {len(cand)} candidates", flush=True)

    sims = [Parametric(df, dem)] + [Learned(df, dem, a, epochs) for a in archs]
    res = {"weights": {"route": W_ROUTE, "area": W_AREA},
           "avail_target": AVAIL_TARGET,
           "totals": {"route_km": scorer.tot_rk, "area_km2": scorer.tot_ar},
           "simulators": {}}
    for sim in sims:
        res["simulators"][sim.name] = site_with(sim, df, cells, cand, scorer,
                                                dem, draws, verbose)

    # How far apart are the recommendations? That is the number that decides
    # whether the choice of simulator matters operationally.
    ref = res["simulators"]["parametric"]
    res["macro_site_disagreement_m"] = {}
    for nm, r in res["simulators"].items():
        if nm == "parametric" or not r["assets"]["macro"]["sites"]:
            continue
        a, b = ref["assets"]["macro"]["sites"][0], r["assets"]["macro"]["sites"][0]
        res["macro_site_disagreement_m"][nm] = float(
            haversine_m(a["lat"], a["lon"], b["lat"], b["lon"]))

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "siting_compare.json").write_text(json.dumps(res, indent=2))
    if verbose:
        print(f"\n{'simulator':<26}{'thr dBm':>9}{'before':>9}{'after':>9}"
              f"{'+route km':>11}{'site move':>11}")
        for nm, r in res["simulators"].items():
            m = r["assets"]["macro"]
            mv = res["macro_site_disagreement_m"].get(nm)
            print(f"{r['label']:<26}{r['rsrp_threshold_dbm']:>9.1f}"
                  f"{r['baseline']['route_pct']:>8.1f}%"
                  f"{m['one_asset']['route_pct']:>8.1f}%"
                  f"{m['one_asset']['route_km_added']:>11.1f}"
                  + (f"{mv:>10.0f} m" if mv is not None else f"{'--':>11}"))
        print(f"\n[site] {time.time() - t0:.0f} s -- wrote "
              f"reports/siting_compare.json")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", action="append", default=None,
                    help="learned architecture to site with (repeatable)")
    ap.add_argument("--epochs", type=int, default=EPOCHS)
    ap.add_argument("--draws", type=int, default=N_ROBUSTNESS_DRAWS)
    a = ap.parse_args()
    run(archs=tuple(a.arch or ["fno"]), epochs=a.epochs, draws=a.draws)
