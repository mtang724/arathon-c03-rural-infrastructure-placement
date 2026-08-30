"""Extrude Microsoft building footprints into a mesh in the scene frame.

The footprints carry no height, so height is an explicit parameter rather than a hidden
assumption. 6 m is a reasonable rural default (single-storey houses, machine sheds);
grain bins and silos are taller, which is why the height is worth sweeping.

usage: build_ms_buildings.py [height_m]
"""
import json, math, sys
import numpy as np
from pathlib import Path
from PIL import Image

BASE = Path(__file__).resolve().parent
H = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
W, S, E, N = -93.8950, 41.9200, -93.6250, 42.0500
HEIGHT_OFFSET = 262.0

g = json.load(open(BASE / "georef.json"))
LAT0, LON0, R, K = g["origin_lat"], g["origin_lon"], g["radius"], g["k"]
lat0r = math.radians(LAT0)

def fromGeo(lat, lon):
    lat = np.radians(lat); lon = np.radians(lon - LON0)
    B = np.sin(lon) * np.cos(lat)
    return (0.5*K*R*np.log((1+B)/(1-B)), K*R*(np.arctan(np.tan(lat)/np.cos(lon)) - lat0r))

Image.MAX_IMAGE_PIXELS = None
dem = np.array(Image.open(BASE / "dem_3dep.tif"), dtype=float)
dem = np.where(dem < -1e5, np.nan, dem)
dem = np.where(np.isnan(dem), np.nanmedian(dem), dem)
h0, w0 = dem.shape
def ground(lat, lon):
    j = np.clip(((N - lat) / (N - S) * h0).astype(int), 0, h0 - 1)
    i = np.clip(((lon - W) / (E - W) * w0).astype(int), 0, w0 - 1)
    return dem[j, i] - HEIGHT_OFFSET

rings = json.load(open(BASE / "ms_buildings.json"))
V, F = [], []
for ring in rings:
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) < 3:
        continue
    lo = np.array([p[0] for p in ring]); la = np.array([p[1] for p in ring])
    x, y = fromGeo(la, lo)
    z0 = float(np.median(ground(la, lo)))          # one base level per building
    n = len(x); b = len(V)
    for k in range(n):                              # base ring then top ring
        V.append((x[k], y[k], z0))
    for k in range(n):
        V.append((x[k], y[k], z0 + H))
    for k in range(n):                              # walls
        k2 = (k + 1) % n
        F.append((b + k, b + k2, b + n + k2))
        F.append((b + k, b + n + k2, b + n + k))
    cx, cy = x.mean(), y.mean()                     # roof, fanned from the centroid
    c = len(V); V.append((cx, cy, z0 + H))
    for k in range(n):
        F.append((b + n + k, b + n + (k + 1) % n, c))

V = np.array(V, np.float32); F = np.array(F, np.int32)
print(f"{len(rings):,} footprints -> {len(V):,} verts, {len(F):,} triangles, height {H:g} m")

out = BASE / f"mitsuba/meshes/ms_buildings_h{H:g}.ply"
with open(out, "wb") as f:
    f.write(b"ply\nformat binary_little_endian 1.0\n")
    f.write(f"element vertex {len(V)}\n".encode())
    f.write(b"property float x\nproperty float y\nproperty float z\n")
    f.write(f"element face {len(F)}\n".encode())
    f.write(b"property list uchar int vertex_indices\nend_header\n")
    f.write(V.tobytes())
    rec = np.empty(len(F), dtype=[("n", "u1"), ("v", "i4", 3)]); rec["n"] = 3; rec["v"] = F
    f.write(rec.tobytes())
print("wrote", out.name)
