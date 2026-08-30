"""Compute a terrain-following RSRP surface for the Agronomy Farm site.

Uses the terrain mesh itself as Sionna's measurement surface, so predicted values
follow the real ground rather than a flat plane through 94 m of relief.

usage: radio_map.py <scene.xml> <h_ant> <out.npz> [cell_m]
"""
import os
from pathlib import Path

# Paths resolve relative to this script so the tree can be moved or cloned anywhere.
BASE = str(Path(__file__).resolve().parent)
import json, math, sys, numpy as np, mitsuba as mi
from sionna.rt import load_scene, Transmitter, PlanarArray, RadioMapSolver

FC = 3.4608e9
SECTORS = {"00019C00B": 0.0, "00019C015": 115.0, "00019C01F": 240.0}
XML, H, OUT = sys.argv[1], float(sys.argv[2]), sys.argv[3]
CELL = float(sys.argv[4]) if len(sys.argv) > 4 else 60.0

g = json.load(open(f"{BASE}/georef.json"))
scene = load_scene(f"{BASE}/{XML}", merge_shapes=False)
scene.frequency = FC
scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="tr38901", polarization="V")
scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")

site = g["sites"]["Agronomy Farm"]
for cid, az in SECTORS.items():
    scene.add(Transmitter(name=cid, position=[site["x"], site["y"], site["ground"] + H],
                          orientation=[math.radians(90.0 - az), 0.0, 0.0]))

terrain = scene.objects["Terrain"]
solver = RadioMapSolver()
rm = solver(scene, measurement_surface=terrain, max_depth=3,
            los=True, specular_reflection=True, diffuse_reflection=False,
            refraction=False, samples_per_tx=10_000_000)
print("radio map type:", type(rm).__name__)

pg = np.array(rm.path_gain)                      # [n_tx, n_cells]
best = pg.max(axis=0)
print(f"cells {best.size:,}, with signal {(best>0).sum():,}")

# centroid of every measurement-surface triangle, to place each cell in the plane
mesh = terrain.mi_mesh if hasattr(terrain, "mi_mesh") else None
np.savez_compressed(OUT, path_gain=pg.astype(np.float32), best=best.astype(np.float32),
                    h_ant=H, xml=XML)
print("wrote", OUT)
