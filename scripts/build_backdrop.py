"""Backdrop terrain: a 5 km square of the HRDEM 1 m DTM (2 m grid) around the detailed core, draped with SWOOP 2025.

The inner boundary reuses the exact boundary vertices (and heights) of the core terrain mesh, so the join is
watertight. Two rings: near (core + 640 m, finer mesh, 0.5 m imagery) and far (to 2.5 km, 1.2 m imagery).
Output: build/backdrop_mesh.npz, data/imagery/backdrop_near_<extent>.jpg, data/imagery/backdrop_far_<extent>.jpg
"""
import sys
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


SUMMER_GREEN = (84, 116, 54)   # sRGB target for the median vegetated backdrop pixel (cf. config.TURF_TINT rough)
NDVI_LO, NDVI_HI = 0.08, 0.22   # NDVI ramp: below LO untouched (roads, roofs, water), above HI fully graded


def summer_grade(a, ndvi, target=SUMMER_GREEN, keep_l=0.5):
    """The spring photo drapes the backdrop in grey-brown dormant lawns and leaf-off woods. Move vegetated pixels (NDVI
    ramp NDVI_LO..NDVI_HI) to summer: in Lab their chroma is re-centred on `target`, keeping each pixel's deviation from
    the vegetated median (texture, mowing stripes, crowns); L moves `keep_l` of the way to the target. Pixels with NDVI
    below NDVI_LO are returned unchanged."""
    from skimage.color import rgb2lab, lab2rgb
    w = np.clip((ndvi - NDVI_LO) / (NDVI_HI - NDVI_LO), 0, 1).astype(np.float32)
    veg = w > 0.5
    if not veg.any():
        return a.copy()
    step = 1 if veg.sum() < 2_000_000 else int(np.sqrt(veg.sum() / 2_000_000)) + 1
    sample = rgb2lab(a[::step, ::step][veg[::step, ::step]][None].astype(np.float32) / 255)[0]
    med = np.median(sample, 0)
    tgt = rgb2lab(np.array([[target]], np.float32) / 255)[0, 0]
    shift = np.array([(tgt[0] - med[0]) * keep_l, tgt[1] - med[1], tgt[2] - med[2]], np.float32)
    out = a.copy()
    rows = 2048
    for r0 in range(0, a.shape[0], rows):
        wr = w[r0:r0 + rows]
        if not (wr > 0).any():
            continue
        lab = rgb2lab(a[r0:r0 + rows].astype(np.float32) / 255)
        lab += shift * wr[..., None]
        g = (np.clip(lab2rgb(lab), 0, 1) * 255 + 0.5).astype(np.uint8)
        out[r0:r0 + rows] = np.where((wr > 0)[..., None], g, a[r0:r0 + rows])
    return out


def summer_tif(path):
    """<stem>_summer.tif: the graded RGB, georeferenced like <stem>.tif."""
    return path.with_name(path.stem + "_summer.tif")


def imagery(ext, res, path):
    """<stem>.tif: SWOOP RGB; <stem>_nir.tif: its NIR band (same grid); <stem>_summer.tif: RGB after summer_grade
    (read by the GSPro outer overlay); <stem>.jpg: the summer RGB with lift_shadows (viewer / glTF drape)."""
    tif, nir, summer = path.with_suffix(".tif"), path.with_name(path.stem + "_nir.tif"), summer_tif(path)
    raw = path.with_name(path.stem + "_raw.jpg")
    import fetch_imageserver
    if not tif.exists():
        fetch_imageserver.fetch(ext["xmin"], ext["ymin"], ext["xmax"], ext["ymax"], res, tif)
    if not nir.exists():
        fetch_imageserver.fetch(ext["xmin"], ext["ymin"], ext["xmax"], ext["ymax"], res, nir, bands=(3,))
    if summer.exists() and path.exists() and min(summer.stat().st_mtime, path.stat().st_mtime) > max(
            tif.stat().st_mtime, nir.stat().st_mtime, __import__("os").stat(__file__).st_mtime):
        return
    from scipy import ndimage
    with rasterio.open(tif) as ds:
        a = np.moveaxis(ds.read(), 0, -1); prof = ds.profile
    with rasterio.open(nir) as ds:
        n = ds.read(1).astype(np.float32)
    r = a[..., 0].astype(np.float32)
    ndvi = ndimage.gaussian_filter((n - r) / np.maximum(n + r, 1), 1.0)
    g = summer_grade(a, ndvi)
    with rasterio.open(summer, "w", **dict(prof, compress="deflate")) as ds:
        ds.write(np.moveaxis(g, -1, 0))
    Image.fromarray(a).save(raw, quality=88)
    Image.fromarray(lift_shadows(g)).save(path, quality=88)


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
    imagery(NEAR, 0.5, NEAR_IMG)
    imagery(FAR, 1.25, FAR_IMG)


if __name__ == "__main__":
    main()
