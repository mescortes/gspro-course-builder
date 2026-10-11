"""Backdrop terrain: a 5 km square of USGS 1 m DEM (2 m overview) around the detailed core, draped with imagery.

The inner boundary reuses the exact boundary vertices (and heights) of the core terrain mesh, so the join is
watertight. Two rings: near (core + 640 m, finer mesh, 0.5 m imagery) and far (to 2.5 km, 1.2 m imagery).
Output: build/backdrop_mesh.npz, data/imagery/backdrop_near_<extent>.jpg, data/imagery/backdrop_far_<extent>.jpg
"""
import sys, subprocess
import numpy as np
import rasterio
import triangle
from scipy.interpolate import RegularGridInterpolator
from PIL import Image

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C

FAR = dict(xmin=C.ORIGIN_E - 2500, ymin=C.ORIGIN_N - 2500, xmax=C.ORIGIN_E + 2500, ymax=C.ORIGIN_N + 2500)
NEAR = dict(xmin=C.CORE["xmin"] - 640, ymin=C.CORE["ymin"] - 640, xmax=C.CORE["xmax"] + 640, ymax=C.CORE["ymax"] + 640)
# imagery files are keyed by extent so different build profiles never reuse a mismatched image
NEAR_IMG = C.DATA / "imagery" / f"backdrop_near_{int(NEAR['xmin'])}_{int(NEAR['ymin'])}_{int(NEAR['xmax'])}_{int(NEAR['ymax'])}.jpg"
FAR_IMG = C.DATA / "imagery" / f"backdrop_far_{int(FAR['xmin'])}_{int(FAR['ymin'])}_{int(FAR['xmax'])}_{int(FAR['ymax'])}.jpg"


def core_boundary():
    d = np.load(C.BUILD / "terrain_mesh.npz")
    V, F = d["V"], d["F"]
    e = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), 1)
    key = e[:, 0].astype(np.int64) * len(V) + e[:, 1]
    u, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    b = e[cnt[inv] == 1]
    vid = np.unique(b)
    return V[vid], b, vid


def lift_shadows(a, knee=40.0, keep=0.6, chroma=1.25):
    """Photo shadows on steep slopes + live shading in the renderer = near-black hillsides. Compress the dark end of
    the tone curve (Lab L below `knee` is pulled up, keeping `keep` of its distance to the knee) and restore a little
    chroma there so lifted shadows stay green rather than grey. Pixel-local: no haze, detail preserved."""
    from skimage.color import rgb2lab, lab2rgb
    out = np.empty_like(a)
    step = 2048
    for r0 in range(0, a.shape[0], step):
        lab = rgb2lab(a[r0:r0 + step].astype(np.float32) / 255)
        L = lab[..., 0]
        dark = L < knee
        w = np.clip((knee - L) / knee, 0, 1)
        lab[..., 0] = np.where(dark, knee - (knee - L) * keep, L)
        lab[..., 1] *= 1 + (chroma - 1) * w
        lab[..., 2] *= 1 + (chroma - 1) * w
        out[r0:r0 + step] = (np.clip(lab2rgb(lab), 0, 1) * 255 + 0.5).astype(np.uint8)
    return out


def imagery(ext, zoom, res, path):
    raw = path.with_name(path.stem + "_raw.jpg")
    if not path.with_suffix(".tif").exists():
        subprocess.run([sys.executable, str(C.ROOT / "scripts/fetch_tiles.py"), "esri", str(zoom), str(ext["xmin"]), str(ext["ymin"]),
                        str(ext["xmax"]), str(ext["ymax"]), str(res), str(path.with_suffix(".tif"))], check=True)
    if not raw.exists() or raw.stat().st_mtime < path.with_suffix(".tif").stat().st_mtime:
        with rasterio.open(path.with_suffix(".tif")) as ds:
            a = np.moveaxis(ds.read(), 0, -1)
        Image.fromarray(a).save(raw, quality=88)
        Image.fromarray(lift_shadows(a)).save(path, quality=88)


def main():
    PV, PB, vid = core_boundary()
    remap = {v: i for i, v in enumerate(vid)}
    o = np.array([C.ORIGIN_E, C.ORIGIN_N])
    pts = [PV[:, :2] - o]
    segs = [np.vectorize(remap.get)(PB)]
    def square(ext, base):
        c = np.array([[ext["xmin"], ext["ymin"]], [ext["xmax"], ext["ymin"]], [ext["xmax"], ext["ymax"]], [ext["xmin"], ext["ymax"]]]) - o
        # subdivide edges so the boundary is not a few huge segments
        P = []
        for i in range(4):
            a, b = c[i], c[(i + 1) % 4]
            n = int(np.linalg.norm(b - a) / 40)
            for t in np.linspace(0, 1, n, endpoint=False):
                P.append(a + (b - a) * t)
        P = np.array(P)
        S = np.c_[np.arange(len(P)), (np.arange(len(P)) + 1) % len(P)] + base
        return P, S
    n0 = len(pts[0])
    Pn, Sn = square(NEAR, n0); pts.append(Pn); segs.append(Sn)
    Pf, Sf = square(FAR, n0 + len(Pn)); pts.append(Pf); segs.append(Sf)
    P = np.concatenate(pts); S = np.concatenate(segs)
    core_c = np.array([(C.CORE["xmin"] + C.CORE["xmax"]) / 2, (C.CORE["ymin"] + C.CORE["ymax"]) / 2]) - o
    regions = np.array([[NEAR["xmin"] - o[0] + 5, NEAR["ymin"] - o[1] + 5, 1, 30.0],   # near ring
                        [FAR["xmin"] - o[0] + 5, FAR["ymin"] - o[1] + 5, 2, 250.0]])  # far ring
    tri = triangle.triangulate({"vertices": P, "segments": S, "regions": regions, "holes": core_c[None]}, "pq28Aa")
    Vt = tri["vertices"]; Ft = tri["triangles"]; ring = tri["triangle_attributes"][:, 0].astype(int)
    with rasterio.open(C.DATA / "dem/backdrop_dem.tif") as ds:
        Z = ds.read(1).astype(np.float64); T = ds.transform
    xs = T.c + (np.arange(Z.shape[1]) + 0.5) * T.a - o[0]; ys = T.f + (np.arange(Z.shape[0]) + 0.5) * T.e - o[1]
    f = RegularGridInterpolator((ys[::-1], xs), Z[::-1], bounds_error=False, fill_value=None)
    z = f(np.c_[Vt[:, 1], Vt[:, 0]])
    # seam vertices keep the exact core heights
    z[:n0] = PV[:, 2]
    V = np.c_[Vt + o, z]
    np.savez_compressed(C.BUILD / "backdrop_mesh.npz", V=V, F=Ft.astype(np.int32), ring=ring, n_seam=n0)
    print("backdrop triangles", len(Ft), "near", (ring == 1).sum(), "far", (ring == 2).sum())
    imagery(NEAR, 18, 0.5, NEAR_IMG)
    imagery(FAR, 17, 1.25, FAR_IMG)


if __name__ == "__main__":
    main()
