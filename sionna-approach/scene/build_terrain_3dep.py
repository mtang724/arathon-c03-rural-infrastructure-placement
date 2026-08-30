"""Build a terrain mesh from the USGS 3DEP 1/3 arc-second DEM.

Replaces Blosm's 30 m skadi terrain. Uses the identical projection and origin from
georef.json and the same 262 m height offset, so RMSE against the skadi scene is a
like-for-like comparison of terrain resolution alone.

usage: build_terrain_3dep.py [stride]     stride 1 = full 10 m, 2 = ~20 m, ...
"""
import os
from pathlib import Path

# Paths resolve relative to this script so the tree can be moved or cloned anywhere.
BASE = str(Path(__file__).resolve().parent)
import json, math, sys, numpy as np
from PIL import Image

W, S, E, N = -93.8950, 41.9200, -93.6250, 42.0500
HEIGHT_OFFSET = 262.0                      # matches Blosm's Terrain["height_offset"]
stride = int(sys.argv[1]) if len(sys.argv) > 1 else 1

g = json.load(open(f"{BASE}/georef.json"))
LAT0, LON0, R, K = g["origin_lat"], g["origin_lon"], g["radius"], g["k"]
lat0r = math.radians(LAT0)

def fromGeo(lat, lon):
    lat = np.radians(lat); lon = np.radians(lon - LON0)
    B = np.sin(lon) * np.cos(lat)
    return (0.5 * K * R * np.log((1 + B) / (1 - B)),
            K * R * (np.arctan(np.tan(lat) / np.cos(lon)) - lat0r))

Image.MAX_IMAGE_PIXELS = None
z = np.array(Image.open(f"{BASE}/dem_3dep.tif"), dtype=np.float64)
z = np.where(z < -1e5, np.nan, z)
print(f"DEM {z.shape}  elev [{np.nanmin(z):.1f}, {np.nanmax(z):.1f}] m, nodata {np.isnan(z).sum()}")
if np.isnan(z).any():                       # nearest-ish fill so the mesh stays watertight
    z = np.where(np.isnan(z), np.nanmedian(z), z)

z = z[::stride, ::stride]
nrow, ncol = z.shape
# pixel centres of the ORIGINAL grid, then strided
h0, w0 = np.array(Image.open(f"{BASE}/dem_3dep.tif")).shape
lats = (N - (np.arange(h0) + 0.5) * (N - S) / h0)[::stride]
lons = (W + (np.arange(w0) + 0.5) * (E - W) / w0)[::stride]
LON, LAT = np.meshgrid(lons, lats)
X, Y = fromGeo(LAT, LON)                    # non-linear on purpose: a fixed cos(lat) costs ~8 m at the corners
Z = z - HEIGHT_OFFSET

print(f"mesh {nrow} x {ncol} = {nrow*ncol:,} verts, {2*(nrow-1)*(ncol-1):,} tris")
print(f"post spacing ~{abs(X[0,1]-X[0,0]):.1f} m E-W, {abs(Y[1,0]-Y[0,0]):.1f} m N-S")

verts = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()]).astype(np.float32)
idx = np.arange(nrow * ncol).reshape(nrow, ncol)
a, b = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel()
c, d = idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
faces = np.empty((2 * len(a), 3), np.int32)
faces[0::2] = np.column_stack([a, b, c])
faces[1::2] = np.column_stack([a, c, d])

out = f"{BASE}/mitsuba/meshes/Terrain3DEP.ply"
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

xml = f"""<scene version="2.1.0">
	<bsdf type="twosided" id="mat-itu_concrete" name="mat-itu_concrete">
		<bsdf type="principled" name="bsdf"><rgb value="0.7 0.7 0.7" name="base_color"/><float name="roughness" value="1.0"/></bsdf>
	</bsdf>
	<bsdf type="twosided" id="mat-itu_medium_dry_ground" name="mat-itu_medium_dry_ground">
		<bsdf type="principled" name="bsdf"><rgb value="0.45 0.38 0.26" name="base_color"/><float name="roughness" value="1.0"/></bsdf>
	</bsdf>
	<shape type="ply" id="mesh-ames_osm_buildings" name="mesh-ames_osm_buildings">
		<string name="filename" value="meshes/ames_osm_buildings.ply"/>
		<boolean name="face_normals" value="true"/>
		<ref id="mat-itu_concrete" name="bsdf"/>
	</shape>
	<shape type="ply" id="mesh-Terrain" name="mesh-Terrain">
		<string name="filename" value="meshes/Terrain3DEP.ply"/>
		<ref id="mat-itu_medium_dry_ground" name="bsdf"/>
	</shape>
</scene>
"""
open(f"{BASE}/mitsuba/ames_3dep.xml", "w").write(xml)
print("wrote mitsuba/ames_3dep.xml")
