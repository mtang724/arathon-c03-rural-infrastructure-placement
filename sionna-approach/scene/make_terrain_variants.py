"""Build matched flat / earth-curvature-corrected terrain meshes from the 3DEP DEM.

Sionna RT is flat-Euclidean: a projected terrain plane has no horizon, so the model
over-predicts at long range. The standard RF-profile correction lowers each point by
d^2/(2 k R) with d measured from the transmitter, making flat-earth geometry equivalent
to curved-earth propagation from that site. k = 4/3 is the usual refractive value.

Because the correction is referenced to one transmitter, the curved mesh is valid for
Agronomy Farm analyses only. Rebuild it per site if another transmitter is studied.

usage: make_terrain_variants.py [stride] [k]      k = 0 -> flat (no correction)
"""
import json, math, sys
import numpy as np
from pathlib import Path
from PIL import Image

BASE = str(Path(__file__).resolve().parent)
W, S, E, N = -93.8950, 41.9200, -93.6250, 42.0500
HEIGHT_OFFSET = 262.0
R_EARTH = 6371000.0
stride = int(sys.argv[1]) if len(sys.argv) > 1 else 3
kfac   = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0

g = json.load(open(f"{BASE}/georef.json"))
LAT0, LON0, R, K = g["origin_lat"], g["origin_lon"], g["radius"], g["k"]
lat0r = math.radians(LAT0)
site = g["sites"]["Agronomy Farm"]

def fromGeo(lat, lon):
    lat = np.radians(lat); lon = np.radians(lon - LON0)
    B = np.sin(lon) * np.cos(lat)
    return (0.5 * K * R * np.log((1 + B) / (1 - B)),
            K * R * (np.arctan(np.tan(lat) / np.cos(lon)) - lat0r))

Image.MAX_IMAGE_PIXELS = None
full = np.array(Image.open(f"{BASE}/dem_3dep.tif"), dtype=np.float64)
full = np.where(full < -1e5, np.nan, full)
if np.isnan(full).any():
    full = np.where(np.isnan(full), np.nanmedian(full), full)
h0, w0 = full.shape
z = full[::stride, ::stride]
lats = (N - (np.arange(h0) + 0.5) * (N - S) / h0)[::stride]
lons = (W + (np.arange(w0) + 0.5) * (E - W) / w0)[::stride]
LON, LAT = np.meshgrid(lons, lats)
X, Y = fromGeo(LAT, LON)
Z = z - HEIGHT_OFFSET

drop_max = 0.0
if kfac > 0:
    d2 = (X - site["x"]) ** 2 + (Y - site["y"]) ** 2
    drop = d2 / (2.0 * kfac * R_EARTH)
    Z = Z - drop
    drop_max = float(drop.max())
    print(f"curvature k={kfac}: max drop {drop_max:.1f} m at {math.sqrt(d2.max())/1000:.1f} km")

nrow, ncol = Z.shape
name = f"Terrain3DEP_s{stride}" + (f"_k{kfac:g}".replace(".", "p") if kfac > 0 else "_flat") + ".ply"
print(f"{name}: {nrow}x{ncol} = {nrow*ncol:,} verts, spacing "
      f"{abs(X[0,1]-X[0,0]):.1f} x {abs(Y[1,0]-Y[0,0]):.1f} m")

verts = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()]).astype(np.float32)
idx = np.arange(nrow * ncol).reshape(nrow, ncol)
a, b = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel()
c, d = idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
faces = np.empty((2 * len(a), 3), np.int32)
faces[0::2] = np.column_stack([a, b, c]); faces[1::2] = np.column_stack([a, c, d])

out = f"{BASE}/mitsuba/meshes/{name}"
with open(out, "wb") as f:
    f.write(b"ply\nformat binary_little_endian 1.0\n")
    f.write(f"element vertex {len(verts)}\n".encode())
    f.write(b"property float x\nproperty float y\nproperty float z\n")
    f.write(f"element face {len(faces)}\n".encode())
    f.write(b"property list uchar int vertex_indices\nend_header\n")
    f.write(verts.tobytes())
    rec = np.empty(len(faces), dtype=[("n", "u1"), ("v", "i4", 3)])
    rec["n"] = 3; rec["v"] = faces
    f.write(rec.tobytes())
print("wrote", out)
