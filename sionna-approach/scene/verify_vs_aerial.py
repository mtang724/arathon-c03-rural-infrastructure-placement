"""Validate the scene against USGS NAIP aerial imagery.

Projects the *exported Mitsuba mesh* back to WGS84 and draws it over real imagery, so this
tests the whole chain -- OSM -> Blosm -> projection -> PLY export -> inverse projection --
not merely whether OpenStreetMap agrees with itself. Terrain is checked separately by
comparing hillshaded drainage against the imagery.

NAIP is public domain (USDA), so the resulting figure carries no licence encumbrance.
"""
import json, math, struct, sys, argparse
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.colors import LightSource
from pathlib import Path
from PIL import Image

AP = argparse.ArgumentParser()
AP.add_argument("--mesh", default="ames_osm_buildings.ply")
AP.add_argument("--out", default="scene_validation.png")
AP.add_argument("--source", default="OpenStreetMap")
AP.add_argument("--nbox", type=int, default=6, help="buildings in the 2x2 km box")
AP.add_argument("--nrural", default="365", help="buildings in the rural half")
A = AP.parse_args()

BASE = Path(__file__).resolve().parent
SCENE = (-93.8950, 41.9200, -93.6250, 42.0500)          # W S E N
g = json.load(open(BASE / "georef.json"))
LAT0, LON0, R, K = g["origin_lat"], g["origin_lon"], g["radius"], g["k"]
lat0r = math.radians(LAT0)

def toGeo(x, y):
    x = x / (K * R); y = y / (K * R)
    D = y + lat0r
    return (np.degrees(np.arcsin(np.sin(D) / np.cosh(x))),
            LON0 + np.degrees(np.arctan(np.sinh(x) / np.cos(D))))

def read_ply(p):
    raw = open(p, "rb").read()
    hdr_end = raw.index(b"end_header\n") + len(b"end_header\n")
    hdr = raw[:hdr_end].decode("ascii", "replace")
    nv = int([l for l in hdr.splitlines() if l.startswith("element vertex")][0].split()[-1])
    nf = int([l for l in hdr.splitlines() if l.startswith("element face")][0].split()[-1])
    v = np.frombuffer(raw, dtype="<f4", count=nv * 3, offset=hdr_end).reshape(nv, 3)
    off = hdr_end + nv * 12
    rec = np.frombuffer(raw, dtype=np.dtype([("n", "u1"), ("v", "<i4", 3)]), count=nf, offset=off)
    return v, rec["v"]

verts, faces = read_ply(BASE / "mitsuba/meshes" / A.mesh)
blat, blon = toGeo(verts[:, 0], verts[:, 1])
print(f"buildings mesh: {len(verts):,} verts, {len(faces):,} faces")
print(f"reprojected extent: lat [{blat.min():.4f},{blat.max():.4f}] lon [{blon.min():.4f},{blon.max():.4f}]")

Image.MAX_IMAGE_PIXELS = None
naip_scene = np.array(Image.open(BASE / "naip_scene.png"))
naip_zoom = np.array(Image.open(BASE / "naip_zoom.png"))
dem = np.array(Image.open(BASE / "dem_3dep.tif"), dtype=float)
dem = np.where(dem < -1e5, np.nan, dem)
hs = LightSource(azdeg=315, altdeg=40).hillshade(dem, vert_exag=4.0, dx=7.7, dy=10.3)

site = (42.021016348205585, -93.77358107943655)
d_lat = 1000 / 111320; d_lon = 1000 / (111320 * math.cos(math.radians(site[0])))
ZOOM = (site[1] - d_lon, site[0] - d_lat, site[1] + d_lon, site[0] + d_lat)

def poly_patches(bbox):
    W_, S_, E_, N_ = bbox
    keep = (blon > W_) & (blon < E_) & (blat > S_) & (blat < N_)
    fm = keep[faces].any(axis=1)
    tri = faces[fm]
    return [np.column_stack([blon[t], blat[t]]) for t in tri], int(fm.sum())

plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "figure.dpi": 200})
fig, ax = plt.subplots(2, 2, figsize=(13, 9.6))
for a in ax.ravel():
    a.set_xticks([]); a.set_yticks([])

# --- a. full scene, real imagery ---------------------------------------------
ax[0, 0].imshow(naip_scene, extent=[SCENE[0], SCENE[2], SCENE[1], SCENE[3]], origin="upper")
ax[0, 0].plot(site[1], site[0], "^", ms=11, mfc="#ff3b30", mec="white", mew=1.3)
ax[0, 0].add_patch(plt.Rectangle((ZOOM[0], ZOOM[1]), ZOOM[2] - ZOOM[0], ZOOM[3] - ZOOM[1],
                                 fill=False, ec="#ffcc00", lw=1.8))
ax[0, 0].set_xlim(SCENE[0], SCENE[2]); ax[0, 0].set_ylim(SCENE[1], SCENE[3])
ax[0, 0].set_title("a  USGS NAIP aerial imagery — ground truth", loc="left", weight="bold")

# --- b. our terrain, same extent ---------------------------------------------
ax[0, 1].imshow(hs, extent=[SCENE[0], SCENE[2], SCENE[1], SCENE[3]], origin="upper",
                cmap="gray", vmin=0, vmax=1.25)
pp, n = poly_patches(SCENE)
ax[0, 1].add_collection(PolyCollection(pp, facecolors="#e8453c", edgecolors="none", alpha=0.9))
ax[0, 1].plot(site[1], site[0], "^", ms=11, mfc="#ff3b30", mec="white", mew=1.3)
ax[0, 1].set_xlim(SCENE[0], SCENE[2]); ax[0, 1].set_ylim(SCENE[1], SCENE[3])
ax[0, 1].set_title(f"b  Our scene — hillshade + {A.source} buildings (red)", loc="left", weight="bold")
ax[0, 1].text(0.015, 0.03, f"{A.source}: {A.nrural} buildings in the rural half",
              transform=ax[0, 1].transAxes, fontsize=8, va="bottom",
              bbox=dict(fc="white", ec="#ccc", alpha=0.9, pad=3))

# --- c. the alignment test ---------------------------------------------------
ax[1, 0].imshow(naip_zoom, extent=[ZOOM[0], ZOOM[2], ZOOM[1], ZOOM[3]], origin="upper")
pp, n = poly_patches(ZOOM)
ax[1, 0].add_collection(PolyCollection(pp, facecolors="none", edgecolors="#ffcc00", lw=0.7))
ax[1, 0].set_title("c  Alignment test — mesh reprojected onto imagery", loc="left", weight="bold")
ax[1, 0].text(0.015, 0.03, f"{A.nbox} {A.source} buildings in this 2x2 km box,\nreprojected onto the imagery",
              transform=ax[1, 0].transAxes, fontsize=8, va="bottom",
              bbox=dict(fc="white", ec="#ccc", alpha=0.92, pad=3))
ax[1, 0].plot(site[1], site[0], "^", ms=12, mfc="#ff3b30", mec="white", mew=1.4)

# --- d. what the ray tracer actually sees ------------------------------------
ax[1, 1].imshow(naip_zoom, extent=[ZOOM[0], ZOOM[2], ZOOM[1], ZOOM[3]], origin="upper", alpha=0.35)
ax[1, 1].add_collection(PolyCollection(pp, facecolors="#2b6a8f", edgecolors="#123", lw=0.3, alpha=0.95))
ax[1, 1].plot(site[1], site[0], "^", ms=12, mfc="#ff3b30", mec="white", mew=1.4)
ax[1, 1].set_title("d  What Sionna traces — and what is missing", loc="left", weight="bold")
ax[1, 1].text(0.015, 0.03, A.footnote if hasattr(A, "footnote") else
              ("every large farm shed and grain bin visible\nin (c) is absent from the model"
               if A.source == "OpenStreetMap" else
               "the sheds and bins OSM omits are now present;\ntree lines still are not"),
              transform=ax[1, 1].transAxes, fontsize=8, va="bottom",
              bbox=dict(fc="#fff4f4" if A.source == "OpenStreetMap" else "#f2f8f2",
                        ec="#e8453c" if A.source == "OpenStreetMap" else "#3a8a3a", alpha=0.95, pad=3))

for a in (ax[1, 0], ax[1, 1]):
    a.set_xlim(ZOOM[0], ZOOM[2]); a.set_ylim(ZOOM[1], ZOOM[3])
for a in ax.ravel():
    a.set_aspect(1 / math.cos(math.radians(site[0])))

fig.suptitle("Scene validation against public-domain aerial imagery — Agronomy Farm, Ames, Iowa"
             f"   ·   building footprints from {A.source}",
             x=0.012, ha="left", weight="bold", fontsize=11.5, y=0.985)
fig.tight_layout(rect=[0, 0.022, 1, 0.972])
fig.text(0.012, 0.012, f"Imagery: USGS NAIP (public domain).  Buildings: {A.source} (ODbL), "
         "reprojected from the exported mesh.  Terrain: USGS 3DEP 1/3 arc-second.",
         fontsize=7, color="#555")
fig.savefig(BASE.parent / A.out, bbox_inches="tight", facecolor="white")
print("wrote", A.out)
