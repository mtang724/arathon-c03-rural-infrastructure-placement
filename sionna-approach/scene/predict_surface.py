"""Predict RSRP over a grid AND at every measured point, in one ray-tracing pass.

The grid is what Challenge 3 needs (the 88.5% of the scene the drive never visited);
the measured points are what makes the grid believable. Calibration uses a spatially
blocked split, as the challenge brief requires, so the reported error is out-of-sample.

usage: predict_surface.py <scene.xml> <h_ant> <out.npz> [grid_m]
"""
import os
from pathlib import Path

# Paths resolve relative to this script so the tree can be moved or cloned anywhere.
BASE = str(Path(__file__).resolve().parent)


def _find_data():
    """Locate COTS.csv. Override with COTS_DATA=/path/to/dir."""
    env = os.environ.get("COTS_DATA")
    if env:
        return env
    here = Path(BASE)
    for cand in [here / "data", *(p / "extracted" / "COTS_Dataset" for p in here.parents)]:
        if (cand / "COTS.csv").exists():
            return str(cand)
    raise SystemExit("COTS.csv not found. Set COTS_DATA=/path/to/COTS_Dataset")

DATA = _find_data()
import json, math, sys, numpy as np, pandas as pd, mitsuba as mi
from sionna.rt import load_scene, Transmitter, Receiver, PlanarArray, PathSolver

FC = 3.4608e9
SECTORS = {"00019C00B": 0.0, "00019C015": 115.0, "00019C01F": 240.0}
XML, H, OUT = sys.argv[1], float(sys.argv[2]), sys.argv[3]
GRID = float(sys.argv[4]) if len(sys.argv) > 4 else 150.0
BLOCK = 2000.0                       # spatial block size for the train/test split

g = json.load(open(f"{BASE}/georef.json"))
LAT0, LON0, R, K = g["origin_lat"], g["origin_lon"], g["radius"], g["k"]
lat0r = math.radians(LAT0)

def fromGeo(lat, lon):
    lat = np.radians(lat); lon = np.radians(lon - LON0)
    B = np.sin(lon) * np.cos(lat)
    return (0.5 * K * R * np.log((1 + B) / (1 - B)),
            K * R * (np.arctan(np.tan(lat) / np.cos(lon)) - lat0r))

df = pd.read_csv(f"{DATA}/COTS.csv", dtype={"cellid": str})
df["rsrp"] = pd.to_numeric(df["rsrp"], errors="coerce")
df = df[df.cellid.isin(SECTORS) & df.rsrp.notna()].copy()
df["x"], df["y"] = fromGeo(df.lat.values, df.lon.values)
print(f"{len(df)} measured Agronomy rows", flush=True)

scene = load_scene(f"{BASE}/{XML}", merge_shapes=True)
scene.frequency = FC

def ground_z(x, y):
    o = mi.Point3f(np.asarray(x, np.float32), np.asarray(y, np.float32),
                   np.full(len(x), 600.0, np.float32))
    si = scene.mi_scene.ray_intersect(mi.Ray3f(o=o, d=mi.Vector3f(0, 0, -1)))
    return np.array(si.p.z), np.array(si.is_valid())

pad = 1500.0
gx = np.arange(df.x.min() - pad, df.x.max() + pad, GRID)
gy = np.arange(df.y.min() - pad, df.y.max() + pad, GRID)
GX, GY = np.meshgrid(gx, gy)
grid_x, grid_y = GX.ravel(), GY.ravel()
gz, gok = ground_z(grid_x, grid_y)
print(f"grid {len(gx)} x {len(gy)} = {grid_x.size:,} points, {gok.sum():,} on terrain", flush=True)

mz, mok = ground_z(df.x.values, df.y.values)
df = df[mok].reset_index(drop=True); mz = mz[mok]

# one receiver list: grid first, then measured points
all_x = np.concatenate([grid_x[gok], df.x.values])
all_y = np.concatenate([grid_y[gok], df.y.values])
all_z = np.concatenate([gz[gok], mz]) + 1.5
n_grid = int(gok.sum())
print(f"total receivers: {len(all_x):,}", flush=True)

scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="tr38901", polarization="V")
site = g["sites"]["Agronomy Farm"]
for cid, az in SECTORS.items():
    scene.add(Transmitter(name=cid, position=[site["x"], site["y"], site["ground"] + H],
                          orientation=[math.radians(90.0 - az), 0.0, 0.0]))

# PathSolver degrades badly past a couple of thousand receivers: a single 15.7k-receiver
# solve ran 30 min without finishing, while 800 took 15 s. Chunking keeps each solve in the
# regime where cost is linear in receiver count. 800 suits a CPU/LLVM backend; on a CUDA
# GPU raise it until VRAM complains -- RT_CHUNK=8000 is a reasonable starting point.
CHUNK = int(os.environ.get("RT_CHUNK", 800))
solver = PathSolver()
pg_parts = []
import time
t0 = time.time()
for lo in range(0, len(all_x), CHUNK):
    hi = min(lo + CHUNK, len(all_x))
    for nm in [n for n in scene.receivers]:
        scene.remove(nm)
    for i in range(lo, hi):
        scene.add(Receiver(name=f"rx{i}", position=[float(all_x[i]), float(all_y[i]), float(all_z[i])]))
    paths = solver(scene, max_depth=3, los=True, specular_reflection=True,
                   diffuse_reflection=False, refraction=False, synthetic_array=True)
    a, _ = paths.cir(normalize_delays=False, out_type="numpy")
    part = np.sum(np.abs(a) ** 2, axis=(1, 3, 4, 5))
    pg_parts.append(part)
    np.save(f"{OUT}.part{lo//CHUNK:03d}.npy", part)
    print(f"  {hi:6d}/{len(all_x)}  {time.time()-t0:6.1f}s  "
          f"paths={a.shape[4]} mem_parts={sum(x.nbytes for x in pg_parts)//1024}kB", flush=True)
    del a, paths
pg = np.concatenate(pg_parts, axis=0)
tx_order = list(scene.transmitters)
print("path gain array", pg.shape, flush=True)

np.savez_compressed(
    OUT,
    grid_x=grid_x[gok], grid_y=grid_y[gok], grid_z=gz[gok], grid_pg=pg[:n_grid],
    meas_x=df.x.values, meas_y=df.y.values, meas_rsrp=df.rsrp.values,
    meas_cell=df.cellid.values, meas_pg=pg[n_grid:],
    meas_lat=df.lat.values, meas_lon=df.lon.values,
    tx_order=np.array(tx_order), h_ant=H, xml=XML, grid_m=GRID, block_m=BLOCK,
    gx=gx, gy=gy, gok=gok,
    site_x=site["x"], site_y=site["y"], site_ground=site["ground"])
print("wrote", OUT, flush=True)
