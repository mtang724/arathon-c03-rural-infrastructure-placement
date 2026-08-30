"""Compute the sweeps and threshold table the deck now needs, cache to JSON."""
import json
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from config import DATA, REPORTS, SERVING_SITE
from coverage import Scorer, build_grid
from coverage_terrain import avail_threshold, fit_avail_terrain, macro_rsrp, ASSETS, fit_with_terrain, rsrp_from_node
from features import haversine_m, load_sites
from model import fit_pathloss
from propagation import DEM, TX_AGL, link_features

dem = DEM()
df = pd.read_csv(DATA / "labeled_terrain.csv", dtype={"cellid": str})
plf = fit_pathloss(df); pl = fit_with_terrain(df)
df["outage"] = df.cellid.isna() | df.cellid.eq("FFFFFFFFF")
av = fit_avail_terrain(df, pl, dem)
cells = build_grid(df); sc = Scorer(cells)
clat, clon = cells.lat.to_numpy(), cells.lon.to_numpy()
sites, _ = load_sites(); tl, to = sites[SERVING_SITE]

base = macro_rsrp(pl, dem, clat, clon)

res = json.load((REPORTS / "coverage_terrain.json").open())
s = res["assets"]["macro"]["sites"][0]
A = ASSETS["macro"]

out = {}

# ---- explicit service thresholds -------------------------------------------
Fs = link_features(dem, s["lat"], s["lon"], clat, clon, tx_agl=A["agl"])
ds = haversine_m(s["lat"], s["lon"], clat, clon)
after = np.maximum(base, rsrp_from_node(pl, ds, Fs["diff_db"], A["deficit"]))
rows = []
for p in (25, 50, 75, 90):
    t = avail_threshold(av, p / 100)
    rb, ab = sc.parts(base >= t); ra, aa = sc.parts(after >= t)
    rows.append({"pct": p,
                 "route_before": 100 * rb / sc.tot_rk, "route_after": 100 * ra / sc.tot_rk,
                 "area_before": 100 * ab / sc.tot_ar, "area_after": 100 * aa / sc.tot_ar})
out["thresholds"] = rows

# ---- sensitivity at the recommended site ------------------------------------
thr = avail_threshold(av, 0.50)
b0 = sc(base >= thr)
powers = [0, 5, 10, 15, 20, 26, 32]
out["sweep_power"] = [{"db": d, "gain": sc(np.maximum(
    base, rsrp_from_node(pl, ds, Fs["diff_db"], d)) >= thr) - b0} for d in powers]
masts = [6, 12, 20, 28, 37, 48, 60]
sw = []
for h in masts:
    F = link_features(dem, s["lat"], s["lon"], clat, clon, tx_agl=float(h))
    sw.append({"m": h, "gain": sc(np.maximum(
        base, rsrp_from_node(pl, ds, F["diff_db"], A["deficit"])) >= thr) - b0})
out["sweep_mast"] = sw

# ---- robustness distribution of the GAIN (not just which site wins) ---------
rng = np.random.default_rng(11)
sig, R0, TC = pl["sigma"], 0.60, 45.0
site_r = rsrp_from_node(pl, ds, Fs["diff_db"], A["deficit"])
bm = (np.degrees(np.arctan2(
    np.sin(np.radians(to - clon)) * np.cos(np.radians(tl)),
    np.cos(np.radians(clat)) * np.sin(np.radians(tl)) -
    np.sin(np.radians(clat)) * np.cos(np.radians(tl)) * np.cos(np.radians(to - clon)))) + 360) % 360
bs = (np.degrees(np.arctan2(
    np.sin(np.radians(s["lon"] - clon)) * np.cos(np.radians(s["lat"])),
    np.cos(np.radians(clat)) * np.sin(np.radians(s["lat"])) -
    np.sin(np.radians(clat)) * np.cos(np.radians(s["lat"])) * np.cos(np.radians(s["lon"] - clon)))) + 360) % 360
th = np.abs((bs - bm + 180) % 360 - 180)
w = np.sqrt(R0 * np.exp(-th / TC))
G = []
for _ in range(400):
    com = rng.normal(0, sig, len(cells))
    sm = np.sqrt(R0) * com + np.sqrt(1 - R0) * rng.normal(0, sig, len(cells))
    ss = w * com + np.sqrt(np.clip(1 - w**2, 0, 1)) * rng.normal(0, sig, len(cells))
    bb = base + sm
    G.append(sc(np.maximum(bb, site_r + ss) >= thr) - sc(bb >= thr))
G = np.array(G)
out["robust_gain"] = {"p10": float(np.percentile(G, 10)), "p50": float(np.median(G)),
                      "p90": float(np.percentile(G, 90)),
                      "pct_positive": float(100 * (G > 0.0005).mean()),
                      "n": len(G),
                      "hist": np.histogram(G, bins=16)[0].tolist(),
                      "edges": [float(x) for x in np.histogram(G, bins=16)[1]]}

rob = json.load((REPORTS / "robustness.json").open())
out["robust_models"] = [{"name": k.split("(")[0].strip(),
                         "exact": v["exact"], "within2": v["within_2km"]}
                        for k, v in rob["models"].items()]
out["fit"] = pl
# the deck's validation slide reads these straight out of the backtest
bt = json.load(open(REPORTS / "backtest.json"))
K = bt["B_out_of_sample"]["kmeans_on_position"]
W = bt["B_out_of_sample"]["angular_wedges"]
C = bt["C_coverage"]
out["backtest"] = {
    "rsrp_mae_in": bt["A_in_sample"]["mae"], "rsrp_rmse_in": bt["A_in_sample"]["rmse"],
    "rsrp_r2_in": bt["A_in_sample"]["r2"],
    "rsrp_mae_random": bt["B_out_of_sample"]["random_split"]["mae"],
    "rsrp_rmse_random": bt["B_out_of_sample"]["random_split"]["rmse"],
    "rsrp_r2_random": bt["B_out_of_sample"]["random_split"]["r2"],
    "rsrp_mae_spatial": K["mae"], "rsrp_rmse_spatial": K["rmse"], "rsrp_r2_spatial": K["r2"],
    "rsrp_rmse_wedge": W["rmse"], "rsrp_r2_wedge": W["r2"],
    "base_rate": C["base_rate"], "acc_model": C["cellwise_agreement"],
    "obs_pct": C["observed_pct"], "pred_pct": C["predicted_pct"],
    "brier": C["brier"], "cells": C["cells_compared"],
    "n_near": bt["fit"]["n_exponent"], "n_far": bt["fit"]["n_far"],
    "sigma": bt["fit"]["sigma"],
}
json.dump(out, open(REPORTS / "deck_extras.json", "w"), indent=2)
print("thresholds:", [(r["pct"], round(r["route_before"],1), round(r["route_after"],1)) for r in rows])
print("power sweep:", [(d["db"], round(d["gain"],3)) for d in out["sweep_power"]])
print("mast sweep :", [(d["m"], round(d["gain"],3)) for d in out["sweep_mast"]])
print("robust gain: p10 %.3f  med %.3f  p90 %.3f  positive %.0f%%" % (
    out["robust_gain"]["p10"], out["robust_gain"]["p50"],
    out["robust_gain"]["p90"], out["robust_gain"]["pct_positive"]))
print("wrote reports/deck_extras.json")
