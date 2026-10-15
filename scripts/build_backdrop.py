"""Backdrop terrain: a square of the backdrop DEM (2 m grid) around the detailed core, draped with the course photo:
5 km (ORIGIN +/- 2500 m), larger when the GSPro outer plot of a wide terrain needs it (far_extent).

The inner boundary reuses the exact boundary vertices (and heights) of the core terrain mesh, so the join is
watertight. Two rings: near (core + 640 m, finer mesh, 0.5 m imagery) and far (to the square's edge, 1.25 m imagery).
Output: build/backdrop_mesh.npz, data/imagery/backdrop_near_<extent>.jpg, data/imagery/backdrop_far_<extent>.jpg
"""
import json, math, sys
from pathlib import Path
import numpy as np
import rasterio
import triangle
from scipy.interpolate import RegularGridInterpolator
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import config as C

NEAR_RING = 640.0   # m the near ring (finer mesh, 0.5 m photo) reaches past the core
MARGIN = 100.0      # m of backdrop kept past the GSPro outer plot and the near ring


def near_extent(core):
    return dict(xmin=core["xmin"] - NEAR_RING, ymin=core["ymin"] - NEAR_RING, xmax=core["xmax"] + NEAR_RING,
                ymax=core["ymax"] + NEAR_RING)


def far_extent():
    """The backdrop square ORIGIN +/- R: the backdrop DEM (fetch_backdrop.py), the far photo and the far ring. R is
    [tuning] backdrop_half_m (2500 m, a 5 km square) unless the GSPro outer plot (export_gspro.outer_extent, twice the
    terrain: a terrain over about 2.2 km) or the near ring (a core over about 3.7 km) comes within MARGIN of its edge;
    then R is the next whole 100 m past them. The course profile's frame counts in both profiles, so the test profile
    reads the course's backdrop DEM (data/<slug>/ is shared)."""
    from export_gspro import outer_extent
    reach = max(max(C.ORIGIN_E - e["xmin"], e["xmax"] - C.ORIGIN_E, C.ORIGIN_N - e["ymin"], e["ymax"] - C.ORIGIN_N)
                for core, te in ((C.FETCH_CORE, C.FETCH_TERRAIN), (C.CORE, C.TERRAIN))
                for e in (outer_extent(te), near_extent(core)))
    half = C.tuning("backdrop_half_m", 2500.0)
    if reach + MARGIN > half:
        half = math.ceil((reach + MARGIN) / 100.0) * 100.0
    return dict(xmin=C.ORIGIN_E - half, ymin=C.ORIGIN_N - half, xmax=C.ORIGIN_E + half, ymax=C.ORIGIN_N + half)


FAR = far_extent()
NEAR = near_extent(C.CORE)
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


def _rel(p):
    try:
        return Path(p).relative_to(C.ROOT)
    except ValueError:
        return Path(p)


def require_cover(path, ext, what):
    """Exit unless the raster `path` covers `ext`: past its border the samplers repeat its edge heights (flat smeared
    bands with no message), e.g. a backdrop DEM fetched before the [frame] terrain grew."""
    if not Path(path).exists():
        sys.exit(f"{_rel(path)}: missing (the backdrop DEM): run scripts/fetch_backdrop.py")
    with rasterio.open(path) as ds:
        b = ds.bounds
    if b.left > ext["xmin"] + 1e-6 or b.right < ext["xmax"] - 1e-6 or b.bottom > ext["ymin"] + 1e-6 or b.top < ext["ymax"] - 1e-6:
        sys.exit(f"{_rel(path)} covers E {b.left:.0f}-{b.right:.0f} N {b.bottom:.0f}-{b.top:.0f}, but {what} needs "
                 f"E {ext['xmin']:.0f}-{ext['xmax']:.0f} N {ext['ymin']:.0f}-{ext['ymax']:.0f}: run scripts/fetch_backdrop.py "
                 "again (it sizes the backdrop to the course.toml [frame] terrain), then build_all.py backdrop")


def datum_offset(dem, backdrop, core, band=(10.0, 50.0), res=2.0):
    """(median, MAD, cells) of backdrop minus LiDAR DEM heights (m) on `res` m cells `band` m inside the build extent
    `core`, where both are bare ground and the course's own edits (water levels, built-up tees) are further in; None
    when no cell has both."""
    from rasterio.enums import Resampling
    from rasterio.windows import from_bounds
    W, H = int(round((core["xmax"] - core["xmin"]) / res)), int(round((core["ymax"] - core["ymin"]) / res))
    z = []
    for p in (dem, backdrop):
        with rasterio.open(p) as ds:
            z.append(ds.read(1, window=from_bounds(core["xmin"], core["ymin"], core["xmax"], core["ymax"], transform=ds.transform),
                             out_shape=(H, W), resampling=Resampling.average, boundless=True, fill_value=np.nan).astype(np.float64))
    x, y = (np.arange(W) + 0.5) * res, (np.arange(H) + 0.5) * res
    d = np.minimum(np.minimum(x, W * res - x)[None, :], np.minimum(y, H * res - y)[:, None])
    diff = (z[1] - z[0])[(d >= band[0]) & (d <= band[1])]
    diff = diff[np.isfinite(diff)]
    if not diff.size:
        return None
    med = float(np.median(diff))
    return med, float(np.median(np.abs(diff - med))), int(diff.size)


def check_datum(dem, backdrop, core):
    """The backdrop DEM's offset from the LiDAR DEM round the build extent. Another vertical datum (ellipsoidal vs
    orthometric heights, an older national datum) or unit (feet) would leave a wall or a berm all round the course:
    a warning above [tuning] backdrop_datum_warn_m (0.3 m), a stop above backdrop_datum_max_m (3 m)."""
    r = datum_offset(dem, backdrop, core)
    if r is None:
        print("!! backdrop DEM vs LiDAR DEM: no cell near the edge of the build extent has both heights", flush=True)
        return
    med, mad, n = r
    msg = f"backdrop DEM - LiDAR DEM, 10-50 m inside the build extent: median {med:+.2f} m, MAD {mad:.2f} m ({n} cells)"
    if abs(med) > C.tuning("backdrop_datum_max_m", 3.0):
        sys.exit(f"{msg}. The backdrop DEM ([sources.backdrop]) is on another vertical datum than the point cloud "
                 "([sources.lidar]), or in feet. Use a backdrop DEM in metres on the LiDAR's datum, or for a constant "
                 f"datum offset set [sources.backdrop] z_offset = {-med:.2f} in courses/{C.SLUG}/course.toml and run "
                 "scripts/fetch_backdrop.py again")
    warn = abs(med) > C.tuning("backdrop_datum_warn_m", 0.3)
    print(("!! " if warn else "") + msg + (": a step round the course (another vertical datum? [sources.backdrop] "
                                           "z_offset moves the backdrop)" if warn else ""), flush=True)


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


_GRADE = C.REGION["backdrop"]  # regions/<region>.toml [backdrop]
SUMMER_GREEN = tuple(_GRADE["summer_green"])   # sRGB target for the median vegetated backdrop pixel (cf. config.TURF_TINT)
NDVI_LO, NDVI_HI = _GRADE["ndvi"]   # NDVI ramp: below LO untouched (roads, roofs, water), above HI fully graded


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


_NOTED = set()


def note(msg):
    """Print `msg` once per run (the near and the far photo share their notes)."""
    if msg not in _NOTED:
        _NOTED.add(msg)
        print(msg, flush=True)


def grade_key(ndvi):
    """What the graded photos depend on besides the photo, its NIR band and this file: the region / course [backdrop]
    grade, and whether there is a NIR band to grade by. Kept in <stem>_summer.tif's tags: a changed grade is redone."""
    return json.dumps({"backdrop": _GRADE, "ndvi": bool(ndvi)}, sort_keys=True)


def _grade_of(p):
    try:
        with rasterio.open(p) as ds:
            return ds.tags().get("BACKDROP_GRADE")
    except rasterio.errors.RasterioIOError:
        return None


def imagery(ext, res, path):
    """<stem>.tif: the photo's RGB; <stem>_nir.tif: its NIR band (same grid), when [sources.imagery] bands has one;
    <stem>_summer.tif: RGB after summer_grade (read by the GSPro outer overlay); <stem>.jpg: the summer RGB with
    lift_shadows (viewer / glTF drape). Without NIR there is no NDVI to find the vegetation by: no grade."""
    tif, nir, summer = path.with_suffix(".tif"), path.with_name(path.stem + "_nir.tif"), summer_tif(path)
    raw = path.with_name(path.stem + "_raw.jpg")
    import sources
    mod, spec = sources.provider("imagery")
    nir_band = tuple(spec["bands"][3:4])   # bands = R, G, B[, NIR]
    if not tif.exists():
        mod.fetch(spec, ext["xmin"], ext["ymin"], ext["xmax"], ext["ymax"], res, tif, bands=tuple(spec["bands"][:3]))
    if not nir_band:
        nir = None
        if _GRADE["summer_grade"]:
            note(f"backdrop: [sources.imagery] bands = {list(spec['bands'])} has no NIR band, so the backdrop photos keep "
                 "their own colours (the summer grade finds the vegetation by NDVI)")
    elif not nir.exists():
        mod.fetch(spec, ext["xmin"], ext["ymin"], ext["xmax"], ext["ymax"], res, nir, bands=nir_band)
    key = grade_key(nir is not None)
    if summer.exists() and path.exists() and min(summer.stat().st_mtime, path.stat().st_mtime) > max(
            p.stat().st_mtime for p in (tif, nir, Path(__file__)) if p is not None) and _grade_of(summer) == key:
        return
    from scipy import ndimage
    with rasterio.open(tif) as ds:
        a = np.moveaxis(ds.read(), 0, -1); prof = ds.profile
    g = a
    if _GRADE["summer_grade"] and nir is not None:
        with rasterio.open(nir) as ds:
            n = ds.read(1).astype(np.float32)
        r = a[..., 0].astype(np.float32)
        ndvi = ndimage.gaussian_filter((n - r) / np.maximum(n + r, 1), 1.0)
        g = summer_grade(a, ndvi)
    with rasterio.open(summer, "w", **dict(prof, compress="deflate")) as ds:
        ds.write(np.moveaxis(g, -1, 0))
        ds.update_tags(BACKDROP_GRADE=key)
    Image.fromarray(a).save(raw, quality=88)
    Image.fromarray(lift_shadows(g)).save(path, quality=88)


def main():
    dem = C.DATA / "dem/backdrop_dem.tif"
    require_cover(dem, FAR, "the far backdrop ring")
    if (C.BUILD / "dem_final.tif").exists():
        check_datum(C.BUILD / "dem_final.tif", dem, C.CORE)
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
    with rasterio.open(dem) as ds:
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
