"""Siting constraints for candidate locations, derived from open data.

Challenge 03 asks for sensitivity to *placement* constraints, but the measurement dataset
carries none: it says where service is poor, not where an asset may legally or practically
be built. ARA has not supplied utility or land records (see
`sionna-approach/DATA_REQUEST.md`), so every layer here is an open-data **proxy**, and the
planner labels them as such. They are real geography, not invented numbers -- but a power
tower in OpenStreetMap is evidence of a distribution line nearby, not an interconnection
agreement.

Layers, and what each stands in for:

  grid power     power=tower|pole|line|minor_line|substation   distance to the nearest
  land access    highway=*                                     public right-of-way
  structures     building footprints, silos, masts, towers     something to mount on
  backhaul       the four existing base stations               donor/fibre proximity
  exclusion      natural=water, waterway=riverbank             cannot build there

Distances are metres to the nearest feature of each class.
"""
from __future__ import annotations
import json, math, re
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OSM = ROOT / "sionna-approach" / "scene" / "ames.osm"
MSB = ROOT / "sionna-approach" / "scene" / "ms_buildings.json"
GEOREF = ROOT / "sionna-approach" / "scene" / "georef.json"   # committed; the dataset YAML is not

LAYERS = {
    "power":     dict(label="Grid power", proxy="power tower, pole, line or substation"),
    "road":      dict(label="Land access", proxy="any mapped highway (public right-of-way)"),
    "structure": dict(label="Existing structure", proxy="building, silo, mast or tower"),
    "backhaul":  dict(label="Backhaul", proxy="distance to an existing base station"),
    "water":     dict(label="Water (exclusion)", proxy="mapped water body or riverbank"),
}


def _m_per_deg(lat0: float) -> tuple[float, float]:
    return 111_320.0 * math.cos(math.radians(lat0)), 110_540.0


def _nodes(osm: str) -> dict[str, tuple[float, float]]:
    return {m.group(1): (float(m.group(2)), float(m.group(3)))
            for m in re.finditer(
                r'<node id="(\d+)"[^>]*lat="([-\d.]+)" lon="([-\d.]+)"', osm)}


def extract(verbose: bool = True) -> dict[str, np.ndarray]:
    """Point clouds, one per layer, as (lat, lon) arrays.

    Ways are represented by their vertices rather than their geometry: nearest-vertex is
    within half a segment length of nearest-point, and OSM segments here are short. That
    is well inside the honesty of the proxy.
    """
    osm = OSM.read_text(errors="replace")
    nodes = _nodes(osm)
    pts: dict[str, list] = {k: [] for k in LAYERS}

    # tagged standalone nodes (power towers and poles are nodes, not ways)
    for m in re.finditer(r'<node id="(\d+)"[^>]*lat="([-\d.]+)" lon="([-\d.]+)"[^/>]*>(.*?)</node>',
                         osm, re.S):
        body = m.group(4)
        la, lo = float(m.group(2)), float(m.group(3))
        if re.search(r'k="power" v="(tower|pole|substation|transformer)"', body):
            pts["power"].append((la, lo))
        if re.search(r'k="man_made" v="(mast|tower|silo|water_tower|storage_tank)"', body):
            pts["structure"].append((la, lo))

    for wm in re.finditer(r'<way id="\d+".*?</way>', osm, re.S):
        body = wm.group(0)
        refs = [r for r in re.findall(r'<nd ref="(\d+)"', body) if r in nodes]
        if not refs:
            continue
        coords = [nodes[r] for r in refs]
        if re.search(r'k="power" v="(line|minor_line|substation)"', body):
            pts["power"] += coords
        if 'k="highway"' in body:
            pts["road"] += coords
        if re.search(r'k="natural" v="water"', body) or 'v="riverbank"' in body:
            pts["water"] += coords
        if re.search(r'k="(building|man_made)"', body):
            pts["structure"] += coords

    if MSB.exists():                       # the ML footprints are the bulk of rural structures
        for ring in json.load(open(MSB)):
            lo = sum(p[0] for p in ring) / len(ring)
            la = sum(p[1] for p in ring) / len(ring)
            pts["structure"].append((la, lo))

    for s in json.loads(GEOREF.read_text())["sites"].values():
        pts["backhaul"].append((s["lat"], s["lon"]))

    out = {k: np.array(v, dtype=float) if v else np.zeros((0, 2)) for k, v in pts.items()}
    if verbose:
        for k, v in out.items():
            print(f"  {LAYERS[k]['label']:20s} {len(v):7,d} features   ({LAYERS[k]['proxy']})")
    return out


def distances(cand_lat, cand_lon, layers: dict[str, np.ndarray],
              lat0: float | None = None) -> dict[str, np.ndarray]:
    """Metres from every candidate to the nearest feature of each layer."""
    cand_lat = np.asarray(cand_lat, float); cand_lon = np.asarray(cand_lon, float)
    lat0 = float(np.mean(cand_lat)) if lat0 is None else lat0
    mx, my = _m_per_deg(lat0)
    cx, cy = cand_lon * mx, cand_lat * my
    res = {}
    for k, pts in layers.items():
        if len(pts) == 0:
            res[k] = np.full(len(cand_lat), np.inf); continue
        px, py = pts[:, 1] * mx, pts[:, 0] * my
        best = np.full(len(cand_lat), np.inf)
        step = max(1, 2_000_000 // max(len(cand_lat), 1))     # bound peak memory
        for s in range(0, len(px), step):
            d2 = ((cx[:, None] - px[None, s:s+step]) ** 2 +
                  (cy[:, None] - py[None, s:s+step]) ** 2).min(axis=1)
            best = np.minimum(best, d2)
        res[k] = np.sqrt(best)
    return res


if __name__ == "__main__":
    print("constraint layers:")
    L = extract()
