"""
Stage 9 -- coverage siting with terrain in the loop.

The flat-earth version of this (coverage.py) picked a site by distance alone.
That is now known to be wrong in a specific, measured way: Fresnel obstruction
more than doubles the odds of outage between 2 and 6 km from the tower
(odds ratio 2.25 at 2-4 km, p = 7.7e-08; 2.39 at 4-6 km, p = 5.5e-12), while
beyond 6 km it has no effect at all because the link budget has already run out.

So a candidate site is no longer judged on how far it is from a demand cell, but
on whether it can actually *see* that cell. Two consequences the flat model
could not represent:

  * MAST HEIGHT BECOMES A SITING VARIABLE. A 10 m relay pole and a 36.6 m macro
    mast clear completely different amounts of terrain, so height is declared
    per asset class rather than assumed away.

  * HIGH GROUND BEATS CLOSE GROUND. A site on a ridge with line of sight into
    the southern shadow can outperform one that is nearer but tucked behind it.

Propagation model, fitted jointly on the measured data:

    RSRP = b0 + b1*log10(d) + [azimuth terms, macro only] + b_diff * J(v)

where J(v) is ITU-R P.526 single knife-edge loss. Fitting the diffraction term
explicitly drops the distance exponent from 2.40 to 1.95 -- essentially free
space -- which says the terrain term is absorbing real physics rather than
fitting noise, because that is what the exponent *should* be once obstruction is
accounted for separately.
"""
import json

import numpy as np
import pandas as pd
from scipy.optimize import lsq_linear

from config import (DATA, GRID_M, N_ROBUSTNESS_DRAWS, RANDOM_SEED, REPORTS,
                    SERVING_SITE)
from coverage import (AVAIL_TARGET, W_AREA, W_ROUTE, Scorer, avail_to_rsrp,
                      build_candidates, build_grid)
from features import haversine_m, load_sites
from model import fit_outage_curve, fit_pathloss
from propagation import DEM, RX_AGL, TX_AGL, link_features

# Mast height is now part of the asset definition, not a global assumption.
ASSETS = {
    "relay":     {"label": "Donor-fed relay",       "deficit": 20.0,
                  "agl": 10.0, "donor_min": -95.0},
    "smallcell": {"label": "Backhauled small cell", "deficit": 26.0,
                  "agl": 10.0, "donor_min": None},
    "macro":     {"label": "Macro-class site",      "deficit": 0.0,
                  "agl": 36.576, "donor_min": None},
}


DUAL_BREAK_M = 3000.0        # two-slope breakpoint
N_NEAR_MIN, N_NEAR_MAX = 1.8, 3.5     # physical bounds on the near exponent
N_FAR_MAX = 5.0


def _terms(pl, log_d, diff_db, fresnel):
    """The direction-independent part of the model, shared by every node.

    Both terrain terms are ORTHOGONALISED against log-distance before use.
    Without that, Fresnel clearance is 96.5% correlated with log-distance --
    clearance is high near the tower and low far from it -- so a free
    coefficient on it absorbs the distance effect and leaves a path-loss
    exponent of 0.53, which is not a propagation law, it is distance wearing a
    hat. Removing the collinear part lets each term carry only what distance
    does not already explain, and the exponent means what it says again.
    """
    ld = np.asarray(log_d, dtype=float)
    fr = np.clip(np.asarray(fresnel, dtype=float), -3.0, 3.0)
    df_ = np.asarray(diff_db, dtype=float)
    of, od = pl["orth_fres"], pl["orth_diff"]
    fres = fr - (of[0] + of[1] * ld)
    diff = df_ - (od[0] + od[1] * ld)
    dual = np.maximum(0.0, ld - np.log10(pl["break_m"]))
    return dual, fres, diff


def fit_with_terrain(df):
    """Path loss with terrain, fitted to generalise rather than to fit.

    Four changes from the first version, every one of them forced by the
    backtest rather than chosen for elegance:

      ONE azimuth harmonic, not two. Two harmonics fit the three-sector beam
      shape beautifully in sample and then fall apart on a held-out bearing
      sector. Dropping to one is the single largest win here.

      A DUAL SLOPE breaking at 3 km -- the standard two-ray treatment, and the
      fitted result is textbook rural: n = 1.80 near, 3.35 far.

      TERRAIN TERMS ORTHOGONALISED against log-distance (see _terms), which is
      what stops the clearance term from eating the exponent.

      THE NEAR EXPONENT BOUNDED at 1.8, costing 0.08 dB of RMSE and buying a
      model whose constants can be defended in a room.

    Held out by geography: RMSE 9.63 dB, R2 +0.16, against 12.48 dB and -0.65
    for the form this replaces.
    """
    r = df[df.site.eq(SERVING_SITE) & df.rsrp.notna() & (df.dist_m > 30)]
    ld = r.log_d.to_numpy()
    az = np.radians(r.az_deg.to_numpy())
    A = np.column_stack([np.ones(len(r)), ld])
    of, *_ = np.linalg.lstsq(A, np.clip(r.fresnel_frac.to_numpy(), -3, 3), rcond=None)
    od, *_ = np.linalg.lstsq(A, r.diff_db.to_numpy(), rcond=None)
    pre = {"orth_fres": [float(x) for x in of], "orth_diff": [float(x) for x in od],
           "break_m": DUAL_BREAK_M}
    dual, fres, diff = _terms(pre, ld, r.diff_db.to_numpy(), r.fresnel_frac.to_numpy())

    X = np.column_stack([np.ones(len(r)), ld, np.cos(az), np.sin(az), diff, dual, fres])
    lo = np.array([-np.inf, -10 * N_NEAR_MAX, -np.inf, -np.inf, -2.5, -10 * N_FAR_MAX, 0.0])
    hi = np.array([np.inf, -10 * N_NEAR_MIN, np.inf, np.inf, -0.2, 0.0, 15.0])
    c = lsq_linear(X, r.rsrp.to_numpy(), bounds=(lo, hi), max_iter=400).x
    res = r.rsrp.to_numpy() - X @ c
    return dict(pre, b0=float(c[0]), slope=float(c[1]),
                az=[float(c[2]), float(c[3])], b_diff=float(c[4]),
                b_dual=float(c[5]), b_fres=float(c[6]),
                sigma=float(res.std()), n_exponent=float(-c[1] / 10.0),
                n_far=float(-(c[1] + c[5]) / 10.0), n=int(len(r)))


def rsrp_from_node(pl, dist_m, diff_db, eirp_deficit, fresnel=None):
    """Omni node: distance, dual slope, EIRP offset, and the terrain terms.

    `fresnel` is the minimum first-Fresnel clearance as a fraction of F1, from
    link_features(). Omitting it assumes an unobstructed path, which is only
    safe when diff_db is zero as well.
    """
    ld = np.log10(np.clip(dist_m, 30.0, None))
    if fresnel is None:
        fresnel = np.full(np.shape(ld), 3.0)
    dual, fres, diff = _terms(pl, ld, diff_db, fresnel)
    return (pl["b0"] + pl["slope"] * ld + pl["b_dual"] * dual - eirp_deficit
            + pl["b_diff"] * diff + pl["b_fres"] * fres)


def macro_rsrp(pl, dem, lat, lon):
    """Predicted RSRP from the existing macro, using the full fitted model."""
    from features import haversine_m, load_sites
    from propagation import TX_AGL, link_features
    sites, _ = load_sites(); tl, to = sites[SERVING_SITE]
    F = link_features(dem, tl, to, np.asarray(lat), np.asarray(lon), tx_agl=TX_AGL)
    d = haversine_m(tl, to, np.asarray(lat), np.asarray(lon))
    az = np.arctan2(np.sin(np.radians(np.asarray(lon) - to)) * np.cos(np.radians(np.asarray(lat))),
                    np.cos(np.radians(tl)) * np.sin(np.radians(np.asarray(lat))) -
                    np.sin(np.radians(tl)) * np.cos(np.radians(np.asarray(lat))) *
                    np.cos(np.radians(np.asarray(lon) - to)))
    a = pl["az"]
    ld = np.log10(np.clip(d, 30, None))
    dual, fres, diff = _terms(pl, ld, F["diff_db"], F["fresnel_frac"])
    return (pl["b0"] + pl["slope"] * ld + pl["b_dual"] * dual
            + a[0] * np.cos(az) + a[1] * np.sin(az)
            + pl["b_diff"] * diff + pl["b_fres"] * fres)


def fit_avail_terrain(df, pl, dem, min_n=1):
    """Availability as a function of the RSRP THIS model predicts.

    The bug this replaces: the availability curve used to be calibrated against
    rsrp_omni(distance) from the non-terrain fit, then read with RSRP from the
    terrain fit. Those differ by up to 6.9 dB on distance alone and much more on
    obstructed cells, because the diffraction term carries a -1.90 dB/dB
    coefficient. The curve was being sampled at the wrong place on its own axis,
    and the backtest caught it: the simulator claimed 44.6% of measured route-km
    had service where the measurements said 68.0%.

    Calibrating the curve against the same quantity the coverage model produces
    makes the mapping self-consistent by construction.
    """
    from sklearn.isotonic import IsotonicRegression
    ma = GRID_M / 111_320.0
    mo = GRID_M / (111_320.0 * np.cos(np.radians(42.0)))
    g = df.assign(gy=np.round(df.lat / ma).astype(int),
                  gx=np.round(df.lon / mo).astype(int))
    agg = g.groupby(["gy", "gx"]).agg(lat=("lat", "mean"), lon=("lon", "mean"),
                                      n=("outage", "size"),
                                      avail=("outage", lambda s: 1 - s.mean())).reset_index()
    agg = agg[agg.n >= min_n]
    x = macro_rsrp(pl, dem, agg.lat.to_numpy(), agg.lon.to_numpy())
    iso = IsotonicRegression(increasing=True, out_of_bounds="clip", y_min=0, y_max=1)
    # Weight each cell by how many samples it holds. Unweighted, the fit is
    # dominated by the sparse far-south cells (one or two samples each) whose
    # mean availability is 0.38, while the population actually being scored has
    # a sample-weighted availability of 0.58. That mismatch alone had the
    # simulator claiming 24.7% of measured route-km served against an observed
    # 68%. Weighting moves it to 49.2% and drops the Brier score from 0.176
    # to 0.141.
    iso.fit(x, agg.avail.to_numpy(), sample_weight=agg.n.to_numpy())
    return iso


def avail_threshold(av, t, lo=-140.0, hi=-30.0, step=0.05):
    """RSRP at which the fitted availability curve first reaches t."""
    grid = np.arange(lo, hi, step)
    a = np.clip(av.predict(grid), 0, 1)
    ok = np.where(a >= t)[0]
    return float(grid[ok[0]]) if len(ok) else np.inf


def run(verbose=True):
    rng = np.random.default_rng(RANDOM_SEED)
    dem = DEM()
    df = pd.read_csv(DATA / "labeled_terrain.csv", dtype={"cellid": str})
    plf = fit_pathloss(df)
    pl = fit_with_terrain(df)
    df["outage"] = df.cellid.isna() | df.cellid.eq("FFFFFFFFF")
    av = fit_avail_terrain(df, pl, dem)      # calibrated against THIS model's RSRP
    sigma = pl["sigma"]
    r_thr = avail_threshold(av, AVAIL_TARGET)

    cells = build_grid(df)
    scorer = Scorer(cells)
    cand = build_candidates(df, cells, plf)
    clat, clon = cells.lat.to_numpy(), cells.lon.to_numpy()

    sites, _ = load_sites()
    tl, to = sites[SERVING_SITE]

    if verbose:
        print(f"[fit] n = {pl['n_exponent']:.2f} (was 2.40 without terrain), "
              f"b_diff = {pl['b_diff']:.2f} dB/dB, sigma = {sigma:.2f} dB")
        print(f"[cover] {len(cells):,} cells | {scorer.tot_rk:.1f} route-km | "
              f"{scorer.tot_ar:.1f} km2 | {len(cand)} candidates")
        print(f"[cover] service test: RSRP >= {r_thr:.1f} dBm\n")

    # ---- existing macro, terrain-aware -----------------------------------
    Fm = link_features(dem, tl, to, clat, clon, tx_agl=TX_AGL)
    dm = haversine_m(tl, to, clat, clon)
    az = np.radians(np.degrees(np.arctan2(
        np.sin(np.radians(clon - to)) * np.cos(np.radians(clat)),
        np.cos(np.radians(tl)) * np.sin(np.radians(clat)) -
        np.sin(np.radians(tl)) * np.cos(np.radians(clat)) * np.cos(np.radians(clon - to)))))
    base_r = macro_rsrp(pl, dem, clat, clon)

    b_km, b_a = scorer.parts(base_r >= r_thr)
    base_score = scorer(base_r >= r_thr)
    if verbose:
        print(f"[cover] BEFORE (terrain-aware): {b_km:.1f} route-km "
              f"({100*b_km/scorer.tot_rk:.1f}%), {b_a:.1f} km2 "
              f"({100*b_a/scorer.tot_ar:.1f}%), score {base_score:.3f}\n")

    results = {"fit": pl, "avail_target": AVAIL_TARGET, "rsrp_threshold": r_thr,
               "weights": {"route": W_ROUTE, "area": W_AREA},
               "totals": {"route_km": scorer.tot_rk, "area_km2": scorer.tot_ar},
               "baseline": {"score": base_score, "route_km": b_km, "area_km2": b_a,
                            "route_pct": 100 * b_km / scorer.tot_rk,
                            "area_pct": 100 * b_a / scorer.tot_ar},
               "assets": {}}

    for key, A in ASSETS.items():
        feas = (cand.donor_rsrp.to_numpy() >= A["donor_min"]
                if A["donor_min"] is not None else np.ones(len(cand), bool))
        cf = cand[feas].reset_index(drop=True)
        if verbose:
            print(f"  {A['label']}  ({A['agl']:.0f} m mast, -{A['deficit']:.0f} dB, "
                  f"{len(cf)}/{len(cand)} feasible)")

        # terrain-aware RSRP from every feasible candidate to every cell
        R = np.empty((len(cf), len(cells)), dtype=np.float32)
        for i, c in enumerate(cf.itertuples()):
            F = link_features(dem, c.lat, c.lon, clat, clon, tx_agl=A["agl"])
            d = haversine_m(c.lat, c.lon, clat, clon)
            R[i] = rsrp_from_node(pl, d, F["diff_db"], A["deficit"], F["fresnel_frac"])

        cur, chosen, gains = base_r.copy(), [], []
        base = scorer(cur >= r_thr)
        for _ in range(3):
            best, bg, br = None, 1e-12, None
            for i in range(len(cf)):
                nr = np.maximum(cur, R[i])
                s = scorer(nr >= r_thr) - base
                if s > bg:
                    best, bg, br = i, s, nr
            if best is None:
                break
            chosen.append(best); cur = br; gains.append(bg)

        km1, a1 = scorer.parts(np.maximum(base_r, R[chosen[0]]) >= r_thr)
        gz = dem.at(cf.loc[chosen[0], "lat"], cf.loc[chosen[0], "lon"])
        rec = {"label": A["label"], "agl_m": A["agl"], "deficit_db": A["deficit"],
               "n_feasible": int(len(cf)),
               "sites": [{"rank": i + 1, "lat": float(cf.loc[c, "lat"]),
                          "lon": float(cf.loc[c, "lon"]), "kind": cf.loc[c, "kind"],
                          "ground_m": float(dem.at(cf.loc[c, "lat"], cf.loc[c, "lon"])),
                          "dist_from_macro_m": round(float(cf.loc[c, "d_macro"])),
                          "cumulative_gain": g}
                         for i, (c, g) in enumerate(zip(chosen, gains))],
               "one_asset": {"route_km": km1, "area_km2": a1,
                             "route_km_added": km1 - b_km, "area_km2_added": a1 - b_a,
                             "route_pct": 100 * km1 / scorer.tot_rk,
                             "area_pct": 100 * a1 / scorer.tot_ar,
                             "score": base + gains[0]}}

        # robustness under shadow fading
        wins = np.zeros(len(cf), int)
        for _ in range(N_ROBUSTNESS_DRAWS):
            sh = rng.normal(0, sigma, len(cells)).astype(np.float32)
            bb = base_r + sh
            bs = scorer(bb >= r_thr)
            sc = np.array([scorer(np.maximum(bb, R[i] + sh) >= r_thr) - bs
                           for i in range(len(cf))])
            wins[int(np.argmax(sc))] += 1
        freq = wins / N_ROBUSTNESS_DRAWS
        dref = haversine_m(cf.loc[chosen[0], "lat"], cf.loc[chosen[0], "lon"],
                           cf.lat.to_numpy(), cf.lon.to_numpy())
        rec["robustness"] = {"exact": float(freq[chosen[0]]),
                             "within_1km": float(freq[dref <= 1000].sum()),
                             "within_2km": float(freq[dref <= 2000].sum()),
                             "random_pick": 1.0 / len(cf)}
        results["assets"][key] = rec

        if verbose:
            s0 = rec["sites"][0]
            print(f"    best {s0['lat']:.5f},{s0['lon']:.5f} ({s0['kind']}, "
                  f"ground {s0['ground_m']:.0f} m, {s0['dist_from_macro_m']} m out)")
            print(f"    +{rec['one_asset']['route_km_added']:.1f} route-km, "
                  f"+{rec['one_asset']['area_km2_added']:.1f} km2  -> route "
                  f"{rec['one_asset']['route_pct']:.1f}%, area "
                  f"{rec['one_asset']['area_pct']:.1f}%, score "
                  f"{rec['one_asset']['score']:.3f}")
            print(f"    3 assets cumulative +{gains[-1]:.3f} | robustness "
                  f"{100*freq[chosen[0]]:.0f}% exact, "
                  f"{100*rec['robustness']['within_2km']:.0f}% within 2 km\n")

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "coverage_terrain.json").write_text(json.dumps(results, indent=2))
    if verbose:
        print("[cover] wrote reports/coverage_terrain.json")
    return results


if __name__ == "__main__":
    run()
