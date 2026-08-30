"""Headless Blosm import of the Challenge-3 scene: terrain first, then local OSM.

Run:  /Applications/Blender.app/Contents/MacOS/Blender -b -P import_scene.py
Both data sources are local (pre-seeded skadi tiles + clipped ames.osm), so this
makes no network calls and cannot hit the Overpass 504s that block the GUI path.
"""
import os
from pathlib import Path

# Paths resolve relative to this script so the tree can be moved or cloned anywhere.
BASE = str(Path(__file__).resolve().parent)
import bpy, addon_utils, os, sys

S, W, N, E = 41.9200, -93.8950, 42.0500, -93.6250

addon_utils.enable("blosm", default_set=True, persistent=True)

prefs = bpy.context.preferences.addons["blosm"].preferences
prefs.dataDir = os.path.join(BASE, "blosm_data")
print("dataDir:", prefs.dataDir)

# start from an empty scene
bpy.ops.wm.read_homefile(use_empty=True)

b = bpy.context.scene.blosm
b.commandLineMode = True
b.minLat, b.maxLat, b.minLon, b.maxLon = S, N, W, E

# --- pass 1: terrain (stamps the georeference origin) -----------------------
b.dataType = "terrain"
b.terrainResolution = "1"          # 1 arc-second skadi tiles
b.terrainPrimitiveType = "quad"
b.terrainReductionRatio = "1"
bpy.ops.blosm.import_data()
print("after terrain, objects:", [o.name for o in bpy.data.objects])

# --- pass 2: OSM from the local clip, identical extent ----------------------
b.dataType = "osm"
b.osmSource = "file"
b.osmFilepath = os.path.join(BASE, "ames.osm")
b.mode = "3Dsimple"
b.buildings = True
b.water = b.forests = b.vegetation = b.highways = b.railways = False
b.singleObject = True
b.coordinatesAsFilter = True       # clip the 51 MB file to the extent
bpy.ops.blosm.import_data()

sc = bpy.context.scene
print("=" * 60)
print("ORIGIN lat/lon:", sc.get("lat"), sc.get("lon"))
print("objects:", [(o.name, len(o.data.vertices) if o.type == 'MESH' else '-')
                   for o in bpy.data.objects])
print("=" * 60)

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(BASE, "ames.blend"))
print("saved ames.blend")
