"""Per-footprint alignment against NAIP imagery, robust to roof colour.

A brightness detector fails on dark roofs, so this scores each footprint by the ABSOLUTE
contrast between its interior and a surrounding ring: a building differs from the field
around it whether its roof is bright metal or dark shingle. Each footprint is shifted
independently and the offset maximising that contrast is reported, giving a distribution of
per-building offsets rather than one number dominated by the largest polygon.
"""
import json, math, re
import numpy as np
from pathlib import Path
from PIL import Image
from matplotlib.path import Path as MplPath

BASE = Path(__file__).resolve().parent
site = (42.021016348205585, -93.77358107943655)
dlat = 1000/111320; dlon = 1000/(111320*math.cos(math.radians(site[0])))
BOX = (site[1]-dlon, site[0]-dlat, site[1]+dlon, site[0]+dlat)

Image.MAX_IMAGE_PIXELS = None
img = np.array(Image.open(BASE/"naip_zoom.png")).astype(float)
H, W = img.shape[:2]
grey = img.mean(axis=2)
SH = 20                                     # search +/-20 m

def footprint_offset(ring):
    lo = np.array([p[0] for p in ring]); la = np.array([p[1] for p in ring])
    px = (lo - BOX[0])/(BOX[2]-BOX[0])*W
    py = (BOX[3] - la)/(BOX[3]-BOX[1])*H
    i0, i1 = int(px.min())-SH-6, int(px.max())+SH+7
    j0, j1 = int(py.min())-SH-6, int(py.max())+SH+7
    if i0 < 0 or j0 < 0 or i1 >= W or j1 >= H: return None
    gi, gj = np.meshgrid(np.arange(i0, i1), np.arange(j0, j1))
    pts = np.column_stack([gi.ravel()+.5, gj.ravel()+.5])
    inside = MplPath(np.column_stack([px, py])).contains_points(pts).reshape(gj.shape)
    if inside.sum() < 25: return None
    sub = grey[j0:j1, i0:i1]
    best = None
    for dy in range(-SH, SH+1):
        for dx in range(-SH, SH+1):
            m = np.roll(np.roll(inside, dy, axis=0), dx, axis=1)
            # ring = dilate(m) minus m, approximated by shifting in 4 directions
            ring_m = (np.roll(m,3,0)|np.roll(m,-3,0)|np.roll(m,3,1)|np.roll(m,-3,1)) & ~m
            if m.sum() < 20 or ring_m.sum() < 20: continue
            c = abs(sub[m].mean() - sub[ring_m].mean())
            if best is None or c > best[0]: best = (c, dx, dy)
    return best

def report(label, rings):
    offs = []
    for r in rings:
        lo = np.array([p[0] for p in r]); la = np.array([p[1] for p in r])
        if not (BOX[0] < lo.mean() < BOX[2] and BOX[1] < la.mean() < BOX[3]): continue
        b = footprint_offset(r)
        if b: offs.append((b[1], -b[2], b[0]))
    if not offs:
        print(f"\n{label}: nothing testable"); return
    o = np.array(offs)
    d = np.hypot(o[:,0], o[:,1])
    print(f"\n{label}: {len(o)} footprints tested")
    print(f"  median offset  E {np.median(o[:,0]):+5.1f} m   N {np.median(o[:,1]):+5.1f} m")
    print(f"  offset magnitude: median {np.median(d):4.1f} m, "
          f"p75 {np.percentile(d,75):4.1f} m, max {d.max():4.1f} m")
    print(f"  within 5 m: {100*(d<=5).mean():4.0f}%     within 10 m: {100*(d<=10).mean():4.0f}%")
    print(f"  mean interior-vs-ring contrast at best fit: {o[:,2].mean():.1f} grey levels")

ms = json.load(open(BASE/"ms_buildings.json"))
osm_rings = []
osm = (BASE/"ames.osm").read_text(errors="replace")
nodes = {m.group(1): (float(m.group(2)), float(m.group(3)))
         for m in re.finditer(r'<node id="(\d+)"[^>]*lat="([-\d.]+)" lon="([-\d.]+)"', osm)}
for wm in re.finditer(r'<way id="\d+".*?</way>', osm, re.S):
    body = wm.group(0)
    if 'k="building"' not in body: continue
    pts = [nodes[r] for r in re.findall(r'<nd ref="(\d+)"', body) if r in nodes]
    if len(pts) >= 3: osm_rings.append([(p[1], p[0]) for p in pts])

report("Microsoft ML", ms)
report("OpenStreetMap", osm_rings)
print("\nNote: 1 px = 1 m. A search of +/-20 m means offsets are capped at 28 m diagonal.")
