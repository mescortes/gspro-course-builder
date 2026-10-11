"""Run inside Blender:  blender -b --python scripts/export_fbx_blender.py -- <in.glb> <out_dir> <terrain.json>

Imports the course glTF and writes Unity/OPCD-ready FBX files positioned in the Unity terrain frame
(x = east from the terrain's west edge, z = north from its south edge, y = height above the terrain base):
  course_meshes.fbx   all Hole##_<Surface> surface meshes (OPCD names -> SetMeshMaterial.cs assigns materials)
  structures.fbx      buildings, bridges, flagstick, tee markers
  backdrop.fbx        5 km imagery-draped surrounding terrain
Also saves course.blend for inspection.
"""
import sys, json
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
glb, out_dir, terrain_json = argv[0], argv[1], argv[2]
meta = json.load(open(terrain_json))
e = meta["utm_extent"]; hmin = meta["height_range_navd88_m"][0]
model_origin = (362650.0, 3775300.0, 350.0)  # config.ORIGIN_E / ORIGIN_N / BASE_H

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
# glTF import: Blender X = east, Y = north, Z = up (metres, model origin). Shift into the Unity terrain frame.
shift = Vector((model_origin[0] - e["xmin"], model_origin[1] - e["ymin"], model_origin[2] - hmin))
roots = [o for o in bpy.context.scene.objects if o.parent is None]
for r in roots:
    r.location += shift
bpy.context.view_layer.update()


def descendants(names):
    """Objects under any node whose name is in `names` (or ends with one of the '*suffix' patterns)."""
    suffixes = tuple(n[1:] for n in names if n.startswith("*"))
    out = []
    for o in bpy.context.scene.objects:
        p = o
        while p is not None:
            base = p.name.split(".")[0]
            if base in names or (suffixes and base.endswith(suffixes)):
                out.append(o)
                break
            p = p.parent
    return out


def mask_colours():
    """Course meshes carry two colour sets from the glTF: 'Color' (photo tint for our viewer) and 'Color.001' (3DG
    grass density masks). Unity reads one: keep the masks, named 'Col' like the OPCD V4 vertex-paint layer."""
    n = 0
    for o in bpy.context.scene.objects:
        if o.type != "MESH":
            continue
        ca = o.data.color_attributes
        if "Color.001" in ca:
            if "Color" in ca:
                ca.remove(ca["Color"])
            ca["Color.001"].name = "Col"
            ca.active_color = ca["Col"]; ca.render_color_index = 0
            n += 1
    return n


MANIFEST = {}


def export(objs, path):
    bpy.ops.object.select_all(action="DESELECT")
    meshes = [o for o in objs if o.type == "MESH"]
    MANIFEST[path.split("/")[-1]] = [{"name": o.name, "materials": [s.material.name if s.material else None for s in o.material_slots],
                                      "colour_layers": [c.name for c in o.data.color_attributes], "vertices": len(o.data.vertices)}
                                     for o in meshes]
    for o in meshes:
        o.select_set(True)
    if not meshes:
        return 0
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True, object_types={"MESH", "EMPTY"}, apply_unit_scale=True,
                             apply_scale_options="FBX_SCALE_UNITS", axis_forward="-Z", axis_up="Y", bake_space_transform=True,
                             mesh_smooth_type="OFF", use_mesh_modifiers=True, path_mode="COPY", embed_textures=False,
                             colors_type="LINEAR",  # vertex colours are 3DG density masks: write the values as they are
                             add_leaf_bones=False)
    return len(meshes)


print("3DG mask layers", mask_colours())
n1 = export(descendants({"Terrain"}), f"{out_dir}/course_meshes.fbx")
# flagsticks / cups and tee markers (Hole##_Furniture) stay out: GSPro draws the pin at runtime and places tee markers
# from the GreenKeeper data (research/GSPRO_COSMETICS.md); they are only for our own viewer
n2 = export(descendants({"Structures", "Bridges"}), f"{out_dir}/structures.fbx")
n3 = export(descendants({"Backdrop_Terrain"}), f"{out_dir}/backdrop.fbx")
print(f"FBX: course meshes {n1}, structures {n2}, backdrop {n3}")
import json
json.dump(MANIFEST, open(f"{out_dir}/fbx_manifest.json", "w"), indent=1)
bpy.context.preferences.filepaths.save_version = 0  # no course.blend1 backup copies
bpy.ops.wm.save_as_mainfile(filepath=f"{out_dir}/course.blend", compress=True)
