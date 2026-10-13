"""Unity tree prefabs for the GSPro hand-off: output/gspro/tree_prefabs.glb (+ .fbx via Blender) and tree_prefabs.json.

One object per archetype x variant, named like the viewer's meshes (Tree_<archetype>_v<k>), at the origin at its
reference size, with children <name>_LOD0 (detailed), _LOD1 (light) and _LOD2 (crossed billboards). Unity's FBX
importer turns the _LOD<n> suffixes into a LOD Group. trees.csv gives each LiDAR tree's prefab, position, yaw and scale.
tree_prefabs.json: reference height / crown radius, trunk radius and crown base (for a trunk collider), triangle counts.
"""
import sys, json, subprocess
import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C
from gltf_builder import GLB
from add_vegetation import TREES, BARK, PH, GEN, N_VARIANTS

OUT = C.OUTPUT / "gspro"
ARCHES = C.TREE_ARCHETYPES
LODS = (("hi", 0), ("lo", 1), ("bb", 2))


def to_gltf(p):
    """make_trees stores y-up points already (x, y=up, z) -> same axes as glTF."""
    return np.asarray(p, np.float32)


def main():
    from export_course import encode
    OUT.mkdir(parents=True, exist_ok=True)
    glb = GLB()
    root = glb.node("TreePrefabs", extras={"note": "reference-size tree prefabs; see tree_prefabs.json"})
    meta = []
    for arch in ARCHES:
        b = PH / BARK[arch]
        bark_m = glb.material(f"Bark_{arch}", base_color=encode(b / "diffuse.jpg", "albedo", None, 1024),
                              normal=encode(b / "nor_gl.jpg", "normal", None, 1024), orm=encode(b / "arm.jpg", "orm", None, 1024))
        leaf_m = glb.material(f"Foliage_{arch}", base_color=str(GEN / f"foliage_{arch}.png"), alpha_mode="MASK",
                              alpha_cutoff=0.45, double_sided=True, rough=0.75, specular=0.35)
        for var in range(N_VARIANTS):
            if not (TREES / f"{arch}_v{var}_hi.npz").exists():
                continue
            name = f"Tree_{arch}_v{var}"
            node = glb.node(name, parent=root)
            tris = {}
            H0 = R0 = None
            trunk_r, crown_base = 0.0, 0.0
            for lod, k in LODS:
                f = TREES / f"{arch}_v{var}_{lod}.npz"
                if not f.exists():
                    continue
                d = np.load(f)
                if H0 is None:
                    H0, R0 = float(d["H"]), float(d["R"])
                prims = []
                if len(d["bark_i"]):
                    prims.append(dict(pos=to_gltf(d["bark_p"]), nrm=d["bark_n"], uv0=d["bark_uv"], idx=d["bark_i"], material=bark_m,
                                      col=d["bark_c"] if "bark_c" in d else None))
                prims.append(dict(pos=to_gltf(d["leaf_p"]), nrm=d["leaf_n"], uv0=d["leaf_uv"], idx=d["leaf_i"], material=leaf_m,
                                  col=d["leaf_c"] if "leaf_c" in d else None))
                tris[f"LOD{k}"] = int(sum(np.asarray(p["idx"]).size for p in prims) // 3)
                if lod == "hi":
                    bp = d["bark_p"]
                    base = bp[bp[:, 1] < 0.6]
                    trunk_r = float(np.percentile(np.hypot(base[:, 0], base[:, 2]), 90)) if len(base) else 0.2
                    lp = d["leaf_p"]
                    crown_base = float(np.percentile(lp[:, 1], 3)) if len(lp) else 0.3 * H0
                glb.node(f"{name}_LOD{k}", mesh=glb.mesh(f"{name}_LOD{k}", prims), parent=node)
            meta.append({"name": name, "archetype": arch, "variant": var, "ref_height_m": round(H0, 3),
                         "ref_crown_radius_m": round(R0, 3), "trunk_radius_m": round(max(trunk_r, 0.05), 3),
                         "crown_base_m": round(crown_base, 3), "triangles": tris})
    glb.save(OUT / "tree_prefabs.glb")
    json.dump({"note": "Prefab = object in tree_prefabs.fbx; scale per tree from trees.csv (scale_xz, scale_y, yaw_deg). "
                       "Suggested ball collider: CapsuleCollider on the trunk of the scaled instance, radius trunk_radius_m "
                       "and height crown_base_m in the prefab's own units - the instance scale already applies to it "
                       "(do not multiply by scale_xz / scale_y again).",
               "prefabs": meta}, open(OUT / "tree_prefabs.json", "w"), indent=1)
    print("tree prefabs", len(meta))


if __name__ == "__main__":
    main()
