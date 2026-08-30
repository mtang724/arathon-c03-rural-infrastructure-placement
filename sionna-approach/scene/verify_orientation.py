"""Independent checks that the 3D scene is not flipped, mirrored or rotated.

A sign error or axis swap can leave RMSE looking plausible while making every
directional conclusion wrong, so each check below is designed to FAIL loudly on a
flip rather than degrade quietly.
"""
import json, math, re, struct
import numpy as np, pandas as pd
from pathlib import Path
from PIL import Image

BASE = Path(__file__).resolve().parent
g = json.load(open(BASE / "georef.json"))
LAT0, LON0, R, K = g["origin_lat"], g["origin_lon"], g["radius"], g["k"]
lat0r = math.radians(LAT0)
site = g["sites"]["Agronomy Farm"]
ok = lambda c: "PASS" if c else "*** FAIL ***"

def fromGeo(lat, lon):
    lat = np.radians(lat); lon = np.radians(lon - LON0)
    B = np.sin(lon) * np.cos(lat)
    return (0.5*K*R*np.log((1+B)/(1-B)), K*R*(np.arctan(np.tan(lat)/np.cos(lon)) - lat0r))

print("=" * 72)
print("1. COORDINATE HANDEDNESS  (east -> +x, north -> +y)")
x0, y0 = fromGeo(42.00, -93.80); xE, yE = fromGeo(42.00, -93.70); xN, yN = fromGeo(42.10, -93.80)
print(f"   move 0.10 deg EAST : dx {xE-x0:+9.1f} m, dy {yE-y0:+7.1f} m   {ok(xE>x0 and abs(yE-y0)<abs(xE-x0)/5)}")
print(f"   move 0.10 deg NORTH: dx {xN-x0:+9.1f} m, dy {yN-y0:+7.1f} m   {ok(yN>y0 and abs(xN-x0)<abs(yN-y0)/5)}")

print("\n2. BASE-STATION RELATIVE GEOMETRY  (does the scene preserve real-world layout?)")
sites = {n: (s["lat"], s["lon"], s["x"], s["y"]) for n, s in g["sites"].items()}
import itertools
worst = 0.0
for a, b in itertools.combinations(sites, 2):
    la1, lo1, x1, y1 = sites[a]; la2, lo2, x2, y2 = sites[b]
    # true great-circle distance vs scene euclidean distance
    p1, p2 = math.radians(la1), math.radians(la2)
    dl = math.radians(lo2 - lo1); dp = p2 - p1
    h = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    d_true = 2*6371000*math.asin(math.sqrt(h))
    d_scene = math.hypot(x2-x1, y2-y1)
    err = 100*abs(d_scene-d_true)/d_true; worst = max(worst, err)
    print(f"   {a[:13]:13} - {b[:13]:13}  true {d_true/1000:6.2f} km   scene {d_scene/1000:6.2f} km   {err:.2f}%")
print(f"   worst distortion {worst:.2f}%   {ok(worst < 0.5)}")

print("\n3. TERRAIN ELEVATION  (scene mesh vs an independent read of the DEM)")
Image.MAX_IMAGE_PIXELS = None
dem = np.array(Image.open(BASE/"dem_3dep.tif"), dtype=float)
W_, S_, E_, N_ = -93.8950, 41.9200, -93.6250, 42.0500
h0, w0 = dem.shape
import mitsuba as mi
from sionna.rt import load_scene
sc = load_scene(str(BASE/"mitsuba/ames.xml"), merge_shapes=True)
rng = np.random.default_rng(0)
la = rng.uniform(S_+0.01, N_-0.01, 400); lo = rng.uniform(W_+0.01, E_-0.01, 400)
xs, ys = fromGeo(la, lo)
o = mi.Point3f(xs.astype(np.float32), ys.astype(np.float32), np.full(400, 900.0, np.float32))
si = sc.mi_scene.ray_intersect(mi.Ray3f(o=o, d=mi.Vector3f(0,0,-1)))
z_scene = np.array(si.p.z) + 262.0
j = ((N_ - la)/(N_-S_)*h0).astype(int).clip(0, h0-1)
i = ((lo - W_)/(E_-W_)*w0).astype(int).clip(0, w0-1)
z_dem = dem[j, i]
d = z_scene - z_dem
print(f"   n=400 random points, scene_z+262 minus 3DEP elevation")
print(f"   mean {d.mean():+.2f} m, std {d.std():.2f} m, |median| {abs(np.median(d)):.2f} m")
print(f"   correlation {np.corrcoef(z_scene, z_dem)[0,1]:.4f}   {ok(np.corrcoef(z_scene,z_dem)[0,1] > 0.97 and abs(d.mean()) < 5)}")
# a north-south flip would invert this correlation, so test it explicitly
z_dem_flipud = np.flipud(dem)[j, i]; z_dem_fliplr = np.fliplr(dem)[j, i]
print(f"   correlation if terrain were N-S flipped: {np.corrcoef(z_scene, z_dem_flipud)[0,1]:+.4f}  (must be much lower)")
print(f"   correlation if terrain were E-W flipped: {np.corrcoef(z_scene, z_dem_fliplr)[0,1]:+.4f}  (must be much lower)")

print("\n4. SECTOR AZIMUTHS  (measured bearings, data only -- no model involved)")
DATA = BASE.parent.parent/"extracted/COTS_Dataset"
df = pd.read_csv(DATA/"COTS.csv", dtype={"cellid": str})
df["rsrp"] = pd.to_numeric(df["rsrp"], errors="coerce")
agr = df[df.cellid.isin(["00019C00B","00019C015","00019C01F"]) & df.rsrp.notna()].copy()
agr["x"], agr["y"] = fromGeo(agr.lat.values, agr.lon.values)
# compass bearing from tower: 0 = north, increasing clockwise
agr["brg"] = (np.degrees(np.arctan2(agr.x - site["x"], agr.y - site["y"])) + 360) % 360
NOM = {"00019C00B": 0.0, "00019C015": 115.0, "00019C01F": 240.0}
allpass = True
for cid, nom in NOM.items():
    b = agr.brg[agr.cellid == cid].values
    v = np.exp(1j*np.radians(b)); mean_b = (np.degrees(np.angle(v.mean())) + 360) % 360
    off = (mean_b - nom + 180) % 360 - 180
    good = abs(off) < 45; allpass &= good
    print(f"   {cid}  n={len(b):5d}  circular-mean bearing {mean_b:6.1f} deg  "
          f"(assumed {nom:5.1f})  offset {off:+6.1f}  {ok(good)}")
print(f"   {ok(allpass)}  -- a mirrored scene would show bearings at -offset, i.e. 360-mean")

print("\n5. PREDICTED BEST SERVER vs MEASURED SERVING CELL  (the end-to-end directional test)")
d = np.load(BASE/"pred_30m_h30.npz", allow_pickle=True)
order = [str(t) for t in d["tx_order"]]
pg = d["meas_pg"]; cells = [str(c) for c in d["meas_cell"]]
has = pg.max(axis=1) > 0
pred_idx = pg.argmax(axis=1)
true_idx = np.array([order.index(c) for c in cells])
agree = (pred_idx[has] == true_idx[has])
print(f"   n={has.sum():,} points with a modelled path, 3 candidate sectors (chance = 33%)")
print(f"   model picks the same sector the network did: {100*agree.mean():.1f}%   {ok(agree.mean() > 0.6)}")
for k, cid in enumerate(order):
    m = has & (true_idx == k)
    if m.sum():
        print(f"     served by {cid}: n={int(m.sum()):5d}, model agrees {100*(pred_idx[m]==k).mean():5.1f}%")
print("\n   A mirrored or rotated scene would drive this toward chance. It is the single")
print("   strongest check here because it couples geometry, projection and antenna azimuth.")
