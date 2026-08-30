"""
Stage 6 -- does the placement decision survive a change of statistic?

The pipeline so far scores a cell on EXPECTED uplink: (1 - P(outage)) x mean
uplink.  That is a defensible planning number but it is not what a user
experiences, and it hides two things:

  1. IsotonicRegression minimises squared error, so uplink(RSRP) is a conditional
     MEAN.  Throughput is right-skewed, so the mean sits above the median and the
     coverage figure is optimistic.

  2. Service is normally specified as a percentile, not an average -- "10 Mbps at
     the 90th percentile of attempts", not "10 Mbps on average".  Those are very
     different tests once outage is in the mixture, because a cell that is out
     15% of the time has a p10 of exactly zero no matter how fast it is when up.

So: rebuild the throughput distribution per cell, evaluate the same optimisation
under p05 / p10 / p50 / mean / p90, and check whether the recommended site moves.
If it does not, percentiles are a footnote.  If it does, they are the finding.

Two sources of spread are combined:
  * across locations -- shadow fading, sigma = 9.2 dB from the path-loss fit
  * at a location    -- conditional scatter of uplink at fixed RSRP (scheduling,
                        load, modem state), which is the 14.2 Mbps irreducible
                        term the validation already isolated
"""
import json

import numpy as np
import pandas as pd

from config import ASSETS, DATA, DEFAULT_THRESHOLD, REPORTS, UPLINK_THRESHOLDS
from features import haversine_m
from model import fit_outage_curve, fit_pathloss, fit_uplink_curve
from optimize import make_candidates, rsrp_from
from service import covered as score

from service import (RSRP_GRID, conditional_quantiles, percentile_table)
from config import QUANTILE_LEVELS as QUANTILES


# ==========================================================================
# Main
# ==========================================================================

def run(verbose=True):
    rng = np.random.default_rng(7)
    df = pd.read_csv(DATA / "labeled.csv", dtype={"cellid": str})
    cells = pd.read_csv(DATA / "grid.csv")
    pl = fit_pathloss(df)
    iso = fit_uplink_curve(df)
    oc = fit_outage_curve(df, pl)
    sigma = pl["residual_sd_db"]
    cq = conditional_quantiles(df)

    # ---- 0. how far above the median does the isotonic mean sit? --------
    skew = []
    for x in [-110, -100, -95, -90, -85, -80, -70, -60]:
        i = int(np.clip(np.searchsorted(RSRP_GRID, x), 0, len(RSRP_GRID) - 1))
        skew.append({"rsrp": x, "mean": round(float(cq["mean"][i]), 1),
                     "p50": round(float(cq[0.50][i]), 1),
                     "p10": round(float(cq[0.10][i]), 1),
                     "p90": round(float(cq[0.90][i]), 1),
                     "iso": round(float(iso.predict([x])[0]), 1)})
    if verbose:
        print("[pct] uplink at fixed RSRP -- mean sits above median on a skewed tail")
        print("      RSRP   iso(mean)   p10    p50    p90")
        for s in skew:
            print(f"      {s['rsrp']:5d}   {s['iso']:8.1f} {s['p10']:6.1f} "
                  f"{s['p50']:6.1f} {s['p90']:6.1f}")

    # ---- 1. per-cell service statistic under each criterion -------------
    r0 = cells["rsrp"].to_numpy()
    p0 = np.clip(oc.predict(r0), 0, 1)
    crits = {"mean": None, "p50": 0.50, "p10": 0.10, "p05": 0.05, "p90": 0.90}

    # one lookup table per criterion, then everything downstream is an interp
    tables = {c: (None if c == "mean" else percentile_table(cq, oc, sigma, crits[c]))
              for c in crits}

    def surface(rs, crit):
        if crit == "mean":
            ps = np.clip(oc.predict(rs), 0, 1)
            return (1 - ps) * np.clip(iso.predict(rs), 0, None)
        return np.interp(rs, RSRP_GRID, tables[crit])

    w = cells["route_density"].to_numpy(float); TW = w.sum()
    base = {c: surface(r0, c) for c in crits}

    cov = {c: 100 * score(base[c], w, DEFAULT_THRESHOLD) / TW for c in crits}
    if verbose:
        print("\n[pct] route demand meeting 10 Mbps uplink, by service definition")
        for c in ["p90", "mean", "p50", "p10", "p05"]:
            print(f"      {c:>5}: {cov[c]:5.1f}%")

    # ---- 2. re-run the placement under each criterion --------------------
    cand = make_candidates(df, pl)
    asset = ASSETS["relay"]
    sub = cand[cand["donor_rsrp"] >= asset["donor_rsrp_min"]].reset_index(drop=True)
    cr = [rsrp_from(r.lat, r.lon, cells, pl, asset["eirp_deficit_db"])
          for r in sub.itertuples()]

    picks = {}
    for c in crits:
        b = score(base[c], w, DEFAULT_THRESHOLD)
        best, bg = None, 0.0
        for i in range(len(sub)):
            g = score(surface(np.maximum(r0, cr[i]), c), w, DEFAULT_THRESHOLD) - b
            if g > bg:
                best, bg = i, g
        picks[c] = {"idx": best,
                    "lat": float(sub.loc[best, "lat"]) if best is not None else None,
                    "lon": float(sub.loc[best, "lon"]) if best is not None else None,
                    "dist_from_macro_m": round(float(sub.loc[best, "d_macro"])) if best is not None else None,
                    "covered_before_pct": 100 * b / TW,
                    "gain_pct": 100 * bg / TW}

    ref = picks["mean"]
    for c, p in picks.items():
        p["m_from_mean_choice"] = (round(float(haversine_m(
            ref["lat"], ref["lon"], p["lat"], p["lon"]))) if p["lat"] and ref["lat"] else None)

    if verbose:
        print("\n[pct] recommended site under each service definition")
        for c in ["mean", "p50", "p10", "p05", "p90"]:
            p = picks[c]
            print(f"      {c:>5}: {p['lat']:.5f},{p['lon']:.5f}  {p['dist_from_macro_m']:>5} m out"
                  f"  before {p['covered_before_pct']:5.1f}%  gain {p['gain_pct']:5.2f} pts"
                  f"  ({p['m_from_mean_choice']} m from the mean-criterion site)")

    # ---- 3. what fraction of cells are outage-limited at p10? -----------
    # A cell with P(outage) > 0.10 has a p10 of exactly zero regardless of how
    # fast it is when connected.  This is the number that says whether the
    # problem is throughput or availability.
    lim = {}
    for q in [0.05, 0.10, 0.50]:
        m = p0 > q
        lim[f"p{int(q*100):02d}"] = {
            "cells_capped_at_zero": int(m.sum()),
            "pct_of_cells": round(100 * m.mean(), 1),
            "pct_of_passes": round(100 * w[m].sum() / TW, 1)}
    if verbose:
        print("\n[pct] cells whose percentile is pinned to zero by outage alone")
        for k, v in lim.items():
            print(f"      {k}: {v['cells_capped_at_zero']:>4} cells "
                  f"({v['pct_of_cells']:>4.1f}%), {v['pct_of_passes']:>4.1f}% of passes")

    # ---- 3b. how long does an outage actually last? ---------------------
    # A percentile taken over instantaneous samples is the harshest possible
    # test: it counts a 5-second handover gap the same as a 10-minute hole.  A
    # 60-second file upload rides through the former and dies on the latter, so
    # before accepting "p10 = 0 for 90% of the route" we should measure the
    # duration distribution and say which kind of outage dominates.
    d = df.sort_values("ts").reset_index(drop=True)
    d["ts"] = pd.to_datetime(d["ts"])
    grp = (d["outage"] != d["outage"].shift()).cumsum()
    eps = []
    for _, g in d.groupby(grp):
        if not g["outage"].iloc[0]:
            continue
        dur = (g["ts"].iloc[-1] - g["ts"].iloc[0]).total_seconds()
        # a single-sample episode still occupies about one sampling interval
        eps.append(max(dur, 2.63))
    eps = np.array(eps)
    ep = {"n_episodes": int(len(eps)),
          "median_s": round(float(np.median(eps)), 1),
          "p75_s": round(float(np.quantile(eps, .75)), 1),
          "p90_s": round(float(np.quantile(eps, .90)), 1),
          "p99_s": round(float(np.quantile(eps, .99)), 1),
          "max_s": round(float(eps.max()), 1),
          "total_outage_min": round(float(eps.sum() / 60), 1)}
    # what share of total outage TIME sits in episodes longer than each cutoff?
    ep["time_share_by_duration"] = [
        {"longer_than_s": c,
         "episodes": int((eps > c).sum()),
         "pct_of_episodes": round(100 * float((eps > c).mean()), 1),
         "pct_of_outage_time": round(100 * float(eps[eps > c].sum() / eps.sum()), 1)}
        for c in [10, 30, 60, 120, 300]]
    if verbose:
        print(f"\n[pct] outage episodes: {ep['n_episodes']} of them, median "
              f"{ep['median_s']:.0f}s, p90 {ep['p90_s']:.0f}s, max {ep['max_s']/60:.1f} min")
        print("      share of total outage TIME in episodes longer than:")
        for t in ep["time_share_by_duration"]:
            print(f"        {t['longer_than_s']:>4}s : {t['pct_of_episodes']:>5.1f}% of episodes "
                  f"carry {t['pct_of_outage_time']:>5.1f}% of the outage time")

    # ---- 4. latency percentiles, for completeness -----------------------
    png = df["ping_ms"].dropna()
    lat = {f"p{int(q*100)}": round(float(png.quantile(q)), 1)
           for q in [0.5, 0.9, 0.95, 0.99]}
    lat["max"] = round(float(png.max()), 1)
    by_sinr = []
    for lo, hi in [(-25, -5), (-5, 0), (0, 5), (5, 10), (10, 40)]:
        g = df[df["sinr"].between(lo, hi) & df["ping_ms"].notna()]["ping_ms"]
        if len(g) > 30:
            by_sinr.append({"sinr_lo": lo, "sinr_hi": hi, "n": int(len(g)),
                            "p50": round(float(g.quantile(.5)), 1),
                            "p90": round(float(g.quantile(.9)), 1),
                            "p99": round(float(g.quantile(.99)), 1)})
    if verbose:
        print(f"\n[pct] ping percentiles: {lat}")

    out = {"conditional_curves": {str(k): [round(float(x), 2) for x in v]
                                 for k, v in cq.items()},
           "rsrp_grid": [float(x) for x in RSRP_GRID],
           "skew_table": skew, "coverage_by_criterion": cov,
           "picks": picks, "outage_limited": lim, "episodes": ep,
           "ping_percentiles": lat, "ping_by_sinr": by_sinr,
           "threshold": DEFAULT_THRESHOLD}
    (REPORTS / "percentiles.json").write_text(json.dumps(out, indent=2))
    if verbose:
        print(f"\n[pct] wrote reports/percentiles.json")
    return out


if __name__ == "__main__":
    run()
