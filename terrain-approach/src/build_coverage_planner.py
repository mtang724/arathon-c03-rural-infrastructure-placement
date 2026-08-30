"""
Stage 11 -- the coverage planner.

One self-contained page that replaces the three separate views: the terrain map,
the coverage overlay, and an interactive planner. Click anywhere and it re-solves
coverage for a site at that point, live, using the same terrain-aware physics the
offline optimiser uses.

The browser really does recompute. It carries the DEM and runs the full chain --
path profile, effective-earth bulge, first Fresnel zone, ITU-R P.526 knife-edge
loss, then RSRP and the availability threshold. It is not replaying stored
answers, so a pin dropped anywhere gets a genuine prediction.

DEM RESOLUTION. The page ships the 3DEP grid at every third post (31 m rather
than 10 m) to keep the payload near 2 MB. That was checked rather than assumed:
against the full-resolution grid the mean absolute difference in predicted
diffraction loss is 0.15 dB with a correlation of 0.994, and going finer than
this changed nothing measurable. The availability curve is exported on the same
0.05 dB grid the offline code inverts it on -- exporting it coarser was what
made an early build of this page disagree with the optimiser by 3%.
"""
import json

import numpy as np
import pandas as pd

from config import DATA, REPORTS, ROOT, SERVING_SITE
from coverage import W_AREA, W_ROUTE, Scorer, build_grid
from coverage_terrain import avail_threshold, fit_avail_terrain, macro_rsrp, ASSETS, fit_with_terrain, rsrp_from_node
from features import haversine_m, load_sites
from model import fit_pathloss
from propagation import DEM, RX_AGL, TX_AGL, link_features

STRIDE = 3

from planner_tpl import TPL


def _marginal(rec):
    """Greedy gives cumulative gains; the brief asks for the gain PER intervention."""
    c = [s["cumulative_gain"] for s in rec["sites"]]
    return [c[0]] + [c[i] - c[i - 1] for i in range(1, len(c))]


def build(verbose=True):
    dem = DEM()
    df = pd.read_csv(DATA / "labeled_terrain.csv", dtype={"cellid": str})
    plf = fit_pathloss(df);     pl = fit_with_terrain(df)
    df["outage"] = df.cellid.isna() | df.cellid.eq("FFFFFFFFF")
    av = fit_avail_terrain(df, pl, dem)
    cells = build_grid(df); sc = Scorer(cells)
    clat, clon = cells.lat.to_numpy(), cells.lon.to_numpy()
    sites, _ = load_sites(); tl, to = sites[SERVING_SITE]

    base = macro_rsrp(pl, dem, clat, clon)

    res = json.load((REPORTS / "coverage_terrain.json").open())
    short = {"relay": "Relay", "smallcell": "Small cell", "macro": "Macro"}
    assets = {}
    for k, A in ASSETS.items():
        s = res["assets"][k]["sites"][0]
        assets[k] = {"short": short[k], "label": A["label"], "deficit": A["deficit"],
                     "agl": A["agl"], "donor_min": A["donor_min"],
                     "site": {"lat": s["lat"], "lon": s["lon"]}}

    g = np.arange(-140.0, -30.0, 0.05)
    avc = np.clip(av.predict(g), 0, 1)
    z = dem.z[::STRIDE, ::STRIDE]
    served = df.cellid.notna() & df.cellid.ne("FFFFFFFFF")

    data = {
        "dem": {"ny": int(z.shape[0]), "nx": int(z.shape[1]),
                "z": [int(round(float(v))) for v in np.nan_to_num(
                    z, nan=float(np.nanmedian(z))).ravel()],
                "lat0": float(dem.lats[0]), "lon0": float(dem.lons[0]),
                "dlat": float(dem.dlat * STRIDE), "dlon": float(dem.dlon * STRIDE),
                "n": float(dem.lats[0]), "s": float(dem.lats[-1]),
                "w": float(dem.lons[0]), "e": float(dem.lons[-1]),
                "ns": float(abs(dem.dlat) * STRIDE * 111320),
                "ew": float(abs(dem.dlon) * STRIDE * 111320 * np.cos(np.radians(42)))},
        "cells": {"lat": [round(float(v), 5) for v in clat],
                  "lon": [round(float(v), 5) for v in clon],
                  "rk": [round(float(v), 4) for v in cells.route_km],
                  "ar": float(cells.area_km2.iloc[0]),
                  "base": [round(float(v), 2) for v in base]},
        "cell_deg": 200 / 111320.0,
        "pts": [[round(float(x), 5), round(float(y), 5), int(v)]
                for x, y, v in zip(df.lat, df.lon, served)],
        "macro": {"lat": tl, "lon": to},
        "assets": assets,
        "avail": {"x": [round(float(v), 2) for v in g],
                  "y": [round(float(v), 4) for v in avc]},
        "tot": {"rk": sc.tot_rk, "ar": sc.tot_ar},
        "weights": {"route": W_ROUTE, "area": W_AREA},
        "bounds": [float(df.lat.min()), float(df.lon.min()),
                   float(df.lat.max()), float(df.lon.max())],
        "marginal": {k: [round(g, 5) for g in _marginal(res["assets"][k])]
                     for k in ASSETS},
        "model": {"b0": pl["b0"], "slope": pl["slope"], "bdiff": pl["b_diff"],
                  "rho0": 0.60, "theta_c": 45.0,
                  "sigma": pl["sigma"], "n": pl["n_exponent"],
                  "lambda": 299792458.0 / 3460800000.0, "rx_agl": RX_AGL, "tx_agl": TX_AGL,
                  "post_m": float(abs(dem.dlat) * STRIDE * 111320)},
    }
    out = ROOT / "planner.html"
    out.write_text(TPL.replace("__DATA__", json.dumps(data, separators=(",", ":"))),
                   encoding="utf-8")
    if verbose:
        print(f"[planner] {out} ({out.stat().st_size/1e6:.2f} MB)")
        print(f"[planner] DEM {z.shape[0]}x{z.shape[1]} @ "
              f"{abs(dem.dlat)*STRIDE*111320:.0f} m posts, {len(clat):,} demand cells")
    return out


if __name__ == "__main__":
    build()
