"""
Stage 5 -- compute everything the analysis report plots, plus a palette check.

Writes reports/analysis.json.  Nothing here changes the model; it only measures
it from angles the pipeline does not report on its own.
"""
import json
import sys

import numpy as np
import pandas as pd

from config import (ASSETS, DATA, DEFAULT_THRESHOLD, REPORTS, SERVING_SITE)
from features import haversine_m, load_sites
from model import (fit_outage_curve, fit_pathloss, fit_uplink_curve, rsrp_omni,
                   rsrp_macro)
from optimize import greedy, make_candidates, rsrp_from
from service import build_criteria, covered


# ==========================================================================
# Palette validation -- OKLab dE with CVD simulation, in-process
# (the skill ships a node validator; no node on this box, so the same six
#  checks are implemented here rather than eyeballed)
# ==========================================================================

def _srgb_lin(c):
    c = np.asarray(c, float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _oklab(rgb):
    r, g, b = _srgb_lin(rgb)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = np.cbrt(l), np.cbrt(m), np.cbrt(s)
    return np.array([
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_])


def _cvd(rgb, kind):
    """Brettel/Vienot-style dichromat simulation in linear LMS."""
    r, g, b = _srgb_lin(rgb)
    L = 0.31399022 * r + 0.63951294 * g + 0.04649755 * b
    M = 0.15537241 * r + 0.75789446 * g + 0.08670142 * b
    S = 0.01775239 * r + 0.10944209 * g + 0.87256922 * b
    if kind == "protan":
        L = 1.05118294 * M - 0.05116099 * S
    elif kind == "deutan":
        M = 0.9513092 * L + 0.04866992 * S
    else:  # tritan
        S = -0.86744736 * L + 1.86727089 * M
    r2 = 5.47221206 * L - 4.6419601 * M + 0.16963708 * S
    g2 = -1.1252419 * L + 2.29317094 * M - 0.1678952 * S
    b2 = 0.02980165 * L - 0.19318073 * M + 1.16364789 * S
    lin = np.clip([r2, g2, b2], 0, 1)
    srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return np.clip(srgb, 0, 1) * 255


def _hex2rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], float)


def _contrast(fg, bg):
    def lum(c):
        r, g, b = _srgb_lin(c)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    a, b_ = lum(fg), lum(bg)
    hi, lo = max(a, b_), min(a, b_)
    return (hi + 0.05) / (lo + 0.05)


def validate_palette(colors, surfaces=("#FBFCFA", "#0E1512")):
    """The six checks. dE is OKLab distance x100; >=8 target, <15 normal-vision FAIL."""
    out = {"colors": colors, "pairs": [], "contrast": [], "verdict": "PASS"}
    rgbs = [_hex2rgb(c) for c in colors]
    for i in range(len(colors)):
        for j in range(i + 1, len(colors)):
            row = {"a": colors[i], "b": colors[j]}
            row["normal"] = round(float(np.linalg.norm(
                _oklab(rgbs[i]) - _oklab(rgbs[j])) * 100), 1)
            for k in ("protan", "deutan", "tritan"):
                row[k] = round(float(np.linalg.norm(
                    _oklab(_cvd(rgbs[i], k)) - _oklab(_cvd(rgbs[j], k))) * 100), 1)
            row["min_cvd"] = min(row["protan"], row["deutan"], row["tritan"])
            row["status"] = ("FAIL_NORMAL" if row["normal"] < 15 else
                             "PASS" if row["min_cvd"] >= 8 else
                             "FLOOR" if row["min_cvd"] >= 6 else "FAIL_CVD")
            if row["status"].startswith("FAIL"):
                out["verdict"] = "FAIL"
            out["pairs"].append(row)
    for c in colors:
        for s in surfaces:
            r = round(float(_contrast(_hex2rgb(c), _hex2rgb(s))), 2)
            out["contrast"].append({"color": c, "surface": s, "ratio": r,
                                    "status": "PASS" if r >= 3.0 else "WARN"})
    return out


# ==========================================================================
# Analysis
# ==========================================================================

def run(verbose=True):
    df = pd.read_csv(DATA / "labeled.csv", dtype={"cellid": str})
    cells = pd.read_csv(DATA / "grid.csv")
    pl = fit_pathloss(df)
    iso = fit_uplink_curve(df)
    oc = fit_outage_curve(df, pl)
    res = json.load((REPORTS / "results.json").open())
    mod = json.load((REPORTS / "model.json").open())

    # The report plots whatever the pipeline's headline service definition is,
    # so it cannot hard-code "expected uplink" any more.
    crits, _, _ = build_criteria(df, pl, iso, oc)
    head = crits[res["headline_criterion"]]
    expected_uplink = lambda rs, _i=None, _o=None: head.fn(rs)

    # Both themes are validated, because dark mode gets its own steps rather
    # than an automatic flip.  Pairs that land on the CVD "floor" (dE 6-8) are
    # legal only with secondary encoding -- on this page every such pair is also
    # separated by a text label or an outline, never by hue alone.
    A = {"palette": {"light": validate_palette(
             ["#0F6E70", "#8F6200", "#5B3A9B", "#8C1D40"], surfaces=("#FBFCFA",)),
         "dark": validate_palette(
             ["#4FB3B4", "#D9A227", "#A98BE0", "#E86A93"], surfaces=("#0E1512",))},
         "headline_criterion_label": head.label}

    # ---- 1. the asymmetry, binned by distance --------------------------
    edges = [0, 500, 1000, 2000, 3000, 4000, 6000, 8000, 13000]
    df["dbin"] = pd.cut(df["dist_m"], edges)
    rows = []
    for b, g in df.groupby("dbin", observed=True):
        rows.append({
            "lo": int(b.left), "hi": int(b.right), "n": int(len(g)),
            "mid": float(np.sqrt(max(b.left, 100) * b.right)),
            "rsrp": _f(g["rsrp"].median()), "sinr": _f(g["sinr"].median()),
            "ul": _f(g["uplink"].median()), "dl": _f(g["downlink"].median()),
            "ul_p10": _f(g["uplink"].quantile(.1)), "ul_p90": _f(g["uplink"].quantile(.9)),
            "dl_p10": _f(g["downlink"].quantile(.1)), "dl_p90": _f(g["downlink"].quantile(.9)),
            "outage": _f(g["outage"].mean()), "ping": _f(g["ping_ms"].median()),
        })
    A["distance_bins"] = rows

    # normalised decay: each measure as % of its near-tower value
    b0 = rows[0]
    A["decay"] = [{"lo": r["lo"], "hi": r["hi"],
                   "ul": 100 * r["ul"] / b0["ul"], "dl": 100 * r["dl"] / b0["dl"]}
                  for r in rows if r["ul"] and r["dl"]]

    # ---- 2. threshold exceedance curves --------------------------------
    ul = df["uplink"].dropna(); dl = df["downlink"].dropna()
    ts = list(range(0, 101))
    A["exceedance"] = {"t": ts,
                       "ul": [_f(100 * (ul >= t).mean()) for t in ts],
                       "dl": [_f(100 * (dl >= t).mean()) for t in ts]}

    # ---- 3. path-loss fit ----------------------------------------------
    d = df[df["site"].eq(SERVING_SITE) & df["rsrp"].notna() & (df["dist_m"] > 30)]
    rng = np.random.default_rng(0)
    idx = rng.choice(len(d), size=min(1400, len(d)), replace=False)
    A["pathloss_scatter"] = [[round(float(x), 3), round(float(y), 1)] for x, y in
                             zip(d["log_d"].to_numpy()[idx], d["rsrp"].to_numpy()[idx])]
    xs = np.linspace(d["log_d"].min(), d["log_d"].max(), 60)
    A["pathloss_fit"] = {
        "x": [round(float(v), 3) for v in xs],
        "fitted": [round(float(pl["intercept_dbm"] + pl["slope_per_decade_db"] * v), 1) for v in xs],
        "naive": None, "n": pl["path_loss_exponent_n"],
        "n_naive": pl["naive_exponent_n_no_azimuth"],
        "sigma": pl["residual_sd_db"], "r2": pl["r2"], "r2_naive": pl["naive_r2"]}
    Xd = np.column_stack([np.ones(len(d)), d["log_d"].to_numpy()])
    cd, *_ = np.linalg.lstsq(Xd, d["rsrp"].to_numpy(), rcond=None)
    A["pathloss_fit"]["naive"] = [round(float(cd[0] + cd[1] * v), 1) for v in xs]

    # ---- 4. residual semivariogram (the ray-tracing headroom argument) --
    resid = d["rsrp"].to_numpy() - (Xd @ cd)
    s = rng.choice(len(d), size=min(1100, len(d)), replace=False)
    la, lo = np.radians(d["lat"].to_numpy()[s]), np.radians(d["lon"].to_numpy()[s])
    rr = resid[s]
    a = (np.sin((la[:, None] - la[None, :]) / 2) ** 2
         + np.cos(la[:, None]) * np.cos(la[None, :])
         * np.sin((lo[:, None] - lo[None, :]) / 2) ** 2)
    DD = 2 * 6371000 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    RD = np.abs(rr[:, None] - rr[None, :])
    iu = np.triu_indices(len(s), 1)
    DD, RD = DD[iu], RD[iu]
    vg = []
    for lo_, hi_ in [(0, 50), (50, 150), (150, 400), (400, 1000), (1000, 3000), (3000, 20000)]:
        m = (DD >= lo_) & (DD < hi_)
        if m.sum() > 50:
            vg.append({"lo": lo_, "hi": hi_, "n": int(m.sum()), "v": _f(RD[m].mean())})
    A["semivariogram"] = {"bins": vg, "random_pair": _f(RD.mean())}

    # ---- 5. the two isotonic curves ------------------------------------
    grid = np.linspace(-125, -50, 160)
    A["curves"] = {"x": [round(float(v), 1) for v in grid],
                   "uplink": [_f(v) for v in iso.predict(grid)],
                   "outage": [_f(v, 4) for v in oc.predict(grid)],
                   "expected": [_f(v) for v in expected_uplink(grid, iso, oc)]}

    # ---- 6. validation -------------------------------------------------
    v = mod["validation"]["uplink"]
    A["validation"] = {
        "ladder": sorted([
            {"name": "Isotonic given measured RSRP", "mae": v["baselines"]["isotonic_given_measured_rsrp_mae"], "kind": "ceiling"},
            {"name": "Physics chain (shipped)", "mae": v["baselines"]["physics_chain_mae"], "kind": "shipped"},
            {"name": "Gradient boosting on coords", "mae": v["spatial_block"]["mae"], "kind": "alt"},
            {"name": "Nearest measured neighbour", "mae": v["baselines"]["nearest_neighbour_mae"], "kind": "base"},
            {"name": "Global mean", "mae": v["baselines"]["global_mean_mae"], "kind": "base"},
            {"name": "Distance-only linear", "mae": v["baselines"]["distance_only_mae"], "kind": "base"},
        ], key=lambda r: r["mae"]),
        "leakage": {
            "uplink_r2": {"random": v["random_split"]["r2"], "spatial": v["spatial_block"]["r2"]},
            "uplink_mae": {"random": v["random_split"]["mae"], "spatial": v["spatial_block"]["mae"]},
            "outage_auc": {"random": mod["validation"]["outage"]["random_split"]["auc"],
                           "spatial": mod["validation"]["outage"]["spatial_block"]["auc"]}},
        "per_fold": v.get("spatial_per_fold", []),
        "decomposition": {
            "total": v["baselines"]["physics_chain_mae"],
            "irreducible": v["baselines"]["isotonic_given_measured_rsrp_mae"],
            "propagation": v["baselines"]["physics_chain_mae"] - v["baselines"]["isotonic_given_measured_rsrp_mae"]},
        "calibration": mod["surface_agreement"]["outage_calibration"],
        "brier": mod["surface_agreement"]["outage_surface_brier_physics"]}

    # ---- 7. coverage vs threshold, before and after --------------------
    cand = make_candidates(df, pl)
    w = cells["route_density"].to_numpy(float); TW = w.sum()
    cr0 = cells["rsrp"].to_numpy()
    rec = res["assets"]["relay"]["sites"][0]
    rr_rec = np.maximum(cr0, rsrp_from(rec["lat"], rec["lon"], cells, pl,
                                       ASSETS["relay"]["eirp_deficit_db"]))
    wp = res["assets"]["relay"]["worst_point_baseline"]
    rr_wp = np.maximum(cr0, rsrp_from(wp["lat"], wp["lon"], cells, pl,
                                      ASSETS["relay"]["eirp_deficit_db"]))
    ts2 = list(range(1, 41))
    def cov(r, t):
        c2, _, _ = build_criteria(df, pl, iso, oc, threshold=t)
        h2 = c2[res["headline_criterion"]]
        return 100 * w[h2.fn(r) >= t].sum() / TW
    A["coverage_curve"] = {
        "t": ts2,
        "before": [_f(cov(cr0, t)) for t in ts2],
        "after_optimised": [_f(cov(rr_rec, t)) for t in ts2],
        "after_worstpoint": [_f(cov(rr_wp, t)) for t in ts2]}

    # ---- 8. greedy marginal gains --------------------------------------
    A["greedy"] = {}
    for k, asset in ASSETS.items():
        feas = (cand["donor_rsrp"].to_numpy() >= asset["donor_rsrp_min"]
                if asset["needs_donor"] else np.ones(len(cand), bool))
        sub = cand[feas].reset_index(drop=True)
        crs = [rsrp_from(r.lat, r.lon, cells, pl, asset["eirp_deficit_db"])
               for r in sub.itertuples()]
        ch, g, base = greedy(cr0, crs, head, w, 5)
        A["greedy"][k] = {"base_pct": 100 * base / TW,
                          "cumulative_pct": [_f(100 * x / TW) for x in g],
                          "marginal_pct": [_f(100 * (g[i] - (g[i - 1] if i else 0)) / TW)
                                           for i in range(len(g))]}

    # ---- 9. robustness: cumulative selection frequency vs radius -------
    rb = res["assets"]["relay"]["robustness"]
    A["robustness"] = {
        "radii": [0, 500, 1000, 2000],
        "cum": [rb["exact_site_frequency"], rb["within_500m_frequency"],
                rb["within_1km_frequency"], rb["within_2km_frequency"]],
        "random_pick": rb["random_pick_baseline"],
        "n_draws": rb["n_draws"], "n_candidates": rb["n_feasible_candidates"],
        "top5": rb["top5"],
        "smallcell": {"radii": [0, 500, 1000, 2000],
                      "cum": [res["assets"]["smallcell"]["robustness"][k] for k in
                              ["exact_site_frequency", "within_500m_frequency",
                               "within_1km_frequency", "within_2km_frequency"]]}}

    # ---- 10. map -------------------------------------------------------
    ub, ua = head.fn(cr0), head.fn(rr_rec)
    A["map"] = {
        "cells": [[round(float(r.lat), 5), round(float(r.lon), 5), int(r.route_density),
                   _f(ub[i]), _f(ua[i])] for i, r in enumerate(cells.itertuples())],
        "macro": dict(zip(("lat", "lon"), load_sites()[0][SERVING_SITE])),
        "recommended": {"lat": rec["lat"], "lon": rec["lon"]},
        "smallcell": {"lat": res["assets"]["smallcell"]["sites"][0]["lat"],
                      "lon": res["assets"]["smallcell"]["sites"][0]["lon"]},
        "worst": {"lat": wp["lat"], "lon": wp["lon"]},
        "measurement": res["measurement_campaign"],
        "candidates": [[round(float(r.lat), 5), round(float(r.lon), 5),
                        _f(r.donor_rsrp, 1)] for r in cand.itertuples()]}

    # ---- 10b. service-definition results -------------------------------
    A["criteria"] = {
        k: {"by_criterion": v["by_criterion"], "consensus": v["consensus"],
            "disagreement": v["criterion_disagreement"], "availability": v["availability"],
            "label": v["label"]}
        for k, v in res["assets"].items()}
    A["headline_criterion"] = res["headline_criterion"]

    # ---- 11. headline counters ----------------------------------------
    A["headline"] = {
        "rows": int(len(df)), "outage_rows": int(df["outage"].sum()),
        "outage_pct": _f(100 * df["outage"].mean()),
        "measured_rows": int(df["uplink"].notna().sum()),
        "ul_below_25_pct": _f(100 * (ul < 25).mean()),
        "dl_below_25_pct": _f(100 * (dl < 25).mean()),
        "ul_median": _f(ul.median()), "dl_median": _f(dl.median()),
        "cells": int(len(cells)), "passes": int(TW),
        "covered_before_pct": res["assets"]["relay"]["covered_before_pct"],
        "n_candidates": int(len(cand)),
        "relay": res["assets"]["relay"], "smallcell": res["assets"]["smallcell"],
        "eirp": res["eirp_sensitivity"], "threshold": res["threshold_sensitivity"]}

    (REPORTS / "analysis.json").write_text(json.dumps(A, separators=(",", ":")))
    if verbose:
        for mode in ("light", "dark"):
            p = A["palette"][mode]
            floors = [r for r in p["pairs"] if r["status"] == "FLOOR"]
            print(f"[analysis] palette {mode}: {p['verdict']}"
                  + (f"  ({len(floors)} pair(s) at the CVD floor, label-encoded)" if floors else ""))
        print(f"[analysis] wrote reports/analysis.json "
              f"({(REPORTS/'analysis.json').stat().st_size/1e6:.2f} MB)")
    return A


def _f(x, nd=2):
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return None
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    run()
