"""Assign ITU-named materials and export ames.blend to Mitsuba XML for Sionna RT.

Sionna maps a BSDF whose id is 'mat-itu_<type>' onto its built-in ITURadioMaterial,
so the Blender material name is the entire interface. Exported with an identity axis
conversion (forward=Y, up=Z) so Mitsuba XY stays equal to Blosm XY and the
georeference in georef.json remains valid downstream.
"""
import os
from pathlib import Path

# Paths resolve relative to this script so the tree can be moved or cloned anywhere.
BASE = str(Path(__file__).resolve().parent)
import bpy, addon_utils, os

addon_utils.enable("mitsuba-blender", default_set=True, persistent=True)
bpy.ops.wm.open_mainfile(filepath=f"{BASE}/ames.blend")

# The envelope is a Blosm helper box, not a surface. Left in, it would wrap the
# whole scene in an occluder and every ray would terminate on it.
for name in ("Terrain_envelope",):
    obj = bpy.data.objects.get(name)
    if obj:
        bpy.data.objects.remove(obj, do_unlink=True)
        print("removed helper object:", name)

def itu(name, rgb):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = 1.0
    bsdf.inputs["Metallic"].default_value = 0.0
    return m

assign = {
    # bare, pre-planting March fields -> the ground permittivity is the calibration knob
    "Terrain":            itu("itu_medium_dry_ground", (0.45, 0.38, 0.26)),
    "ames.osm_buildings": itu("itu_concrete",          (0.70, 0.70, 0.70)),
}
for obj_name, mat in assign.items():
    obj = bpy.data.objects[obj_name]
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    print(f"{obj_name:22s} -> {mat.name}  ({len(obj.data.polygons)} faces)")

for o in bpy.data.objects:
    o.select_set(True)
bpy.context.view_layer.objects.active = bpy.data.objects["Terrain"]

out = f"{BASE}/mitsuba/ames.xml"
os.makedirs(os.path.dirname(out), exist_ok=True)
bpy.ops.export_scene.mitsuba(
    filepath=out,
    axis_forward='Y', axis_up='Z',   # identity: keep Blosm XY == Mitsuba XY
    export_ids=True,
    ignore_background=True,
)
print("exported:", out)
