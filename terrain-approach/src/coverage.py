"""
Stage 7 -- coverage-first siting.

The objective here is NOT the throughput objective used elsewhere in the
pipeline.  The question is "where does one more access point give the most
locations *some* service", so a cell either has usable service or it does not,
and the score is a weighted blend of two demand layers:

    score = 0.70 x (route-km covered / total route-km)
          + 0.30 x (area covered      / total area)

ROUTE LAYER is the primary weight because it is the only demand we actually
measured.  Its length is de-duplicated: the van drove some roads on all four
runs, so summing GPS step distances gives 277 km for what is really 116.7 km of
distinct road.  Counting distinct 25 m sub-cells recovers the true length.

AREA LAYER is secondary and is an extrapolation -- it scores the whole 189 km2
bounding box, most of which was never driven.  That is defensible only because
the propagation model is a fitted physical law rather than an interpolator: it
has a mechanism, so evaluating it away from the measurements is a prediction
rather than an invention.  It is still the weaker of the two layers and carries
30% for that reason.

ONE SIMPLIFICATION MAKES THIS FAST.  Availability is a monotone function of
predicted RSRP, so "availability >= t" is exactly "RSRP >= r(t)" for a single
scalar r(t).  Coverage becomes one threshold comparison on a precomputed
candidate-by-cell RSRP matrix, which is what lets the robustness pass re-solve
the whole problem 200 times in seconds.
"""
import json

import numpy as np
import pandas as pd

from config import (DATA, GRID_M, N_ROBUSTNESS_DRAWS, RANDOM_SEED, REPORTS,
                    SERVING_SITE)
from features import haversine_m, load_sites
from model import fit_outage_curve, fit_pathloss, rsrp_macro, rsrp_omni

W_ROUTE, W_AREA = 0.70, 0.30
SUB_M = 25.0                      # sub-cell size for de-duplicating road length
AVAIL_TARGET = 0.50               # "has service more often than not"
AVAIL_SWEEP = [0.25, 0.40, 0.50, 0.65, 0.75]

# Asset classes.  The first two are the brief's menu; the third is deliberately
# outside it, because a 640 m relay cannot fill a 9 km hole and the honest
# comparison is what it would actually take.
ASSET_CLASSES = {
    "relay":     {"label": "Donor-fed relay",      "deficit": 20.0, "donor_min": -95.0},
    "smallcell": {"label": "Backhauled small cell", "deficit": 26.0, "donor_min": None},
    "macro":     {"label": "Macro-class site",      "deficit": 0.0,  "donor_min": None},
}


# ==========================================================================
# Demand grid
# ==========================================================================

def build_grid(df):
    """One grid over the whole bounding box carrying both demand layers."""
    ma = GRID_M / 111_320.0
    mo = GRID_M / (111_320.0 * np.cos(np.radians(42.0)))
    sa = SUB_M / 111_320.0
    so = SUB_M / (111_320.0 * np.cos(np.radians(42.0)))

    # unique road length per 200 m cell, via distinct 25 m sub-cells
    d = df.assign(sy=np.round(df.lat / sa).astype(int),
                  sx=np.round(df.lon / so).astype(int),
                  gy=np.round(df.lat / ma).astype(int),
                  gx=np.round(df.lon / mo).astype(int))
    sub = d.drop_duplicates(["sy", "sx"])
    rk = sub.groupby(["gy", "gx"]).size().mul(SUB_M / 1000.0).rename("route_km")

    gy = np.arange(int(np.floor(df.lat.min() / ma)), int(np.ceil(df.lat.max() / ma)) + 1)
    gx = np.arange(int(np.floor(df.lon.min() / mo)), int(np.ceil(df.lon.max() / mo)) + 1)
    GY, GX = np.meshgrid(gy, gx, indexing="ij")
    cells = pd.DataFrame({"gy": GY.ravel(), "gx": GX.ravel()})
    cells["lat"] = cells.gy * ma
    cells["lon"] = cells.gx * mo
    cells["area_km2"] = (GRID_M / 1000.0) ** 2
    cells = cells.merge(rk.reset_index(), on=["gy", "gx"], how="left")
    cells["route_km"] = cells.route_km.fillna(0.0)
    return cells.reset_index(drop=True)


def avail_to_rsrp(oc, t):
    """Invert the fitted outage curve: the RSRP at which availability reaches t."""
    g = np.arange(-140.0, -30.0, 0.05)
    a = 1.0 - np.clip(oc.predict(g), 0, 1)
    ok = np.where(a >= t)[0]
    return float(g[ok[0]]) if len(ok) else np.inf


# ==========================================================================
# Candidates
# ==========================================================================

def build_candidates(df, cells, pl, spacing_m=400.0, offroute_m=600.0):
    """Two sets: on the driven route (access evidenced) and an off-route grid."""
    pts = df[["lat", "lon"]].dropna().to_numpy()
    keep, kl, ko = [pts[0]], [pts[0][0]], [pts[0][1]]
    for p in pts[1:]:
        if haversine_m(p[0], p[1], np.array(kl), np.array(ko)).min() > spacing_m:
            keep.append(p); kl.append(p[0]); ko.append(p[1])
    on = pd.DataFrame(keep, columns=["lat", "lon"]); on["kind"] = "on-route"

    step = max(1, int(round(offroute_m / GRID_M)))
    g = cells.iloc[::1][(cells.gy % step == 0) & (cells.gx % step == 0)]
    off = g[["lat", "lon"]].copy(); off["kind"] = "off-route"
    # drop off-route points that are already near an on-route candidate
    keepo = []
    for r in off.itertuples():
        if haversine_m(r.lat, r.lon, on.lat.to_numpy(), on.lon.to_numpy()).min() > offroute_m * 0.6:
            keepo.append((r.lat, r.lon))
    off = pd.DataFrame(keepo, columns=["lat", "lon"]); off["kind"] = "off-route"

    cand = pd.concat([on, off], ignore_index=True)
    sites, _ = load_sites()
    slat, slon = sites[SERVING_SITE]
    cand["d_macro"] = haversine_m(cand.lat, cand.lon, slat, slon)
    cand["donor_rsrp"] = rsrp_omni(cand.d_macro, pl)
    return cand[cand.d_macro > 400].reset_index(drop=True)


# ==========================================================================
# Scoring
# ==========================================================================

class Scorer:
    """0.70 route-km + 0.30 area, both as a fraction of their own total."""

    def __init__(self, cells):
        self.rk = cells.route_km.to_numpy()
        self.ar = cells.area_km2.to_numpy()
        self.tot_rk = self.rk.sum()
        self.tot_ar = self.ar.sum()

    def parts(self, covered):
        return (float(self.rk[covered].sum()), float(self.ar[covered].sum()))

    def __call__(self, covered):
        km, a = self.parts(covered)
        return W_ROUTE * km / self.tot_rk + W_AREA * a / self.tot_ar


def greedy(base_r, R, r_thr, scorer, k):
    """Greedy max-coverage. R is (n_candidates, n_cells) of delivered RSRP."""
    cur = base_r.copy()
    base = scorer(cur >= r_thr)
    chosen, gains = [], []
    for _ in range(k):
        best, bg, br = None, 1e-12, None
        for i in range(R.shape[0]):
            if i in chosen:
                continue
            nr = np.maximum(cur, R[i])
            s = scorer(nr >= r_thr) - base
            if s > bg:
                best, bg, br = i, s, nr
        if best is None:
            break
        chosen.append(best); cur = br; gains.append(bg)
    return chosen, gains, base, cur


# ==========================================================================
# Main
# ==========================================================================

def run(verbose=True):
    rng = np.random.default_rng(RANDOM_SEED)
    df = pd.read_csv(DATA / "labeled.csv", dtype={"cellid": str})
    pl = fit_pathloss(df)
    oc = fit_outage_curve(df, pl)
    sigma = pl["residual_sd_db"]

    cells = build_grid(df)
    scorer = Scorer(cells)
    cand = build_candidates(df, cells, pl)
    base_r = rsrp_macro(cells.lat.to_numpy(), cells.lon.to_numpy(), pl)
    r_thr = avail_to_rsrp(oc, AVAIL_TARGET)

    if verbose:
        print(f"[cover] grid {len(cells):,} cells | {scorer.tot_rk:.1f} route-km "
              f"| {scorer.tot_ar:.1f} km2")
        print(f"[cover] candidates {len(cand)} "
              f"({(cand.kind=='on-route').sum()} on-route, "
              f"{(cand.kind=='off-route').sum()} off-route)")
        print(f"[cover] service test: availability >= {AVAIL_TARGET:.2f} "
              f"<=> RSRP >= {r_thr:.1f} dBm")

    D = np.stack([haversine_m(r.lat, r.lon, cells.lat.to_numpy(), cells.lon.to_numpy())
                  for r in cand.itertuples()])

    results = {"weights": {"route": W_ROUTE, "area": W_AREA},
               "avail_target": AVAIL_TARGET,
               "rsrp_threshold_dbm": r_thr,
               "totals": {"route_km": scorer.tot_rk, "area_km2": scorer.tot_ar,
                          "n_cells": int(len(cells)), "n_candidates": int(len(cand))},
               "assets": {}}

    b_km, b_a = scorer.parts(base_r >= r_thr)
    base_score = scorer(base_r >= r_thr)
    results["baseline"] = {"score": base_score, "route_km": b_km, "area_km2": b_a,
                           "route_pct": 100 * b_km / scorer.tot_rk,
                           "area_pct": 100 * b_a / scorer.tot_ar}
    if verbose:
        print(f"[cover] BEFORE: {b_km:.1f} route-km ({100*b_km/scorer.tot_rk:.1f}%), "
              f"{b_a:.1f} km2 ({100*b_a/scorer.tot_ar:.1f}%), score {base_score:.3f}\n")

    for key, A in ASSET_CLASSES.items():
        R = rsrp_omni(D, pl, A["deficit"])
        feas = np.ones(len(cand), bool)
        if A["donor_min"] is not None:
            feas = cand.donor_rsrp.to_numpy() >= A["donor_min"]
        # a site that can never be reached for backhaul or access is not a site
        Rf = R[feas]
        cf = cand[feas].reset_index(drop=True)

        # radius at which this asset alone still clears the service test
        rr = np.logspace(1.5, 4.3, 600)
        ok = rsrp_omni(rr, pl, A["deficit"]) >= r_thr
        radius = float(rr[ok].max()) if ok.any() else 0.0

        chosen, gains, b, final = greedy(base_r, Rf, r_thr, scorer, 3)
        km1, a1 = scorer.parts(np.maximum(base_r, Rf[chosen[0]]) >= r_thr)

        # the baseline the brief says to beat: the worst measured point
        d = df.assign(gy=np.round(df.lat / (GRID_M / 111320.0)).astype(int))
        worst = df.loc[df[df.cellid.isna()].lat.idxmin()] if df.cellid.isna().any() else df.iloc[0]
        wD = haversine_m(worst.lat, worst.lon, cells.lat.to_numpy(), cells.lon.to_numpy())
        wR = rsrp_omni(wD, pl, A["deficit"])
        w_gain = scorer(np.maximum(base_r, wR) >= r_thr) - b

        rec = {
            "label": A["label"], "eirp_deficit_db": A["deficit"],
            "outside_brief_menu": key == "macro",
            "service_radius_m": round(radius),
            "n_feasible": int(feas.sum()), "n_candidates": int(len(cand)),
            "sites": [{"rank": i + 1, "lat": float(cf.loc[c, "lat"]),
                       "lon": float(cf.loc[c, "lon"]), "kind": cf.loc[c, "kind"],
                       "dist_from_macro_m": round(float(cf.loc[c, "d_macro"])),
                       "donor_rsrp_dbm": round(float(cf.loc[c, "donor_rsrp"]), 1),
                       "cumulative_gain": g} for i, (c, g) in enumerate(zip(chosen, gains))],
            "one_asset": {"route_km": km1, "area_km2": a1,
                          "route_km_added": km1 - b_km, "area_km2_added": a1 - b_a,
                          "route_pct": 100 * km1 / scorer.tot_rk,
                          "area_pct": 100 * a1 / scorer.tot_ar,
                          "score": b + gains[0] if gains else b},
            "worst_point_baseline": {"lat": float(worst.lat), "lon": float(worst.lon),
                                     "gain": w_gain},
            "optimiser_vs_worst_point": (gains[0] / w_gain) if w_gain > 1e-9 else None,
        }

        # robustness: shadow fading on every cell, re-solve k=1
        wins = np.zeros(len(cf), int)
        for _ in range(N_ROBUSTNESS_DRAWS):
            sh = rng.normal(0, sigma, len(cells))
            bb = base_r + sh
            bs = scorer(bb >= r_thr)
            sc = np.array([scorer(np.maximum(bb, Rf[i] + sh) >= r_thr) - bs
                           for i in range(len(cf))])
            wins[int(np.argmax(sc))] += 1
        freq = wins / N_ROBUSTNESS_DRAWS
        dref = haversine_m(cf.loc[chosen[0], "lat"], cf.loc[chosen[0], "lon"],
                           cf.lat.to_numpy(), cf.lon.to_numpy())
        rec["robustness"] = {
            "n_draws": N_ROBUSTNESS_DRAWS, "random_pick": 1.0 / len(cf),
            "exact": float(freq[chosen[0]]),
            "within_1km": float(freq[dref <= 1000].sum()),
            "within_2km": float(freq[dref <= 2000].sum()),
            "within_3km": float(freq[dref <= 3000].sum())}
        results["assets"][key] = rec

        if verbose:
            s0 = rec["sites"][0]
            print(f"  {A['label']:<22} radius {radius:>5.0f} m | "
                  f"{int(feas.sum()):>4}/{len(cand)} feasible")
            print(f"    best site {s0['lat']:.5f},{s0['lon']:.5f} "
                  f"({s0['kind']}, {s0['dist_from_macro_m']} m out)")
            print(f"    adds {rec['one_asset']['route_km_added']:>5.1f} route-km and "
                  f"{rec['one_asset']['area_km2_added']:>5.1f} km2  -> "
                  f"route {rec['one_asset']['route_pct']:.1f}%, "
                  f"area {rec['one_asset']['area_pct']:.1f}%, "
                  f"score {rec['one_asset']['score']:.3f}")
            print(f"    3 assets cumulative gain {gains[-1]:.3f} | "
                  f"vs worst-point {w_gain:.3f}"
                  + (f" ({rec['optimiser_vs_worst_point']:.1f}x)"
                     if rec["optimiser_vs_worst_point"] else ""))
            print(f"    robustness: exact {100*freq[chosen[0]]:.0f}%, "
                  f"within 2 km {100*rec['robustness']['within_2km']:.0f}% "
                  f"(random {100/len(cf):.1f}%)\n")

    # ---- availability-threshold sweep -----------------------------------
    sweep = {}
    for t in AVAIL_SWEEP:
        rt = avail_to_rsrp(oc, t)
        row = {"rsrp_threshold": rt}
        bkm, ba = scorer.parts(base_r >= rt)
        row["before"] = {"route_pct": 100 * bkm / scorer.tot_rk,
                         "area_pct": 100 * ba / scorer.tot_ar}
        for key, A in ASSET_CLASSES.items():
            R = rsrp_omni(D, pl, A["deficit"])
            feas = (cand.donor_rsrp.to_numpy() >= A["donor_min"]
                    if A["donor_min"] is not None else np.ones(len(cand), bool))
            ch, g, b2, _ = greedy(base_r, R[feas], rt, scorer, 1)
            row[key] = {"gain": g[0] if g else 0.0}
        sweep[f"{t:.2f}"] = row
    results["availability_sweep"] = sweep

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "coverage.json").write_text(json.dumps(results, indent=2))
    if verbose:
        print(f"[cover] wrote reports/coverage.json")
    return results


if __name__ == "__main__":
    run()
