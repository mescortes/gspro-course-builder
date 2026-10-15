"""Add LiDAR-placed, GPU-instanced trees to the glTF (EXT_mesh_gpu_instancing).

Trees are grouped by archetype, variant and 256 m cell. The detailed LOD lives in the default scene (scene 0); the
light LOD (lod 1) and the crossed-billboard impostors (lod 2) for the same cells live in scene 1 ("VegetationLOD1").
The viewer swaps per cell by camera distance; other glTF viewers show the default scene (detailed trees only).
"""
import sys, json, zlib
import numpy as np
import rasterio

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C
from make_trees import N_VARIANTS

TREES = C.DATA / "trees"
PH = C.DATA / "textures"; GEN = C.DATA / "textures_gen"
BARK = dict(C.REGION["trees"]["bark"])  # archetype -> Poly Haven bark set (regions/<region>.toml [trees] bark)
CELL = 256.0


def ground(e, n):
    with rasterio.open(C.BUILD / "dem.tif") as ds:
        dem = ds.read(1); T = ds.transform
    c = np.clip(((e - T.c) / T.a).astype(int), 0, dem.shape[1] - 1)
    r = np.clip(((n - T.f) / T.e).astype(int), 0, dem.shape[0] - 1)
    # min over a 3x3 so trunks on slopes do not float
    hs = [dem[np.clip(r + dr, 0, dem.shape[0] - 1), np.clip(c + dc, 0, dem.shape[1] - 1)] for dr in (-2, 0, 2) for dc in (-2, 0, 2)]
    return np.min(hs, 0)


def instance_params(trees):
    """Per tree: (variant, yaw rad, scale_xz, scale_y, H0, R0) exactly as placed in the glTF; also used for trees.csv so
    the Unity placement matches the viewer. H0 / R0 are the archetype's reference height and crown radius."""
    rng = np.random.default_rng(7)
    yaw = rng.uniform(0, 2 * np.pi, len(trees))
    ref = {}
    out = []
    for i, t in enumerate(trees):
        p = t["properties"]; arch = p["archetype"]
        var = zlib.crc32(str(p["id"]).encode()) % N_VARIANTS
        if (arch, var) not in ref:
            f = TREES / f"{arch}_v{var}_hi.npz"
            d = np.load(f) if f.exists() else None
            ref[(arch, var)] = (float(d["H"]), float(d["R"])) if d is not None else (1.0, 1.0)
        H0, R0 = ref[(arch, var)]
        sy = p["height"] / H0
        sxz = float(np.clip(p["crown_r"] / R0, 0.55 * sy, 1.7 * sy))
        out.append((var, float(yaw[i]), sxz, float(sy), H0, R0))
    return out


def add(glb, root, trees_path=None, lods=("hi", "lo", "bb")):
    from export_course import encode
    trees = json.load(open(trees_path or (C.FEATURES / "trees.geojson")))["features"]
    if not trees:
        return
    E = np.array([t["geometry"]["coordinates"][0] for t in trees]); N = np.array([t["geometry"]["coordinates"][1] for t in trees])
    G = ground(E, N)
    veg = glb.node("Vegetation", parent=root)
    veg_lo = glb.node("VegetationLOD1", scene=1, extras={"lod": 1, "cell_m": CELL}) if len(lods) > 1 else None
    LOD_INDEX = {"hi": 0, "lo": 1, "bb": 2}
    mats = {}; meshes = {}
    groups = {}
    params = instance_params(trees)
    for i, t in enumerate(trees):
        p = t["properties"]; arch = p["archetype"]
        var = params[i][0]
        ci = int((E[i] - C.CORE["xmin"]) // CELL); cj = int((N[i] - C.CORE["ymin"]) // CELL)
        groups.setdefault((arch, var, ci, cj), []).append(i)
    yaw_all = np.array([q[1] for q in params])
    for (arch, var, ci, cj), idx in sorted(groups.items()):
        idx = np.array(idx)
        h = np.array([trees[i]["properties"]["height"] for i in idx]); cr = np.array([trees[i]["properties"]["crown_r"] for i in idx])
        tr = np.c_[E[idx] - C.ORIGIN_E, G[idx] - C.BASE_H - 0.05, -(N[idx] - C.ORIGIN_N)]
        yaw = yaw_all[idx]
        rot = np.c_[np.zeros(len(idx)), np.sin(yaw / 2), np.zeros(len(idx)), np.cos(yaw / 2)]
        cx = C.CORE["xmin"] + (ci + 0.5) * CELL; cy = C.CORE["ymin"] + (cj + 0.5) * CELL
        centre = [round(cx - C.ORIGIN_E, 1), round(-(cy - C.ORIGIN_N), 1)]
        for lod in lods:
            f = TREES / f"{arch}_v{var}_{lod}.npz"
            if not f.exists():
                continue
            key = (arch, var, lod)
            if key not in meshes:
                d = np.load(f)
                if arch not in mats:
                    b = PH / BARK[arch]
                    bark_m = glb.material(f"Bark_{arch}", base_color=encode(b / "diffuse.jpg", "albedo", None, 1024),
                                          normal=encode(b / "nor_gl.jpg", "normal", None, 1024), orm=encode(b / "arm.jpg", "orm", None, 1024))
                    leaf_m = glb.material(f"Foliage_{arch}", base_color=str(GEN / f"foliage_{arch}.png"), alpha_mode="MASK",
                                          alpha_cutoff=0.45, double_sided=True, rough=0.75, specular=0.35)
                    mats[arch] = (bark_m, leaf_m)
                bark_m, leaf_m = mats[arch]
                prims = []
                if len(d["bark_i"]):
                    prims.append(dict(pos=d["bark_p"], nrm=d["bark_n"], uv0=d["bark_uv"], idx=d["bark_i"], material=bark_m,
                                      col=d["bark_c"] if "bark_c" in d else None))
                prims.append(dict(pos=d["leaf_p"], nrm=d["leaf_n"], uv0=d["leaf_uv"], idx=d["leaf_i"], material=leaf_m,
                                  col=d["leaf_c"] if "leaf_c" in d else None))
                meshes[key] = (glb.mesh(f"Tree_{arch}_v{var}_{lod}", prims), float(d["H"]), float(d["R"]))
            mesh, H0, R0 = meshes[key]
            sy = h / H0
            sxz = np.clip(cr / R0, 0.55 * sy, 1.7 * sy)
            sc = np.c_[sxz, sy, sxz]
            glb.node(f"Tree_{arch}_v{var}_{lod}_c{ci}_{cj}", mesh=mesh, parent=veg if lod == "hi" else veg_lo, instances=(tr, rot, sc),
                     extras={"count": int(len(idx)), "lod": LOD_INDEX[lod], "cell": [ci, cj], "cell_centre_xz": centre})
    print("vegetation groups", len(groups), "trees", len(trees))
