"""Run inside Blender:  blender -b --python scripts/glb_to_fbx_blender.py -- <in.glb> <out.fbx>

Plain glTF -> FBX conversion (no re-framing) with the same axis settings as export_fbx_blender.py, for assets that live
at their own origin (tree prefabs)."""
import sys
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.fbx(filepath=dst, use_selection=True, object_types={"MESH", "EMPTY"}, apply_unit_scale=True,
                         apply_scale_options="FBX_SCALE_UNITS", axis_forward="-Z", axis_up="Y", bake_space_transform=True,
                         mesh_smooth_type="OFF", path_mode="COPY", embed_textures=True, add_leaf_bones=False)
print("FBX:", dst, len([o for o in bpy.context.scene.objects if o.type == "MESH"]), "meshes")
