"""Ray-trace the Agronomy Farm site against the measured drive test.

Antenna height is the largest free parameter in the handoff, so sweep it and score
each candidate against measured RSRP. Receivers sit on the real terrain at each
measurement location, so this is a like-for-like comparison, not a planar radio map.
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

FC = 3.4608e9                      # NR-ARFCN 630720
SECTORS = {"00019C00B": 0.0, "00019C015": 115.0, "00019C01F": 240.0}   # compass deg
N_RX = int(sys.argv[1]) if len(sys.argv) > 1 else 200
XML  = sys.argv[3] if len(sys.argv) > 3 else "mitsuba/ames.xml"
DIFF = (sys.argv[4].lower() == "diff") if len(sys.argv) > 4 else False
HEIGHTS = [float(h) for h in (sys.argv[2].split(",") if len(sys.argv) > 2 else ["30"])]

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
print(f"{len(df)} Agronomy-served rows with RSRP", flush=True)

scene = load_scene(f"{BASE}/{XML}", merge_shapes=True)
print(f"scene: {XML}  diffraction={DIFF}", flush=True)
scene.frequency = FC

def ground_z(x, y):
    """Drop a ray from above to find the terrain surface."""
    o = mi.Point3f(np.asarray(x, np.float32), np.asarray(y, np.float32),
                   np.full(len(x), 500.0, np.float32))
    si = scene.mi_scene.ray_intersect(mi.Ray3f(o=o, d=mi.Vector3f(0, 0, -1)))
    return np.array(si.p.z), np.array(si.is_valid())

# one stratified subsample reused for every height so the scores are comparable
df = df.sample(n=min(N_RX, len(df)), random_state=0).reset_index(drop=True)
gz, ok = ground_z(df.x.values, df.y.values)
df, gz = df[ok].reset_index(drop=True), gz[ok]
print(f"{len(df)} receivers placed on terrain", flush=True)

site = g["sites"]["Agronomy Farm"]
scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="tr38901", polarization="V")

for i, r in df.iterrows():
    scene.add(Receiver(name=f"rx{i}", position=[float(r.x), float(r.y), float(gz[i]) + 1.5]))

solver = PathSolver()
print(f"{'h_ant':>6} {'n_link':>7} {'corr':>7} {'rmse_dB':>8} {'offset_dB':>10}")
for h in HEIGHTS:
    for name in list(scene.transmitters):
        scene.remove(name)
    for cid, az in SECTORS.items():
        scene.add(Transmitter(name=cid, position=[site["x"], site["y"], site["ground"] + h],
                              orientation=[math.radians(90.0 - az), 0.0, 0.0]))
    paths = solver(scene, max_depth=3, los=True, specular_reflection=True,
                   diffuse_reflection=False, refraction=False, synthetic_array=True,
                   diffraction=DIFF, edge_diffraction=DIFF)
    a, _ = paths.cir(normalize_delays=False, out_type="numpy")
    # |a|^2 summed over paths -> linear path gain per (rx, tx); a is [rx,rxant,tx,txant,path,t]
    pg = np.sum(np.abs(a) ** 2, axis=(1, 3, 4, 5))          # [n_rx, n_tx]
    tx_order = list(scene.transmitters)
    served = np.array([tx_order.index(c) for c in df.cellid])
    pg_serv = pg[np.arange(len(df)), served]
    m = pg_serv > 0
    pred = 10 * np.log10(pg_serv[m])
    meas = df.rsrp.values[m]
    off = float(np.mean(meas - pred))
    print(f"{h:6.0f} {m.sum():7d} {np.corrcoef(pred, meas)[0,1]:7.3f} "
          f"{np.sqrt(np.mean((pred + off - meas) ** 2)):8.2f} {off:10.1f}", flush=True)
