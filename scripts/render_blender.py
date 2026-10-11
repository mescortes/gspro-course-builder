"""Headless still renders of the course glTF (visual QA without a browser), with Cycles on the CPU.

  blender -b --python scripts/render_blender.py -- <in.glb> <out_dir> <views.json> [name ...] [--size 1600x900]
         [--samples 48] [--holes output/holes.json]

Cameras come from viewer/views.json (model frame: x = E - ORIGIN_E, y = height - BASE_H, z = -(N - ORIGIN_N)), plus
per-hole presets h<N>-tee / h<N>-green derived from output/holes.json when --holes is given (names like h3-tee).
glTF import in Blender: X = model x, Y = -model z, Z = model y.
"""
import json, math, sys
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
opts = {"--size": "1600x900", "--samples": "48", "--holes": None}
pos = []
i = 0
while i < len(argv):
    if argv[i] in opts:
        opts[argv[i]] = argv[i + 1]; i += 2
    else:
        pos.append(argv[i]); i += 1
glb, out_dir, views_path = pos[:3]
names = pos[3:]
W, H = map(int, opts["--size"].split("x"))

views = json.load(open(views_path))
if opts["--holes"]:
    data = json.load(open(opts["--holes"]))
    for h in data["holes"]:
        if not h.get("tees"):
            continue
        t = h["tees"][0]["model"]; g = h["green"]["centre_model"]
        aim = h["aim_points"][0]["model"] if h["aim_points"] else g
        d = Vector((aim[0] - t[0], 0, aim[2] - t[2])).normalized()
        views[f"h{h['hole']}-tee"] = {"pos": [t[0] - d.x * 4, t[1] + 1.9, t[2] - d.z * 4], "target": [aim[0], aim[1], aim[2]], "fov": 55}
        cl = h["centerline_utm"]
        a = Vector((cl[-1][0] - cl[-2][0], cl[-1][1] - cl[-2][1], 0)).normalized()  # approach direction (E, N)
        views[f"h{h['hole']}-green"] = {"pos": [g[0] - a.x * 45, g[1] + 2.2, g[2] + a.y * 45], "target": g, "fov": 45}

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = int(opts["--samples"])
scene.cycles.use_denoising = True
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - Base Contrast"
scene.render.film_transparent = False
# sky + sun (late-morning summer sun from the south-east)
world = bpy.data.worlds.new("World"); scene.world = world; world.use_nodes = True
nt = world.node_tree; bg = nt.nodes["Background"]
sky = nt.nodes.new("ShaderNodeTexSky"); sky.sky_type = "NISHITA"; sky.sun_elevation = math.radians(48); sky.sun_rotation = math.radians(150)
nt.links.new(sky.outputs["Color"], bg.inputs["Color"]); bg.inputs["Strength"].default_value = 0.25
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN")); scene.collection.objects.link(sun)
sun.data.energy = 2.6; sun.data.angle = math.radians(0.6)
sun.rotation_euler = (math.radians(90 - 48), 0, math.radians(150 + 180))
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam")); scene.collection.objects.link(cam); scene.camera = cam
cam.data.clip_start = 0.05; cam.data.clip_end = 6000


def blender(p):
    return Vector((p[0], -p[2], p[1]))


for name in (names or list(views)):
    v = views[name]
    cam.location = blender(v["pos"])
    d = blender(v["target"]) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cam.data.sensor_fit = "VERTICAL"   # viewer fov (three.js) is vertical
    cam.data.angle_y = math.radians(v.get("fov", 50))
    scene.render.filepath = f"{out_dir}/{name}.png"
    bpy.ops.render.render(write_still=True)
    print("rendered", name, flush=True)
