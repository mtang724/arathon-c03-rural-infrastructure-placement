"""Set a sane view clip range for a 22 km scene and frame it, then re-save.

Blender's default clip_end is 1000 m, so on a scene this size everything is clipped
away and the viewport looks empty even though the objects are present.
"""
import bpy, sys
f = sys.argv[-1]
bpy.ops.wm.open_mainfile(filepath=f)
n = 0
for scr in bpy.data.screens:
    for area in scr.areas:
        if area.type == 'VIEW_3D':
            for sp in area.spaces:
                if sp.type == 'VIEW_3D':
                    sp.clip_start, sp.clip_end = 1.0, 200000.0
                    sp.shading.type = 'SOLID'
                    sp.shading.color_type = 'MATERIAL'
                    sp.region_3d.view_distance = 26000.0
                    sp.region_3d.view_location = (0.0, 0.0, 0.0)
                    n += 1
env = bpy.data.objects.get("Terrain_envelope")
if env:
    env.hide_viewport = env.hide_render = True
    print("hid Terrain_envelope")
print(f"set clip range on {n} viewports")
bpy.ops.wm.save_mainfile(filepath=f)
print("saved", f)
