"""Clip Microsoft's ML-derived building footprints to the scene extent.

OpenStreetMap records only 6 buildings within 2 km of the serving site, while aerial
imagery shows dozens. Microsoft's footprints are extracted from imagery rather than
contributed by volunteers, so rural coverage does not depend on mapper attention.

Streams the 543 MB GeoJSON line by line -- it is one feature per line -- so nothing large
is held in memory.
"""
import json, zipfile, math
import numpy as np
from pathlib import Path

BASE = Path(__file__).resolve().parent
W, S, E, N = -93.8950, 41.9200, -93.6250, 42.0500
out = []
with zipfile.ZipFile(BASE / "iowa_ms.zip") as z:
    with z.open("Iowa.geojson") as f:
        for line in f:
            line = line.strip().rstrip(b",")
            if not line.startswith(b'{"type"'):
                continue
            # cheap pre-filter before paying for a JSON parse
            if b'-93.6' not in line and b'-93.7' not in line and b'-93.8' not in line:
                continue
            try:
                feat = json.loads(line)
            except Exception:
                continue
            ring = feat["geometry"]["coordinates"][0]
            lo = [p[0] for p in ring]; la = [p[1] for p in ring]
            if not (W < sum(lo)/len(lo) < E and S < sum(la)/len(la) < N):
                continue
            out.append(ring)
print(f"{len(out):,} Microsoft footprints inside the scene extent")

json.dump(out, open(BASE / "ms_buildings.json", "w"))
areas = []
for r in out:
    la = np.array([p[1] for p in r]); lo = np.array([p[0] for p in r])
    x = (lo - lo.mean()) * 111320 * math.cos(math.radians(la.mean()))
    y = (la - la.mean()) * 111320
    areas.append(abs(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)))
a = np.array(areas)
print(f"footprint area m^2: median {np.median(a):.0f}, mean {a.mean():.0f}, max {a.max():.0f}")

site = (42.021016348205585, -93.77358107943655)
dlat = 1000/111320; dlon = 1000/(111320*math.cos(math.radians(site[0])))
cen = np.array([[np.mean([p[1] for p in r]), np.mean([p[0] for p in r])] for r in out])
box = ((cen[:,0] > site[0]-dlat) & (cen[:,0] < site[0]+dlat) &
       (cen[:,1] > site[1]-dlon) & (cen[:,1] < site[1]+dlon))
print(f"\nwithin the 2x2 km box around Agronomy Farm: {int(box.sum())}   (OpenStreetMap has 6)")
west = cen[:,1] < -93.72
print(f"in the rural western half: {int(west.sum()):,}   (OpenStreetMap has 365)")
print(f"total: {len(out):,}   (OpenStreetMap has 10,063)")
