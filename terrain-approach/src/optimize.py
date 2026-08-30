"""
Stage 3 -- choose the site.

Everything runs through ONE chain, used identically for the world as it is and
the world with an asset added:

    geometry -> RSRP -> { throughput distribution, P(outage) }
             -> a SERVICE VALUE, whose definition is a parameter (service.py)

A cell served by several nodes takes the best received power available to it, so
adding a transmitter can only help.  Before and after are computed by the same
code, so the DELTA is apples-to-apples -- the only number the challenge wants.

Solved greedily, not with a MILP: the objective is submodular, so greedy is
within 1 - 1/e of optimal, it needs no solver, and it runs in milliseconds,
which is what lets the identical routine run live in the browser.

WHAT CHANGED, AND WHY
---------------------
The first version optimised expected uplink and reported one site.  Measuring
percentiles showed the recommendation moves up to 2.6 km depending on which
statistic the operator writes into their requirement, and reverses direction --
a reliability target pulls the asset inward, an average target pushes it out.
It also showed 90% of route passes are outage-limited, meaning throughput is the
wrong quantity to optimise for them at all.

So this stage now does three things it did not:
  1. optimises under EVERY service definition, not one;
  2. carries a separate AVAILABILITY objective, because that is what actually
     fails here;
  3. reports a CONSENSUS site by minimax regret, since we do not get to know
     which definition the operator will use.
"""
import json

import numpy as np
import pandas as pd

from config import (ASSETS, AVAILABILITY_TARGET, CANDIDATE_SPACING_M,
                    CRITERIA_SWEEP, DATA, DEFAULT_THRESHOLD, HEADLINE_CRITERION,
                    N_ROBUSTNESS_DRAWS, N_SITES, RANDOM_SEED, REPORTS,
                    SERVING_SITE, UPLINK_THRESHOLDS)
from features import haversine_m, load_sites
from model import fit_outage_curve, fit_pathloss, fit_uplink_curve, rsrp_omni
from service import RSRP_GRID, availability_passes, build_criteria, covered


# ==========================================================================
# Candidates
# ==========================================================================

def make_candidates(df, pl, spacing=CANDIDATE_SPACING_M):
    """Thin the driven route to one candidate every `spacing` metres.

    Candidates sit ON the route because that is the only place we have evidence
    of physical access -- a road, right-of-way, usually poles and power.  A mast
    proposed in the middle of standing corn would score well and be undeployable.
    """
    pts = df[["lat", "lon"]].dropna().to_numpy()
    keep, kl, ko = [pts[0]], [pts[0][0]], [pts[0][1]]
    for p in pts[1:]:
        if haversine_m(p[0], p[1], np.array(kl), np.array(ko)).min() > spacing:
            keep.append(p); kl.append(p[0]); ko.append(p[1])
    cand = pd.DataFrame(keep, columns=["lat", "lon"])
    sites, _ = load_sites()
    slat, slon = sites[SERVING_SITE]
    cand["d_macro"] = haversine_m(cand["lat"], cand["lon"], slat, slon)
    cand["donor_rsrp"] = rsrp_omni(cand["d_macro"], pl)
    return cand[cand["d_macro"] > 400].reset_index(drop=True)


def rsrp_from(lat, lon, cells, pl, eirp_deficit_db, slope_scale=1.0):
    """RSRP delivered to every grid cell by an omni node at (lat, lon).

    The entire intervention model.  A node radiating X dB below the macro sits
    X dB lower on the fitted path-loss curve at every distance, so predicting a
    transmitter that has never existed is a shift and a distance recomputation.
    A booster trained on (lat, lon) has no equivalent move available to it.
    """
    d = haversine_m(lat, lon, cells["lat"].to_numpy(), cells["lon"].to_numpy())
    plx = dict(pl, slope_per_decade_db=pl["slope_per_decade_db"] * slope_scale)
    return rsrp_omni(d, plx, eirp_deficit_db)


def greedy(base_rsrp, cand_rsrp, crit, weight, k):
    """Maximum coverage under one service criterion, solved greedily."""
    base = covered(crit.fn(base_rsrp), weight, crit.threshold)
    chosen, cur, gains = [], base_rsrp.copy(), []
    for _ in range(k):
        best, bg, br = None, 1e-9, None
        for i, r in enumerate(cand_rsrp):
            if i in chosen:
                continue
            nr = np.maximum(cur, r)
            g = covered(crit.fn(nr), weight, crit.threshold) - base
            if g > bg:
                best, bg, br = i, g, nr
        if best is None:
            break
        chosen.append(best); cur = br; gains.append(bg)
    return chosen, gains, base


# ==========================================================================
# Main
# ==========================================================================

def run(verbose=True):
    rng = np.random.default_rng(RANDOM_SEED)
    df = pd.read_csv(DATA / "labeled.csv", dtype={"cellid": str})
    cells = pd.read_csv(DATA / "grid.csv")
    pl = fit_pathloss(df)
    iso = fit_uplink_curve(df)
    oc = fit_outage_curve(df, pl)
    crits, cq, tables = build_criteria(df, pl, iso, oc)

    cand = make_candidates(df, pl)
    weight = cells["route_density"].to_numpy(float)
    total_w = weight.sum()
    r0 = cells["rsrp"].to_numpy()
    head = crits[HEADLINE_CRITERION]

    if verbose:
        print(f"[optimise] {len(cand)} candidates, {len(cells)} demand cells")
        print(f"[optimise] headline criterion: {HEADLINE_CRITERION} "
              f"({head.label}) at {head.threshold} {head.unit}")

    results = {"headline_criterion": HEADLINE_CRITERION,
               "threshold_mbps": DEFAULT_THRESHOLD,
               "availability_target": AVAILABILITY_TARGET,
               "total_weight": float(total_w), "n_cells": int(len(cells)),
               "assets": {}, "criteria": {}}
    planner = {"thresholds": UPLINK_THRESHOLDS}

    for key, asset in ASSETS.items():
        feas = (cand["donor_rsrp"].to_numpy() >= asset["donor_rsrp_min"]
                if asset["needs_donor"] else np.ones(len(cand), bool))
        sub = cand[feas].reset_index(drop=True)
        cr = [rsrp_from(r.lat, r.lon, cells, pl, asset["eirp_deficit_db"])
              for r in sub.itertuples()]

        # ---- optimise under EVERY service definition --------------------
        # Not a robustness check bolted on the side: the criterion changes the
        # answer, so all of them are first-class results.
        per_crit, gain_matrix = {}, {}
        for cn in CRITERIA_SWEEP:
            c = crits[cn]
            ch, g, b = greedy(r0, cr, c, weight, 1)
            gain_matrix[cn] = np.array([
                covered(c.fn(np.maximum(r0, x)), weight, c.threshold) - b for x in cr])
            per_crit[cn] = {
                "label": c.label, "blurb": c.blurb,
                "threshold": c.threshold, "unit": c.unit,
                "covered_before_pct": 100 * b / total_w,
                "idx": int(ch[0]) if ch else None,
                "lat": float(sub.loc[ch[0], "lat"]) if ch else None,
                "lon": float(sub.loc[ch[0], "lon"]) if ch else None,
                "dist_from_macro_m": round(float(sub.loc[ch[0], "d_macro"])) if ch else None,
                "gain_pct": 100 * g[0] / total_w if g else 0.0,
            }

        # ---- consensus site: minimax regret across definitions ----------
        # We do not get to know which statistic the operator will write into
        # their requirement.  So rather than pick a winner under one and hope,
        # normalise each criterion's gains by its own best (regret in [0,1]) and
        # take the candidate whose WORST regret across criteria is smallest.
        # That is the site you can defend whatever definition turns up.
        R = np.stack([1 - (gain_matrix[cn] / gain_matrix[cn].max())
                      if gain_matrix[cn].max() > 0 else np.ones(len(sub))
                      for cn in CRITERIA_SWEEP])
        worst = R.max(axis=0)
        ci = int(np.argmin(worst))
        consensus = {
            "lat": float(sub.loc[ci, "lat"]), "lon": float(sub.loc[ci, "lon"]),
            "dist_from_macro_m": round(float(sub.loc[ci, "d_macro"])),
            "donor_rsrp_dbm": round(float(sub.loc[ci, "donor_rsrp"]), 1),
            "max_regret": round(float(worst[ci]), 3),
            "per_criterion_gain_pct": {cn: 100 * float(gain_matrix[cn][ci]) / total_w
                                       for cn in CRITERIA_SWEEP},
            "per_criterion_regret": {cn: round(float(R[i, ci]), 3)
                                     for i, cn in enumerate(CRITERIA_SWEEP)},
            "beats_single_criterion_worst_regret": {
                cn: round(float(worst[per_crit[cn]["idx"]]), 3)
                for cn in CRITERIA_SWEEP if per_crit[cn]["idx"] is not None},
        }

        # ---- how far apart do the criteria actually put the asset? ------
        # Reported because the consensus above only helps if the disagreement is
        # mild.  It is not: max regret 0.77 means that at its worst criterion
        # even the consensus site captures under a quarter of the achievable
        # gain.  The operationally honest output is therefore not a single pin
        # but the statement that the criterion must be fixed BEFORE the question
        # has an answer -- and this matrix is the evidence for it.
        names = [cn for cn in CRITERIA_SWEEP if per_crit[cn]["idx"] is not None]
        dis = {}
        for a in names:
            for b in names:
                if a < b:
                    dis[f"{a}|{b}"] = round(float(haversine_m(
                        per_crit[a]["lat"], per_crit[a]["lon"],
                        per_crit[b]["lat"], per_crit[b]["lon"])))
        spread = max(dis.values()) if dis else 0
        disagreement = {"pairwise_m": dis, "max_spread_m": spread,
                        "n_distinct_sites": len({(per_crit[c]["lat"], per_crit[c]["lon"])
                                                 for c in names})}

        # ---- headline solve, k sites ------------------------------------
        chosen, gains, base = greedy(r0, cr, head, weight, N_SITES)

        # ---- availability, the continuous view --------------------------
        av0 = availability_passes(r0, oc, weight)
        av_after = availability_passes(np.maximum(r0, cr[chosen[0]]), oc, weight)
        av_best_i = int(np.argmax([availability_passes(np.maximum(r0, x), oc, weight)
                                   for x in cr]))
        av_best = availability_passes(np.maximum(r0, cr[av_best_i]), oc, weight)

        # ---- the baseline the brief says to beat ------------------------
        obs = cells[cells["obs_uplink"].notna() & (cells["n"] >= 2)]
        worst_pt = obs.loc[obs["obs_uplink"].idxmin()]
        wr = rsrp_from(worst_pt["lat"], worst_pt["lon"], cells, pl, asset["eirp_deficit_db"])
        w_gain = covered(head.fn(np.maximum(r0, wr)), weight, head.threshold) - base

        # ---- uniform-weight sensitivity ---------------------------------
        u_ch, _, _ = greedy(r0, cr, head, np.ones(len(cells)), 1)

        rec = {
            "label": asset["label"], "eirp_deficit_db": asset["eirp_deficit_db"],
            "n_feasible": int(len(sub)), "n_candidates": int(len(cand)),
            "covered_before_pct": 100 * base / total_w,
            "sites": [{"rank": i + 1, "lat": float(sub.loc[c, "lat"]),
                       "lon": float(sub.loc[c, "lon"]),
                       "dist_from_macro_m": round(float(sub.loc[c, "d_macro"])),
                       "donor_rsrp_dbm": round(float(sub.loc[c, "donor_rsrp"]), 1),
                       "cumulative_gain_pct": 100 * g / total_w}
                      for i, (c, g) in enumerate(zip(chosen, gains))],
            "worst_point_baseline": {
                "lat": float(worst_pt["lat"]), "lon": float(worst_pt["lon"]),
                "observed_uplink_mbps": float(worst_pt["obs_uplink"]),
                "dist_from_macro_m": round(float(worst_pt["dist_m"])),
                "gain_pct": 100 * w_gain / total_w},
            "optimiser_vs_worst_point_ratio": (gains[0] / w_gain) if w_gain > 0 else None,
            "uniform_weight_sensitivity": {
                "same_choice": bool(u_ch and chosen and u_ch[0] == chosen[0]),
                "distance_between_choices_m": (
                    round(float(haversine_m(sub.loc[chosen[0], "lat"], sub.loc[chosen[0], "lon"],
                                            sub.loc[u_ch[0], "lat"], sub.loc[u_ch[0], "lon"])))
                    if u_ch and chosen else None)},
            "by_criterion": per_crit,
            "consensus": consensus,
            "criterion_disagreement": disagreement,
            "availability": {
                "passes_with_service_before": round(av0, 1),
                "passes_with_service_after_headline": round(av_after, 1),
                "passes_restored_headline": round(av_after - av0, 1),
                "best_site_lat": float(sub.loc[av_best_i, "lat"]),
                "best_site_lon": float(sub.loc[av_best_i, "lon"]),
                "best_site_dist_m": round(float(sub.loc[av_best_i, "d_macro"])),
                "passes_restored_best": round(av_best - av0, 1),
                "pct_of_all_passes": 100 * (av_best - av0) / total_w},
        }

        # ---- robustness, under the headline criterion -------------------
        sd = pl["residual_sd_db"]
        wins = np.zeros(len(sub), int)
        for _ in range(N_ROBUSTNESS_DRAWS):
            shadow = rng.normal(0, sd, len(cells))
            ss = rng.normal(1.0, 0.05)
            crd = [rsrp_from(r.lat, r.lon, cells, pl, asset["eirp_deficit_db"], ss) + shadow
                   for r in sub.itertuples()]
            c_d, _, _ = greedy(r0 + shadow, crd, head, weight, 1)
            if c_d:
                wins[c_d[0]] += 1
        freq = wins / N_ROBUSTNESS_DRAWS
        dref = haversine_m(sub.loc[chosen[0], "lat"], sub.loc[chosen[0], "lon"],
                           sub["lat"].to_numpy(), sub["lon"].to_numpy())
        rec["robustness"] = {
            "n_draws": N_ROBUSTNESS_DRAWS, "n_feasible_candidates": int(len(sub)),
            "random_pick_baseline": 1.0 / len(sub),
            "exact_site_frequency": float(freq[chosen[0]]),
            "within_500m_frequency": float(freq[dref <= 500].sum()),
            "within_1km_frequency": float(freq[dref <= 1000].sum()),
            "within_2km_frequency": float(freq[dref <= 2000].sum()),
            "top5": [{"lat": float(sub.loc[i, "lat"]), "lon": float(sub.loc[i, "lon"]),
                      "freq": float(freq[i]), "m_from_recommendation": round(float(dref[i]))}
                     for i in np.argsort(-freq)[:5] if freq[i] > 0]}
        after = head.fn(np.maximum(r0, cr[chosen[0]]))
        before = head.fn(r0)
        gained = (after >= head.threshold) & (before < head.threshold)
        rec["impact"] = {
            "cells_converted": int(gained.sum()),
            "passes_converted": int(weight[gained].sum()),
            "route_km_converted": round(float(gained.sum()) * 0.2, 1),
            "addressable_deficit_pct": 100 * (total_w - base) / total_w,
            "share_of_deficit_closed_pct": 100 * gains[0] / (total_w - base) if total_w > base else 0.0}
        results["assets"][key] = rec

        if verbose:
            print(f"\n[optimise] {asset['label']}: {len(sub)}/{len(cand)} feasible")
            print(f"[optimise]   site by criterion:")
            for cn in CRITERIA_SWEEP:
                p = per_crit[cn]
                print(f"               {cn:>12} ({p['label']:<18}) "
                      f"{p['dist_from_macro_m']:>5} m out, before {p['covered_before_pct']:5.1f}%, "
                      f"gain {p['gain_pct']:5.2f} pts")
            print(f"[optimise]   criteria place it at {disagreement['n_distinct_sites']} distinct sites, "
                  f"max spread {disagreement['max_spread_m']} m")
            print(f"[optimise]   CONSENSUS site {consensus['dist_from_macro_m']} m out, "
                  f"max regret {consensus['max_regret']:.2f} "
                  f"(single-criterion picks reach {min(consensus['beats_single_criterion_worst_regret'].values()):.2f}"
                  f"–{max(consensus['beats_single_criterion_worst_regret'].values()):.2f})")
            print(f"[optimise]   availability: best site restores "
                  f"{rec['availability']['passes_restored_best']} passes "
                  f"({rec['availability']['pct_of_all_passes']:.1f}% of all) at "
                  f"{rec['availability']['best_site_dist_m']} m out")
            print(f"[optimise]   headline gain {rec['sites'][0]['cumulative_gain_pct']:.2f} pts vs "
                  f"worst-point {rec['worst_point_baseline']['gain_pct']:.2f}, "
                  f"selected in {100*freq[chosen[0]]:.0f}% of draws (2 km: "
                  f"{100*rec['robustness']['within_2km_frequency']:.0f}%)")

        if key == "relay":
            planner["candidates"] = [
                {"lat": round(float(r["lat"]), 6), "lon": round(float(r["lon"]), 6),
                 "donor": round(float(r["donor_rsrp"]), 1), "freq": round(float(freq[i]), 3)}
                for i, r in sub.iterrows()]
            planner["recommended"] = rec["sites"]
            planner["baseline"] = rec["worst_point_baseline"]
            planner["consensus"] = consensus
            planner["by_criterion"] = per_crit

    # ---- second objective: where to MEASURE next -------------------------
    unc = (cells["ul_hi"] - cells["ul_lo"]).to_numpy() * np.sqrt(weight)
    picks, taken = [], []
    for _ in range(5):
        m = unc.copy()
        for t in taken:
            m[haversine_m(cells.loc[t, "lat"], cells.loc[t, "lon"],
                          cells["lat"].to_numpy(), cells["lon"].to_numpy()) < 800] = -1
        j = int(np.argmax(m)); taken.append(j)
        picks.append({"lat": float(cells.loc[j, "lat"]), "lon": float(cells.loc[j, "lon"]),
                      "band_mbps": round(float(cells.loc[j, "ul_hi"] - cells.loc[j, "ul_lo"]), 1),
                      "route_density": int(cells.loc[j, "route_density"]),
                      "dist_from_macro_m": round(float(cells.loc[j, "dist_m"]))})
    results["measurement_campaign"] = picks

    # ---- threshold and EIRP sensitivity (headline criterion) -------------
    asset = ASSETS["relay"]
    sub = cand[cand["donor_rsrp"] >= asset["donor_rsrp_min"]].reset_index(drop=True)
    cr = [rsrp_from(r.lat, r.lon, cells, pl, asset["eirp_deficit_db"]) for r in sub.itertuples()]
    sens = {}
    for t in UPLINK_THRESHOLDS:
        c2, _, _ = build_criteria(df, pl, iso, oc, threshold=t)
        h2 = c2[HEADLINE_CRITERION]
        c, g, b = greedy(r0, cr, h2, weight, 1)
        sens[str(t)] = {"covered_before_pct": 100 * b / total_w,
                        "gain_pct": 100 * g[0] / total_w if g else 0.0,
                        "lat": float(sub.loc[c[0], "lat"]) if c else None,
                        "lon": float(sub.loc[c[0], "lon"]) if c else None}
    results["threshold_sensitivity"] = sens

    eirp_sweep = {}
    for dfc in [10.0, 15.0, 20.0, 26.0, 32.0]:
        crd = [rsrp_from(r.lat, r.lon, cells, pl, dfc) for r in sub.itertuples()]
        c, g, b = greedy(r0, crd, head, weight, 1)
        rr = np.logspace(1.5, 4.2, 400)
        ok = head.fn(rsrp_omni(rr, pl, dfc)) >= head.threshold
        conv = (head.fn(np.maximum(r0, crd[c[0]])) >= head.threshold) & (head.fn(r0) < head.threshold)
        eirp_sweep[f"{dfc:.0f}dB"] = {
            "gain_pct": 100 * g[0] / total_w if g else 0.0,
            "cells_converted": int(conv.sum()),
            "service_radius_m": round(float(rr[ok].max())) if ok.any() else 0,
            "lat": float(sub.loc[c[0], "lat"]) if c else None,
            "lon": float(sub.loc[c[0], "lon"]) if c else None,
            "dist_from_macro_m": round(float(sub.loc[c[0], "d_macro"])) if c else None}
    results["eirp_sensitivity"] = eirp_sweep

    # ---- planner payload -------------------------------------------------
    # The browser gets the fitted constants and every service lookup table, so
    # it runs the same model itself -- including switching criterion live.
    planner["curves"] = {
        "uplink": {"x": [round(float(v), 2) for v in iso.X_thresholds_],
                   "y": [round(float(v), 2) for v in iso.y_thresholds_]},
        "outage": {"x": [round(float(v), 2) for v in oc.X_thresholds_],
                   "y": [round(float(v), 4) for v in oc.y_thresholds_]}}
    planner["service_tables"] = {
        "rsrp": [float(v) for v in RSRP_GRID],
        "p05": [round(float(v), 2) for v in tables[0.05]],
        "p10": [round(float(v), 2) for v in tables[0.10]],
        "p50": [round(float(v), 2) for v in tables[0.50]],
        "p90": [round(float(v), 2) for v in tables[0.90]]}
    planner["criteria_meta"] = {cn: {"label": crits[cn].label, "blurb": crits[cn].blurb,
                                     "unit": crits[cn].unit, "threshold": crits[cn].threshold}
                                for cn in CRITERIA_SWEEP}
    planner["headline_criterion"] = HEADLINE_CRITERION
    planner["availability_target"] = AVAILABILITY_TARGET
    planner["pathloss"] = {"intercept": pl["intercept_dbm"], "slope": pl["slope_per_decade_db"],
                           "sigma": pl["residual_sd_db"], "n": pl["path_loss_exponent_n"]}
    planner["assets"] = {k: {"label": v["label"], "deficit": v["eirp_deficit_db"],
                             "needs_donor": v["needs_donor"], "donor_min": v["donor_rsrp_min"]}
                         for k, v in ASSETS.items()}
    planner["cells"] = [{"lat": round(float(r["lat"]), 5), "lon": round(float(r["lon"]), 5),
                         "w": int(r["route_density"]), "r": round(float(r["rsrp"]), 1),
                         "o": (round(float(r["obs_uplink"]), 1) if pd.notna(r["obs_uplink"]) else None)}
                        for _, r in cells.iterrows()]
    sites, _ = load_sites()
    planner["macro"] = {"lat": sites[SERVING_SITE][0], "lon": sites[SERVING_SITE][1],
                        "name": SERVING_SITE}
    planner["measurement"] = picks
    planner["route"] = [[round(float(a), 5), round(float(b), 5)]
                        for a, b in df[["lat", "lon"]].dropna().to_numpy()[::4]]

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "results.json").write_text(json.dumps(results, indent=2))
    (DATA / "planner_data.json").write_text(json.dumps(planner, separators=(",", ":")))
    if verbose:
        print(f"\n[optimise] wrote reports/results.json, data/planner_data.json "
              f"({(DATA/'planner_data.json').stat().st_size/1e6:.1f} MB)")
    return results, planner


if __name__ == "__main__":
    run()
