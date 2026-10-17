"""Run inside Blender:  blender -b --python scripts/glb_to_fbx_blender.py -- <in.glb> <out.fbx>

Plain glTF -> FBX conversion (no re-framing) with the same axis settings as export_fbx_blender.py, for assets that live
at their own origin (tree prefabs). Unity takes the prefabs' materials from this file, so each material's images are
wired straight into its shader and embedded under their own names (<material>_color / _normal), and the faces of
double-sided materials get back faces (fbx_materials.py). The geometry is otherwise the glTF's: tree_prefabs.json
counts the glTF's triangles, without the back faces.
"""
import os, sys, tempfile
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbx_materials  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
print("shader inputs wired straight to their images", fbx_materials.wire_images_straight())
print("back faces added", fbx_materials.double_sided_faces())
with tempfile.TemporaryDirectory() as tmp:   # the image files only name the embedded images
    print("images named", fbx_materials.name_packed_images(tmp))
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.fbx(filepath=dst, use_selection=True, object_types={"MESH", "EMPTY"}, apply_unit_scale=True,
                             apply_scale_options="FBX_SCALE_UNITS", axis_forward="-Z", axis_up="Y",
                             bake_space_transform=True, mesh_smooth_type="OFF", path_mode="COPY", embed_textures=True,
                             add_leaf_bones=False)
print("FBX:", dst, len([o for o in bpy.context.scene.objects if o.type == "MESH"]), "meshes")
