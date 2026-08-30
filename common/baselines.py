"""The brief's testable hypothesis, tested.

    "Optimizing placement against predicted performance deficits and route importance
     will outperform choosing only the single worst measured point."

That is a claim about a comparison, so it needs comparators. Four, from weakest to
strongest, because beating the worst one proves very little:

  worst measured point     the brief's named baseline: put the asset where the drive
                           test recorded the lowest RSRP
  largest outage centroid  the obvious human heuristic: the middle of the longest
                           continuous stretch with no service
  furthest from any site   the naive geometric answer, ignoring radio entirely
  random feasible site     1,000 draws. This is the one that matters -- an optimiser
                           choosing the best of 627 candidates has a selection
                           advantage a single-point heuristic does not, so the honest
                           question is where the named baselines fall in THIS
                           distribution, not whether the optimiser beats them

Every placement is scored identically: the same predicted surface, the same demand grid,
the same criterion and threshold, the same route/area weighting. Baselines are evaluated
at their exact coordinates rather than snapped to the candidate grid, which is the
fairer treatment -- they do not pay for the optimiser's quantisation.

Model-agnostic: simulators arrive through the `common.simulator` contract.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .demand import ASSETS, Scorer, greedy, haversine_m


def worst_measured_point(df):
    """The single measured location with the lowest reported RSRP."""
    r = df[df.rsrp.notna()]
    i = r.rsrp.idxmin()
    return float(r.loc[i, "lat"]), float(r.loc[i, "lon"]), float(r.loc[i, "rsrp"])


def largest_outage_centroid(df):
    """Centroid of the longest consecutive run of no-service samples."""
    d = df.copy()
    if "outage" not in d:
        d["outage"] = d.cellid.isna() | d.cellid.eq("FFFFFFFFF")
    key = "run" if "run" in d else None
    best, best_n = None, 0
    for _, g in (d.groupby(key) if key else [(0, d)]):
        o = g.outage.to_numpy()
        start = None
        for i, v in enumerate(list(o) + [False]):
            if v and start is None:
                start = i
            elif not v and start is not None:
                if i - start > best_n:
                    best_n, best = i - start, g.iloc[start:i]
                start = None
    if best is None:
        return None
    return float(best.lat.mean()), float(best.lon.mean()), int(best_n)


def furthest_measured_from_sites(df, site_lat, site_lon):
    """The measured point furthest from the existing transmitter."""
    d = haversine_m(site_lat, site_lon, df.lat.to_numpy(), df.lon.to_numpy())
    i = int(np.argmax(d))
    return float(df.lat.iloc[i]), float(df.lon.iloc[i]), float(d[i] / 1000.0)


def compare(sim, df, cells, cand, R, asset, thr, scorer, macro_lat, macro_lon,
            n_random=1000, seed=0, verbose=True):
    """Optimiser against every baseline, on one criterion and threshold."""
    clat, clon = cells.lat.to_numpy(), cells.lon.to_numpy()
    base_r = np.asarray(sim.macro_rsrp(clat, clon), float)
    base = scorer(base_r >= thr)
    a = ASSETS[asset]

    def gain_at(lat, lon):
        r = np.asarray(sim.node_rsrp(lat, lon, a["agl"], a["deficit"], clat, clon), float)
        return scorer(np.maximum(base_r, r) >= thr) - base

    rows = []
    pick, gains = greedy(base_r, R, thr, scorer, k=1)
    opt_gain = float(gains[0]) if gains else 0.0
    opt_lat = float(cand.lat.iloc[pick[0]]) if pick else None
    opt_lon = float(cand.lon.iloc[pick[0]]) if pick else None
    rows.append(dict(method="optimiser (max-coverage over candidates)",
                     lat=opt_lat, lon=opt_lon, gain=opt_gain, detail=f"{len(R)} candidates"))

    wlat, wlon, wr = worst_measured_point(df)
    rows.append(dict(method="worst measured point (the brief's baseline)",
                     lat=wlat, lon=wlon, gain=gain_at(wlat, wlon),
                     detail=f"RSRP {wr:.0f} dBm"))

    oc = largest_outage_centroid(df)
    if oc:
        olat, olon, on = oc
        rows.append(dict(method="largest outage centroid", lat=olat, lon=olon,
                         gain=gain_at(olat, olon), detail=f"{on} samples"))

    flat, flon, fd = furthest_measured_from_sites(df, macro_lat, macro_lon)
    rows.append(dict(method="furthest measured point from the site", lat=flat,
                     lon=flon, gain=gain_at(flat, flon), detail=f"{fd:.1f} km out"))

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(R), size=min(n_random, len(R) * 20))
    rnd = np.array([scorer(np.maximum(base_r, R[i]) >= thr) - base for i in
                    np.unique(idx)])
    rows.append(dict(method=f"random feasible candidate (n={len(rnd)})", lat=None,
                     lon=None, gain=float(rnd.mean()),
                     detail=f"median {rnd.mean():.4f}, p90 {np.quantile(rnd, 0.9):.4f}, "
                            f"max {rnd.max():.4f}"))

    out = pd.DataFrame(rows)
    out["pct_of_optimum"] = 100 * out.gain / opt_gain if opt_gain else np.nan
    # where each named baseline falls in the random distribution
    out["random_percentile"] = [
        (100 * float((rnd < g).mean()) if g is not None else np.nan)
        for g in out.gain]
    out["km_from_optimum"] = [
        (haversine_m(opt_lat, opt_lon, la, lo) / 1000.0
         if (la is not None and opt_lat is not None) else np.nan)
        for la, lo in zip(out.lat, out.lon)]

    if verbose:
        print(f"\n  {sim.info.name} · {a['label']} · threshold {thr:.1f} dBm · "
              f"baseline coverage {100*base:.1f}%")
        print(f"    {'method':<44}{'gain pts':>10}{'% of opt':>10}"
              f"{'rand pct':>10}{'km away':>9}")
        for _, r in out.iterrows():
            print(f"    {r.method:<44}{100*r.gain:>10.2f}{r.pct_of_optimum:>10.0f}"
                  f"{r.random_percentile:>10.0f}"
                  f"{'' if np.isnan(r.km_from_optimum) else f'{r.km_from_optimum:9.2f}'}")
    return out
