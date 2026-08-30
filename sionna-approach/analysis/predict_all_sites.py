"""Trace the WHOLE existing network -- all four sites, twelve sectors -- plus every
measured row including the no-service ones.

Two limitations of every surface so far, both fixed here.

PLAN.md 1.1: `predict_surface.py` hard-codes Agronomy's three sectors. That is right for
calibration and wrong for siting, because the "before" surface must be the coverage the
EXISTING NETWORK provides. Otherwise every gap Curtiss and Wilson Hall already fill gets
re-filled by our recommendation and the gain is overstated.

PLAN.md 1.2: 42% of rows (3,023) have no serving cell and have never been given to the
model. They are not missing data -- they are a measured no-service state, and they are the
training target for P(served). Without them the twin can only say "the tracer found no
path", never "there is no service here".

Research Park is a free negative control: it serves 0 of 7,144 rows, so a model that gives
it usable best-server coverage anywhere the van drove is wrong regardless of its RMSE.

usage: predict_all_sites.py <scene.xml> <h_ant> <out.npz> [grid_m]
"""
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
SCENE = BASE.parent / "scene"

# every sector of every site, from Base_Station_Information.yaml. Azimuths follow the
# 0/115/240 convention established for Agronomy from the measured bearing arcs; Curtiss
# is consistent with it, Wilson Hall has 106 samples on one sector so its orientation is
# ASSUMED, and Research Park never serves so its azimuths are untestable.
SECTOR_AZ = {"00B": 0.0, "015": 115.0, "01F": 240.0}
SITE_PREFIX = {"Agronomy Farm": "00019C", "Curtiss Farm": "000194",
               "Research Park": "000198", "Wilson Hall": "0001A0"}
FC = 3.4608e9


def _find_data():
    env = os.environ.get("COTS_DATA")
    if env:
        return Path(env)
    for c in (p / "extracted" / "COTS_Dataset" for p in BASE.parents):
        if (c / "COTS.csv").exists():
            return c
    raise SystemExit("COTS.csv not found")


def main():
    xml, H, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    grid_m = float(sys.argv[4]) if len(sys.argv) > 4 else 100.0
    import mitsuba as mi
    from sionna.rt import load_scene, Transmitter, Receiver, PlanarArray, PathSolver

    g = json.loads((SCENE / "georef.json").read_text())
    lat0r, lon0, R, K = (math.radians(g["origin_lat"]), g["origin_lon"],
                         g["radius"], g["k"])

    def from_geo(lat, lon):
        lat = np.radians(lat); lon = np.radians(lon - lon0)
        B = np.sin(lon) * np.cos(lat)
        return (0.5 * K * R * np.log((1 + B) / (1 - B)),
                K * R * (np.arctan(np.tan(lat) / np.cos(lon)) - lat0r))

    # EVERY row, not just the served ones
    df = pd.read_csv(_find_data() / "COTS.csv", dtype={"cellid": str})
    for c in ("rsrp", "sinr", "rsrq", "uplink", "downlink", "ping_ms"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["served"] = df.cellid.notna() & df.cellid.ne("FFFFFFFFF")
    df["x"], df["y"] = from_geo(df.lat.values, df.lon.values)
    print(f"{len(df):,} rows: {int(df.served.sum()):,} served, "
          f"{int((~df.served).sum()):,} no-service")

    scene = load_scene(str(SCENE / xml), merge_shapes=True)
    scene.frequency = FC
    assert "cuda" in mi.variant(), f"want a GPU variant, got {mi.variant()}"
    scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
    scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="tr38901", polarization="V")

    for site, pref in SITE_PREFIX.items():
        s = g["sites"][site]
        for suf, az in SECTOR_AZ.items():
            scene.add(Transmitter(name=pref + suf,
                                  position=[s["x"], s["y"], s["ground"] + H],
                                  orientation=[math.radians(90.0 - az), 0.0, 0.0]))
    tx_order = list(scene.transmitters)
    print(f"{len(tx_order)} sectors across {len(SITE_PREFIX)} sites at {H:g} m")

    def ground_z(x, y):
        o = mi.Point3f(np.asarray(x, np.float32), np.asarray(y, np.float32),
                       np.full(len(x), 600.0, np.float32))
        si = scene.mi_scene.ray_intersect(mi.Ray3f(o=o, d=mi.Vector3f(0, 0, -1)))
        return np.array(si.p.z), np.array(si.is_valid())

    pad = 1500.0
    gx = np.arange(df.x.min() - pad, df.x.max() + pad, grid_m)
    gy = np.arange(df.y.min() - pad, df.y.max() + pad, grid_m)
    GX, GY = np.meshgrid(gx, gy)
    grid_x, grid_y = GX.ravel(), GY.ravel()
    gz, gok = ground_z(grid_x, grid_y)
    mz, mok = ground_z(df.x.values, df.y.values)
    df = df[mok].reset_index(drop=True); mz = mz[mok]
    n_grid = int(gok.sum())
    ax = np.concatenate([grid_x[gok], df.x.values])
    ay = np.concatenate([grid_y[gok], df.y.values])
    az_ = np.concatenate([gz[gok], mz]) + 1.5
    print(f"receivers: {n_grid:,} grid + {len(df):,} measured = {len(ax):,}")

    solver = PathSolver()
    CH = int(os.environ.get("RT_CHUNK", 4000))
    parts, t0 = [], time.time()
    for lo in range(0, len(ax), CH):
        hi = min(lo + CH, len(ax))
        for nm in list(scene.receivers):
            scene.remove(nm)
        for i in range(lo, hi):
            scene.add(Receiver(name=f"r{i}", position=[float(ax[i]), float(ay[i]),
                                                       float(az_[i])]))
        p = solver(scene, max_depth=3, los=True, specular_reflection=True,
                   diffuse_reflection=False, refraction=False, synthetic_array=True)
        a, _ = p.cir(normalize_delays=False, out_type="numpy")
        parts.append(np.sum(np.abs(a) ** 2, axis=(1, 3, 4, 5)).astype(np.float32))
        print(f"  {hi:6d}/{len(ax)}  {time.time()-t0:6.1f}s", flush=True)
        del a, p
    pg = np.concatenate(parts, axis=0)

    np.savez_compressed(
        out, grid_x=grid_x[gok], grid_y=grid_y[gok], grid_z=gz[gok],
        grid_pg=pg[:n_grid], gx=gx, gy=gy, gok=gok, grid_m=grid_m,
        meas_x=df.x.values, meas_y=df.y.values, meas_lat=df.lat.values,
        meas_lon=df.lon.values, meas_pg=pg[n_grid:],
        meas_rsrp=df.rsrp.values, meas_sinr=df.sinr.values,
        meas_uplink=df.uplink.values, meas_downlink=df.downlink.values,
        meas_ping=df.ping_ms.values, meas_served=df.served.values,
        meas_cell=df.cellid.fillna("NONE").values,
        tx_order=np.array(tx_order), h_ant=H, xml=xml,
        site_x=g["sites"]["Agronomy Farm"]["x"], site_y=g["sites"]["Agronomy Farm"]["y"],
        site_ground=g["sites"]["Agronomy Farm"]["ground"],
        sites=np.array(list(SITE_PREFIX)))
    print(f"wrote {out}")

    # negative control, as an assertion rather than a paragraph
    order = tx_order
    rp = [i for i, t in enumerate(order) if str(t).startswith("000198")]
    best = pg[n_grid:].argmax(axis=1)
    share = float(np.mean(np.isin(best, rp)))
    print(f"\nNEGATIVE CONTROL -- Research Park serves 0 of 7,144 rows in the data.")
    print(f"  model makes it best-server on {share:.2%} of measured points")
    print("  (a correct model keeps this near zero)")


if __name__ == "__main__":
    main()
