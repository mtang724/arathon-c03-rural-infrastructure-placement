"""Parameterised RF-model experiment with a complete, append-only parameter log.

Every run writes one JSON record to experiments.jsonl containing *all* inputs and all
outputs, so any number in a future report can be traced back to the exact configuration
that produced it. Nothing is left implicit.

usage:
  python experiment.py --tag baseline
  python experiment.py --ground itu_wet_ground --tag wet-soil
  python experiment.py --downtilt 6 --tag tilt6
  python experiment.py --terrain Terrain3DEP_s3_curved.ply --tag curved
"""
import os, sys, json, math, time, argparse, subprocess, hashlib
from pathlib import Path
import numpy as np, pandas as pd, mitsuba as mi
from sionna.rt import load_scene, Transmitter, Receiver, PlanarArray, PathSolver

BASE = str(Path(__file__).resolve().parent)

def _find_data():
    env = os.environ.get("COTS_DATA")
    if env:
        return env
    here = Path(BASE)
    for c in [here / "data", *(p / "extracted" / "COTS_Dataset" for p in here.parents)]:
        if (c / "COTS.csv").exists():
            return str(c)
    raise SystemExit("COTS.csv not found. Set COTS_DATA=/path/to/COTS_Dataset")
DATA = _find_data()

# ---- fixed physical facts recovered from the dataset (not free parameters) ----
FREQ_HZ  = 3.4608e9          # NR-ARFCN 630720, single-valued across the dataset
SECTORS  = {"00019C00B": 0.0, "00019C015": 115.0, "00019C01F": 240.0}   # compass deg
SITE     = "Agronomy Farm"
RX_AGL_M = 1.5               # UE height above ground

P = argparse.ArgumentParser()
P.add_argument("--tag", required=True, help="short label for this run")
P.add_argument("--note", default="", help="what this run is testing")
# scene
P.add_argument("--terrain", default="Terrain.ply")
P.add_argument("--ground", default="itu_medium_dry_ground")
P.add_argument("--buildings", default="ames_osm_buildings.ply")
P.add_argument("--building-material", default="itu_concrete")
# transmitter
P.add_argument("--h-ant", type=float, default=30.0, help="antenna height above ground, m")
P.add_argument("--downtilt", type=float, default=0.0, help="mechanical downtilt, deg (+ = down)")
P.add_argument("--tx-pattern", default="tr38901")
# solver
P.add_argument("--max-depth", type=int, default=3)
P.add_argument("--diffraction", action="store_true")
P.add_argument("--diffuse", action="store_true")
P.add_argument("--refraction", action="store_true")
# evaluation
P.add_argument("--n-rx", type=int, default=800)
P.add_argument("--seed", type=int, default=0)
P.add_argument("--block-m", type=float, default=2000.0, help="spatial block size for the split")
a = P.parse_args()

t_start = time.time()
g = json.load(open(f"{BASE}/georef.json"))
LAT0, LON0, R, K = g["origin_lat"], g["origin_lon"], g["radius"], g["k"]
lat0r = math.radians(LAT0)

def fromGeo(lat, lon):
    lat = np.radians(lat); lon = np.radians(lon - LON0)
    B = np.sin(lon) * np.cos(lat)
    return (0.5 * K * R * np.log((1 + B) / (1 - B)),
            K * R * (np.arctan(np.tan(lat) / np.cos(lon)) - lat0r))

# ---- scene assembled from parameters, so material and mesh are both variables ----
xml = f"""<scene version="2.1.0">
<bsdf type="twosided" id="mat-{a.building_material}"><bsdf type="principled"><rgb value="0.7 0.7 0.7" name="base_color"/><float name="roughness" value="1.0"/></bsdf></bsdf>
<bsdf type="twosided" id="mat-{a.ground}"><bsdf type="principled"><rgb value="0.45 0.38 0.26" name="base_color"/><float name="roughness" value="1.0"/></bsdf></bsdf>
<shape type="ply" id="mesh-buildings"><string name="filename" value="meshes/{a.buildings}"/><boolean name="face_normals" value="true"/><ref id="mat-{a.building_material}"/></shape>
<shape type="ply" id="mesh-Terrain"><string name="filename" value="meshes/{a.terrain}"/><ref id="mat-{a.ground}"/></shape>
</scene>"""
xml_path = f"{BASE}/mitsuba/_exp_{a.tag}.xml"
Path(xml_path).write_text(xml)

df = pd.read_csv(f"{DATA}/COTS.csv", dtype={"cellid": str})
df["rsrp"] = pd.to_numeric(df["rsrp"], errors="coerce")
df = df[df.cellid.isin(SECTORS) & df.rsrp.notna()].copy()
df["x"], df["y"] = fromGeo(df.lat.values, df.lon.values)

scene = load_scene(xml_path, merge_shapes=True)
scene.frequency = FREQ_HZ

def ground_z(x, y):
    o = mi.Point3f(np.asarray(x, np.float32), np.asarray(y, np.float32),
                   np.full(len(x), 900.0, np.float32))
    si = scene.mi_scene.ray_intersect(mi.Ray3f(o=o, d=mi.Vector3f(0, 0, -1)))
    return np.array(si.p.z), np.array(si.is_valid())

df = df.sample(n=min(a.n_rx, len(df)), random_state=a.seed).reset_index(drop=True)
gz, ok = ground_z(df.x.values, df.y.values)
df, gz = df[ok].reset_index(drop=True), gz[ok]

scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern=a.tx_pattern, polarization="V")
site = g["sites"][SITE]
tx_z = site["ground"] + a.h_ant
for cid, az in SECTORS.items():
    scene.add(Transmitter(name=cid, position=[site["x"], site["y"], tx_z],
                          orientation=[math.radians(90.0 - az),
                                       math.radians(a.downtilt), 0.0]))
for i, r in df.iterrows():
    scene.add(Receiver(name=f"rx{i}", position=[float(r.x), float(r.y), float(gz[i]) + RX_AGL_M]))

paths = PathSolver()(scene, max_depth=a.max_depth, los=True, specular_reflection=True,
                     diffuse_reflection=a.diffuse, refraction=a.refraction,
                     diffraction=a.diffraction, edge_diffraction=a.diffraction,
                     synthetic_array=True)
arr, _ = paths.cir(normalize_delays=False, out_type="numpy")
pg = np.sum(np.abs(arr) ** 2, axis=(1, 3, 4, 5))
tx_order = list(scene.transmitters)
serv = np.array([tx_order.index(c) for c in df.cellid])
pg_s = pg[np.arange(len(df)), serv]
linked = pg_s > 0

# ---- blocked split: the calibration constant never sees the test blocks ----
bx = np.floor(df.x.values / a.block_m).astype(int)
by = np.floor(df.y.values / a.block_m).astype(int)
is_test = ((bx + by) % 2 == 1)
tr, te = linked & ~is_test, linked & is_test
pred_all = np.full(len(df), np.nan)
pred_all[linked] = 10 * np.log10(pg_s[linked])
offset = float(np.mean(df.rsrp.values[tr] - pred_all[tr]))
pred_all += offset
res_te = pred_all[te] - df.rsrp.values[te]
res_all = pred_all[linked] - df.rsrp.values[linked]

rec = dict(
    tag=a.tag, note=a.note,
    utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    git=subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                       text=True, cwd=BASE).stdout.strip() or None,
    runtime_s=round(time.time() - t_start, 1),
    params=dict(
        frequency_hz=FREQ_HZ, site=SITE, sectors_compass_deg=SECTORS,
        terrain_mesh=a.terrain, ground_material=a.ground,
        buildings_mesh=a.buildings, building_material=a.building_material,
        antenna_height_m=a.h_ant, downtilt_deg=a.downtilt, tx_pattern=a.tx_pattern,
        rx_pattern="iso", rx_agl_m=RX_AGL_M, polarization="V",
        max_depth=a.max_depth, los=True, specular_reflection=True,
        diffuse_reflection=a.diffuse, refraction=a.refraction,
        diffraction=a.diffraction, edge_diffraction=a.diffraction,
        synthetic_array=True, n_rx_requested=a.n_rx, seed=a.seed,
        block_m=a.block_m, mitsuba_variant=mi.variant(),
    ),
    results=dict(
        n_rx_placed=int(len(df)), n_linked=int(linked.sum()),
        link_rate=round(float(linked.mean()), 4),
        n_train=int(tr.sum()), n_test=int(te.sum()),
        offset_db=round(offset, 2),
        test_rmse_db=round(float(np.sqrt(np.mean(res_te ** 2))), 3),
        test_corr=round(float(np.corrcoef(pred_all[te], df.rsrp.values[te])[0, 1]), 4),
        test_bias_db=round(float(res_te.mean()), 3),
        test_mae_db=round(float(np.abs(res_te).mean()), 3),
        all_rmse_db=round(float(np.sqrt(np.mean(res_all ** 2))), 3),
    ),
)
with open(f"{BASE}/experiments.jsonl", "a") as f:
    f.write(json.dumps(rec) + "\n")
r = rec["results"]
print(f"{a.tag:22s} link {r['link_rate']:.2f}  RMSE {r['test_rmse_db']:6.2f}  "
      f"r {r['test_corr']:.3f}  bias {r['test_bias_db']:+6.2f}  offset {r['offset_db']:6.1f}  "
      f"({r['n_test']} test)", flush=True)
Path(xml_path).unlink(missing_ok=True)
