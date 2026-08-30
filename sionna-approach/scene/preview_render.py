"""Render a top-down Workbench preview so we can confirm the geometry is really there."""
import bpy, sys, math
f, out = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.open_mainfile(filepath=f)
sc = bpy.context.scene
cam_data = bpy.data.cameras.new("prev"); cam_data.type = 'ORTHO'
cam_data.ortho_scale = 23000; cam_data.clip_start = 1; cam_data.clip_end = 200000
cam = bpy.data.objects.new("prev", cam_data)
cam.location = (0, 0, 20000); cam.rotation_euler = (0, 0, 0)
sc.collection.objects.link(cam); sc.camera = cam
for o in bpy.data.objects:
    if o.name.startswith("Terrain_envelope"): o.hide_render = True
sc.render.engine = 'BLENDER_WORKBENCH'
sc.display.shading.light = 'STUDIO'
sc.display.shading.color_type = 'MATERIAL'
sc.display.shading.show_shadows = False
sc.display.shading.show_cavity = True
sc.display.shading.cavity_type = "WORLD"
sc.render.resolution_x, sc.render.resolution_y = 1400, 900
sc.render.film_transparent = False
sc.render.filepath = out
bpy.ops.render.render(write_still=True)
print("rendered", out)
