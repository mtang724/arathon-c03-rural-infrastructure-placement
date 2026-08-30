"""Do model residuals get worse near woodland?

Vegetation is excluded from the scene, and is the leading suspect for the residual. If
that is right, points whose transmitter path crosses wooded ground should be
under-predicted (measured weaker than modelled) relative to points over open field. If
there is no such relationship, vegetation is off the hook and the hardest item on the
improvement list can be dropped.

Tests the path, not the receiver: what matters is woodland *between* tower and UE.
"""
import json, math, re
from pathlib import Path
import numpy as np, pandas as pd

BASE = str(Path(__file__).resolve().parent)
g = json.load(open(f"{BASE}/georef.json"))
LAT0, LON0, R, K = g["origin_lat"], g["origin_lon"], g["radius"], g["k"]
lat0r = math.radians(LAT0); site = g["sites"]["Agronomy Farm"]

def fromGeo(lat, lon):
    lat = np.radians(lat); lon = np.radians(lon - LON0)
    B = np.sin(lon) * np.cos(lat)
    return (0.5 * K * R * np.log((1 + B) / (1 - B)),
            K * R * (np.arctan(np.tan(lat) / np.cos(lon)) - lat0r))

# ---- pull wooded polygons out of the OSM extract ----------------------------
osm = Path(f"{BASE}/ames.osm").read_text(errors="replace")
nodes = {}
for m in re.finditer(r'<node id="(\d+)"[^>]*lat="([-\d.]+)" lon="([-\d.]+)"', osm):
    nodes[m.group(1)] = (float(m.group(2)), float(m.group(3)))
WOODY = ('v="wood"', 'v="forest"', 'v="tree_row"', 'v="scrub"', 'v="hedge"')
polys = []
for wm in re.finditer(r'<way id="\d+".*?</way>', osm, re.S):
    body = wm.group(0)
    if not any(w in body for w in WOODY):
        continue
    refs = re.findall(r'<nd ref="(\d+)"', body)
    pts = [nodes[r] for r in refs if r in nodes]
    if len(pts) >= 3:
        la = np.array([p[0] for p in pts]); lo = np.array([p[1] for p in pts])
        x, y = fromGeo(la, lo)
        polys.append(np.column_stack([x, y]))
print(f"{len(polys)} woody polygons parsed")

# rasterise woodland onto a 25 m grid: cheap and ample for a path-crossing count
CELL = 25.0
allp = np.vstack(polys)
x0, y0 = allp[:, 0].min(), allp[:, 1].min()
nx = int((allp[:, 0].max() - x0) / CELL) + 2; ny = int((allp[:, 1].max() - y0) / CELL) + 2
mask = np.zeros((ny, nx), bool)
from matplotlib.path import Path as MplPath
for p in polys:
    lo_i = ((p[:, 0].min() - x0) / CELL).astype(int); hi_i = int((p[:, 0].max() - x0) / CELL) + 1
    lo_j = ((p[:, 1].min() - y0) / CELL).astype(int); hi_j = int((p[:, 1].max() - y0) / CELL) + 1
    if hi_i - lo_i > 400 or hi_j - lo_j > 400:
        continue
    gi, gj = np.meshgrid(np.arange(lo_i, hi_i), np.arange(lo_j, hi_j))
    pts = np.column_stack([x0 + (gi.ravel() + .5) * CELL, y0 + (gj.ravel() + .5) * CELL])
    inside = MplPath(p).contains_points(pts)
    if inside.any():
        mask[gj.ravel()[inside], gi.ravel()[inside]] = True
print(f"woodland raster: {mask.sum():,} cells of {mask.size:,} ({100*mask.mean():.1f}%)")

d = np.load(f"{BASE}/pred_30m_h30.npz", allow_pickle=True)
tx_order = list(d["tx_order"])
serv = np.array([tx_order.index(c) for c in d["meas_cell"]])
pg = d["meas_pg"][np.arange(len(serv)), serv]
ok = pg > 0
pred = 10 * np.log10(pg[ok]); meas = d["meas_rsrp"][ok]
mx, my = d["meas_x"][ok], d["meas_y"][ok]
offset = np.mean(meas - pred)
resid = (pred + offset) - meas            # positive = model over-predicts

# woodland length along each tower->UE path
NS = 120
t = np.linspace(0, 1, NS)[None, :]
px = site["x"] + (mx[:, None] - site["x"]) * t
py = site["y"] + (my[:, None] - site["y"]) * t
ii = ((px - x0) / CELL).astype(int); jj = ((py - y0) / CELL).astype(int)
valid = (ii >= 0) & (ii < nx) & (jj >= 0) & (jj < ny)
hit = np.zeros_like(ii, bool)
hit[valid] = mask[jj[valid], ii[valid]]
seglen = np.hypot(mx - site["x"], my - site["y"]) / NS
wood_m = hit.sum(axis=1) * seglen

print(f"\npaths crossing any woodland: {(wood_m > 0).sum():,} of {len(wood_m):,} "
      f"({100*(wood_m > 0).mean():.0f}%)")
print(f"median wooded path length where >0: {np.median(wood_m[wood_m > 0]):.0f} m, "
      f"max {wood_m.max():.0f} m\n")
bins = [0, 1, 50, 150, 300, 1e9]
lab  = ["none", "0-50 m", "50-150 m", "150-300 m", ">300 m"]
print(f"{'wooded path':>12} {'n':>6} {'mean resid':>11} {'median':>8}")
for i in range(len(bins) - 1):
    m = (wood_m >= bins[i]) & (wood_m < bins[i + 1])
    if m.sum() > 5:
        print(f"{lab[i]:>12} {m.sum():6d} {resid[m].mean():+10.2f} dB {np.median(resid[m]):+7.2f}")
w = wood_m > 0
print(f"\ncorr(wooded metres, residual) = {np.corrcoef(wood_m, resid)[0,1]:+.3f}")
print(f"mean residual  open {resid[~w].mean():+.2f} dB   wooded {resid[w].mean():+.2f} dB   "
      f"difference {resid[w].mean()-resid[~w].mean():+.2f} dB")
# distance is the obvious confounder: wooded paths are also longer
dist = np.hypot(mx - site["x"], my - site["y"])
print(f"\nconfounder check -- mean path length: open {dist[~w].mean():.0f} m, "
      f"wooded {dist[w].mean():.0f} m")
for lo, hi in [(0, 3000), (3000, 6000), (6000, 12000)]:
    b = (dist >= lo) & (dist < hi)
    if (b & w).sum() > 5 and (b & ~w).sum() > 5:
        print(f"  {lo//1000}-{hi//1000} km: open {resid[b & ~w].mean():+6.2f} dB "
              f"(n={int((b & ~w).sum()):4d})   wooded {resid[b & w].mean():+6.2f} dB "
              f"(n={int((b & w).sum()):4d})   diff {resid[b & w].mean()-resid[b & ~w].mean():+6.2f}")
