"""Build a viewable .blend with the 10 m 3DEP terrain + the OSM buildings.

Both meshes are already in the shared scene frame, so the PLY drops straight in
with no transform. Run:
  /Applications/Blender.app/Contents/MacOS/Blender -b -P make_blend_3dep.py
"""
import os
from pathlib import Path

# Paths resolve relative to this script so the tree can be moved or cloned anywhere.
BASE = str(Path(__file__).resolve().parent)
import bpy, os

bpy.ops.wm.open_mainfile(filepath=f"{BASE}/ames.blend")
for n in ("Terrain", "Terrain_envelope"):          # drop the 30 m version + helper box
    o = bpy.data.objects.get(n)
    if o: bpy.data.objects.remove(o, do_unlink=True); print("removed", n)

bpy.ops.wm.ply_import(filepath=f"{BASE}/mitsuba/meshes/Terrain3DEP.ply")
t = bpy.context.selected_objects[0]
t.name = "Terrain_3DEP_10m"
print(f"{t.name}: {len(t.data.vertices):,} verts")

for name, rgb in (("itu_medium_dry_ground", (0.45, 0.38, 0.26, 1)),
                  ("itu_concrete", (0.7, 0.7, 0.7, 1))):
    if name not in bpy.data.materials:
        m = bpy.data.materials.new(name); m.use_nodes = True
        m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = rgb
t.data.materials.clear(); t.data.materials.append(bpy.data.materials["itu_medium_dry_ground"])

# markers at the four base stations so the scene is readable on open
import json, math
g = json.load(open(f"{BASE}/georef.json"))
for n, s in g["sites"].items():
    e = bpy.data.objects.new(f"BS_{n.replace(' ','_')}", None)
    e.empty_display_type = 'SPHERE'; e.empty_display_size = 150
    e.location = (s["x"], s["y"], s["ground"] + 30)
    bpy.context.collection.objects.link(e)

bpy.ops.wm.save_as_mainfile(filepath=f"{BASE}/ames_3dep.blend")
print("saved ames_3dep.blend")
