"""Georeference sanity check on ames.blend.

Confirms Blosm's own output round-trips through the projection we intend to reuse,
then places the four base stations and the measurement route on the terrain.
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
import bpy, math, csv, json, sys
from mathutils import Vector
from mathutils.bvhtree import BVHTree

REQ = dict(S=41.9200, W=-93.8950, N=42.0500, E=-93.6250)

bpy.ops.wm.open_mainfile(filepath=f"{BASE}/ames.blend")
sc = bpy.context.scene
LAT0, LON0 = sc["lat"], sc["lon"]
R, K = 6378137.0, 1.0
lat0r = math.radians(LAT0)

def fromGeo(lat, lon):
    lat = math.radians(lat); lon = math.radians(lon - LON0)
    B = math.sin(lon) * math.cos(lat)
    x = 0.5 * K * R * math.log((1 + B) / (1 - B))
    y = K * R * (math.atan(math.tan(lat) / math.cos(lon)) - lat0r)
    return x, y

def toGeo(x, y):
    x /= K * R; y /= K * R
    D = y + lat0r
    return math.degrees(math.asin(math.sin(D) / math.cosh(x))), LON0 + math.degrees(math.atan(math.sinh(x) / math.cos(D)))

terrain = bpy.data.objects["Terrain"]
print("terrain matrix_world translation:", tuple(round(v, 3) for v in terrain.matrix_world.translation))
print("terrain custom props:", {k: terrain[k] for k in terrain.keys() if not k.startswith("_")})

# --- 1. does Blosm's terrain mesh cover the extent we asked for? ------------
co = [terrain.matrix_world @ v.co for v in terrain.data.vertices]
xs = [c.x for c in co]; ys = [c.y for c in co]; zs = [c.z for c in co]
sw, ne = toGeo(min(xs), min(ys)), toGeo(max(xs), max(ys))
print(f"\nterrain XY extent   x [{min(xs):9.1f}, {max(xs):9.1f}]  y [{min(ys):9.1f}, {max(ys):9.1f}]  z [{min(zs):6.1f}, {max(zs):6.1f}]")
print(f"round-tripped SW    {sw[0]:.5f}, {sw[1]:.5f}   requested {REQ['S']:.5f}, {REQ['W']:.5f}")
print(f"round-tripped NE    {ne[0]:.5f}, {ne[1]:.5f}   requested {REQ['N']:.5f}, {REQ['E']:.5f}")
print(f"corner error (m)    SW {abs(sw[0]-REQ['S'])*111320:.1f} N/S, {abs(sw[1]-REQ['W'])*111320*math.cos(lat0r):.1f} E/W")

# --- 2. drop the base stations onto the terrain ----------------------------
bvh = BVHTree.FromObject(terrain, bpy.context.evaluated_depsgraph_get())
def ground(x, y):
    hit = bvh.ray_cast(Vector((x, y, 5000.0)), Vector((0, 0, -1)))
    return hit[0].z if hit[0] else None

sites = [("Agronomy Farm", 42.021016348205585, -93.77358107943655),
         ("Curtiss Farm",  42.00345729383988,  -93.66091628902467),
         ("Wilson Hall",   42.0135968572502,   -93.65091684111805),
         ("Research Park", 41.991051378648365, -93.63638030677834)]
print("\nsite               scene X      scene Y   ground z   lat/lon round-trip err (m)")
out = {}
for name, la, lo in sites:
    x, y = fromGeo(la, lo); g = ground(x, y)
    bla, blo = toGeo(x, y)
    err = math.hypot((bla - la) * 111320, (blo - lo) * 111320 * math.cos(lat0r))
    out[name] = dict(x=x, y=y, ground=g, lat=la, lon=lo)
    print(f"{name:15s} {x:10.1f} {y:12.1f} {(f'{g:8.2f}' if g else '    MISS')}   {err:.3e}")

# --- 3. does the measured route sit inside the terrain? --------------------
n = miss = 0
gx0, gy0, gx1, gy1 = min(xs), min(ys), max(xs), max(ys)
with open(f"{DATA}/COTS.csv") as f:
    for row in csv.DictReader(f):
        try: la, lo = float(row["lat"]), float(row["lon"])
        except (TypeError, ValueError): continue
        x, y = fromGeo(la, lo); n += 1
        if not (gx0 <= x <= gx1 and gy0 <= y <= gy1): miss += 1
print(f"\nmeasurement rows projected: {n}, outside terrain footprint: {miss}")

b = bpy.data.objects["ames.osm_buildings"]
bz = [(b.matrix_world @ v.co).z for v in b.data.vertices]
print(f"buildings z range   [{min(bz):.1f}, {max(bz):.1f}]  (terrain z [{min(zs):.1f}, {max(zs):.1f}])")

json.dump(dict(origin_lat=LAT0, origin_lon=LON0, radius=R, k=K, sites=out,
               terrain_bbox=dict(x0=gx0, y0=gy0, x1=gx1, y1=gy1, z0=min(zs), z1=max(zs))),
          open(f"{BASE}/georef.json", "w"), indent=2)
print("wrote georef.json")
