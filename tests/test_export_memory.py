"""Memory of the export and gspro steps (export_course.py, export_gspro.py: after the mesh step's fix the build's
largest, 7.6 and 8.6 GB on Whistle Bear). Each helper made leaner must give bit for bit what it gave before: the
pre-change code is kept here verbatim (`_*_before`) and compared on synthetic data. Fast: synthetic data only."""
import json
import sys
import tracemalloc
import weakref
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.windows import from_bounds
from scipy import ndimage
from shapely.geometry import Point, box, mapping, shape
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config as C  # noqa: E402
import export_course as E  # noqa: E402
import export_gspro as G  # noqa: E402
from gltf_builder import GLB  # noqa: E402


# ---- the code before (verbatim, but for module prefixes)

def _imagery_linear_before(W, H):
    e = E.C.CORE
    with rasterio.open(E.C.IMAGERY) as ds:
        a = ds.read([1, 2, 3], window=from_bounds(e["xmin"], e["ymin"], e["xmax"], e["ymax"], transform=ds.transform),
                    out_shape=(3, H, W), resampling=Resampling.average)
    return E.srgb_to_lin(np.moveaxis(a, 0, -1).astype(np.float32) / 255)


def _constrain_grass_before(res, samples, m):
    from skimage.color import rgb2lab, lab2rgb
    med = rgb2lab(E.lin_to_srgb(np.median(samples, 0))[None, None, :])[0, 0]
    sub = res[m]
    lab = rgb2lab(E.lin_to_srgb(sub)[None])[0]
    lab[:, 0] = np.clip(lab[:, 0], med[0] - 14, med[0] + 12)
    lab[:, 1] = np.clip(lab[:, 1], med[1] - 7, min(med[1] + 6, -6))   # stay green (a* negative)
    lab[:, 2] = np.clip(lab[:, 2], med[2] - 8, med[2] + 9)
    out = res.copy()
    out[m] = E.srgb_to_lin(lab2rgb(lab[None])[0])
    return out


def _blur_before(a, sigma):
    """Gaussian blur; large kernels run on a block-averaged pyramid level (much faster, same result to ~1%)."""
    if sigma <= 6:
        return ndimage.gaussian_filter(a, sigma)
    f = int(max(2, sigma // 3))
    H, W = a.shape
    Hp, Wp = -(-H // f) * f, -(-W // f) * f
    ap = np.pad(a, ((0, Hp - H), (0, Wp - W)), mode="edge")
    small = ap.reshape(Hp // f, f, Wp // f, f).mean((1, 3))
    small = ndimage.gaussian_filter(small, sigma / f)
    up = ndimage.zoom(small, f, order=1)[:H, :W]
    return up


def _season_grade_before(tint, stats, target_srgb):
    """Move a surface's median tint to target_srgb (0-255), keeping the photo's relative variation per channel."""
    tgt = E.srgb_to_lin(np.asarray(target_srgb, np.float32) / 255.0)
    k = (tgt / np.maximum(stats[0], 1e-4)).astype(np.float32)
    return tint * k, stats * k


def _tint_for_surface_before(s, gs, img, Y, openm, W, H, T):
    from rasterio.features import rasterize
    m = rasterize([(g, 1) for g in gs], out_shape=(H, W), transform=T, fill=0, dtype="uint8").astype(bool)
    if not m.any():
        return None, None
    r = E.C.DEM_RES
    base = m & openm
    num = _blur_before(Y * base, 4 / r); den = _blur_before(base.astype(np.float32), 4 / r)
    ref = np.where(den > 1e-3, num / np.maximum(den, 1e-6), np.nan)
    del num, den
    shadow = Y < 0.6 * np.nan_to_num(ref, nan=np.nanmedian(Y[base]) if base.any() else 0.1)
    del ref
    shadow = ndimage.binary_dilation(shadow, iterations=2)
    valid = base & ~shadow
    del shadow, base
    if valid.sum() < 50:
        valid = m.copy()
    sigma0 = E.MATS[s][6] / r
    res = np.zeros((H, W, 3), np.float32); filled = np.zeros((H, W), bool)
    near_m = ndimage.binary_dilation(m, iterations=3)
    vf = valid.astype(np.float32)
    for k, sg in enumerate((sigma0, sigma0 * 3, sigma0 * 10, sigma0 * 40, sigma0 * 160)):
        den = _blur_before(vf, sg)
        ok = (den > (0.25 if k == 0 else 0.02)) & ~filled & near_m
        if not ok.any():
            continue
        for c in range(3):
            num = _blur_before(img[..., c] * vf, sg)
            res[..., c][ok] = (num[ok] / den[ok])
        filled |= ok
    samples = img[valid]
    if not filled.all():
        res[~filled] = np.median(samples, 0)
    if s in E.GRASS:
        res = _constrain_grass_before(res, samples, m)
    stats = np.percentile(res[m], [50, 95], axis=0)
    print(f"tint {s}: valid {valid.sum()} px, median {np.round(E.lin_to_srgb(stats[0]) * 255).astype(int)}", flush=True)
    return res, stats


def _add_terrain_before(glb, root, feats_path=None):
    feats_path = feats_path or (E.C.FEATURES / "course_surfaces.geojson")
    d = np.load(E.C.BUILD / "terrain_mesh.npz")
    V, F, surf, hole = d["V"], d["F"], d["surf"], d["hole"]
    SURF = [str(x) for x in d["surfaces"]]
    N = E.vertex_normals(V, F)
    W, H, T = E.grid_arrays()
    img = _imagery_linear_before(W, H)
    Y = img @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    openm = E.open_mask(W, H)
    feats = [(shape(f["geometry"]), f["properties"]["surface"], f["properties"]["hole"]) for f in json.load(open(feats_path))["features"]]
    by_surface = {}
    for g, s_, h_ in feats:
        by_surface.setdefault(s_, []).append(g)
    xs = T.c + (np.arange(W) + 0.5) * T.a; ys = T.f + (np.arange(H) + 0.5) * T.e
    # 3DG grass density masks per vertex (COLOR_1 -> FBX colour layer 'Col'); see grass_spec.py
    import grass_spec
    with rasterio.open(E.C.BUILD / "chm.tif") as ds:
        chm = ndimage.gaussian_filter(ds.read(1).astype(np.float32), 2.0); chm_T = ds.transform
    dry = grass_spec.dryness_grid(img, 8)
    masks = grass_spec.vertex_masks(V, F, surf, SURF, chm, chm_T, dry, T * rasterio.Affine.scale(8))
    del chm, dry
    materials = {}
    groups = {}
    tint_cache = {}
    for si in np.unique(surf):
        sname = SURF[si]
        if sname not in E.MATS:
            continue
        opcd, alb, nrm, orm, tile, nscale, _ = E.MATS[sname]
        tsrc = E.TINT_FROM.get(sname, sname)
        if tsrc in tint_cache:
            tint, stats = tint_cache[tsrc]
        else:
            tint, stats = (_tint_for_surface_before(tsrc, by_surface.get(tsrc, []), img, Y, openm, W, H, T)
                           if tsrc in by_surface and sname not in E.NO_TINT else (None, None))
            if tint is not None and E.C.TURF_TINT and tsrc in E.C.TURF_TINT:
                tint, stats = _season_grade_before(tint, stats, E.C.TURF_TINT[tsrc])
            if tsrc in E.TINT_FROM.values():
                tint_cache[tsrc] = (tint, stats)
        if alb is not None:
            tm = E.mean_lin(alb)
            if stats is not None:
                # recolour the texture so its mean equals the surface's median photo colour (per channel), with
                # headroom so the brighter 95th-percentile areas still need COLOR_0 <= 1. COLOR_0 then stays close
                # to neutral and only carries brightness/hue variation: no false tints on thatch or dry blades.
                head = float(np.clip(np.max(stats[1] / np.maximum(stats[0], 1e-4)), 1.05, 1.8))
                gain = tuple(np.clip(stats[0] * head / tm, 0.05, 6.0))
            else:
                gain = 1.0
            key = (opcd, sname)
            if key not in materials:
                materials[key] = (glb.material(f"{opcd}", base_color=E.encode(alb, "albedo", gain), normal=E.encode(nrm, "normal"),
                                               orm=E.encode(orm, "orm"), normal_scale=nscale,
                                               specular=0.25 if sname in E.GRASS | {"bunkerlip"} else (0.6 if sname in ("bunker", "native") else None),
                                               extras={"surface": sname, "tile_m": tile}), tm * np.asarray(gain))
        else:
            key = (opcd, sname)
            # water: dark, slightly green-blue, glossy (vertex colour carries the photo's tint)
            materials[key] = (glb.material(opcd, base_factor=(0.18, 0.24, 0.22, 1.0), rough=0.06, metal=0.0,
                                           extras={"surface": sname}), np.array([0.18, 0.24, 0.22], np.float32))
        mat_index, tex_mean = materials[key]
        interp = [E.RegularGridInterpolator((ys[::-1], xs), tint[::-1, :, c], bounds_error=False, fill_value=None) for c in range(3)] if tint is not None else None
        for h in np.unique(hole[surf == si]):
            fsel = np.flatnonzero((surf == si) & (hole == h))
            vid, inv = np.unique(F[fsel], return_inverse=True)
            P = V[vid]
            if interp is not None:
                col = np.stack([f(np.c_[P[:, 1], P[:, 0]]) for f in interp], 1) / tex_mean
                col *= E.stripe_factor(P, sname, h)[:, None] / (1 + E.STRIPES.get(sname, (1, 0, 0))[1])
                col *= E.canopy_ao(P)[:, None] * E.SHADE.get(sname, 1.0)
                if sname in E.GRASS:
                    col *= E.turf_patches(P)
                elif sname == "bunker":
                    col *= E.sand_shade(N[vid, 2])[:, None] * E.turf_patches(P, amp=0.04)
                col = np.clip(col, 0, 1)
            else:
                col = np.ones((len(P), 3)) * (E.canopy_ao(P)[:, None] * 0.9 if sname in E.NO_TINT else 1.0)
            pos = E.to_model(P)
            nrm_m = np.c_[N[vid, 0], N[vid, 2], -N[vid, 1]]
            uv0 = np.c_[P[:, 0] / tile, -P[:, 1] / tile]
            uv0 -= np.floor(uv0.mean(0))  # keep numbers small
            name = f"Hole{int(h):02d}_{E.OBJECT.get(sname, opcd)}"
            col1 = masks[vid] if sname in grass_spec.GRASS3DG else np.zeros((len(vid), 3), np.float32)
            idx = inv.reshape(-1, 3)
            if int(h) == 99 and sname in E.TILED:
                cen = P[idx].mean(1)
                ti = ((cen[:, 0] - E.C.CORE["xmin"]) // E.C.TILE).astype(int); tj = ((cen[:, 1] - E.C.CORE["ymin"]) // E.C.TILE).astype(int)
                for key in sorted(set(zip(ti.tolist(), tj.tolist()))):
                    sel = (ti == key[0]) & (tj == key[1])
                    v2, inv2 = np.unique(idx[sel], return_inverse=True)
                    groups.setdefault(f"{name}_t{key[0]:02d}_{key[1]:02d}", []).append(dict(
                        pos=pos[v2], nrm=nrm_m[v2], uv0=uv0[v2], col=col[v2], col1=col1[v2], idx=inv2.reshape(-1, 3),
                        material=mat_index))
                continue
            groups.setdefault(name, []).append(dict(pos=pos, nrm=nrm_m, uv0=uv0, col=col, col1=col1,
                                                    idx=idx, material=mat_index))
        del tint, interp
    terrain = glb.node("Terrain", parent=root)
    for name in sorted(groups):
        m = glb.mesh(name, groups[name])
        glb.node(name, mesh=m, parent=terrain)
    print("terrain nodes", len(groups))
    E.add_water_planes(glb, terrain)


def _sample_before(path, X, Y):
    with rasterio.open(path) as ds:
        z = ds.read(1).astype(np.float64); T = ds.transform
    cols = (X - T.c) / T.a - 0.5; rows = (Y - T.f) / T.e - 0.5
    return ndimage.map_coordinates(np.nan_to_num(z, nan=np.nanmean(z)), [rows, cols], order=1, mode="nearest")


def _heightmap_before():
    TE, N, SIZE, OUT, SINK = G.TE, G.N, G.SIZE, G.OUT, G.SINK
    xs = TE["xmin"] + np.arange(N) * (TE["xmax"] - TE["xmin"]) / (N - 1)
    ys = TE["ymax"] - np.arange(N) * (TE["ymax"] - TE["ymin"]) / (N - 1)  # north row first
    X, Y = np.meshgrid(xs, ys)
    z = _sample_before(G.C.BUILD / "dem_final.tif", X, Y)
    e = G.C.CORE
    inside = (X > e["xmin"]) & (X < e["xmax"]) & (Y > e["ymin"]) & (Y < e["ymax"])
    if not inside.all() and (G.C.DATA / "dem/backdrop_dem.tif").exists():
        from build_backdrop import require_cover
        require_cover(G.C.DATA / "dem/backdrop_dem.tif", TE, "the GSPro terrain")
        zb = _sample_before(G.C.DATA / "dem/backdrop_dem.tif", X, Y)
        # feather over 25 m inside the build extent so the seam has no step
        d = np.minimum.reduce([X - e["xmin"], e["xmax"] - X, Y - e["ymin"], e["ymax"] - Y])
        w = np.clip(d / 25.0, 0, 1)
        z = w * z + (1 - w) * zb
    dd = np.minimum.reduce([X - e["xmin"], e["xmax"] - X, Y - e["ymin"], e["ymax"] - Y])
    z = z - SINK * np.clip(dd / 2.0, 0, 1)
    hmin, hmax = float(np.floor(z.min() - 1)), float(np.ceil(z.max() + 1))
    q = np.round((z - hmin) / (hmax - hmin) * 65535).astype("<u2")
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("heightmap_*"):
        old.unlink()
    q.tofile(OUT / f"heightmap_{N}.raw")
    Image.fromarray(q.astype(np.uint16)).save(OUT / f"heightmap_{N}.png")
    meta = {"heightmap": f"heightmap_{N}.raw", "resolution": N, "format": "RAW 16-bit unsigned, little-endian (Unity: Byte Order = Windows)",
            "row_order": "first row = NORTH edge (GIS north-up). In Unity's Import Raw dialog tick 'Flip Vertically' so north stays at +Z.",
            "terrain_size_m": {"width_x": SIZE, "length_z": TE["ymax"] - TE["ymin"], "height_y": hmax - hmin},
            "height_range_m": [hmin, hmax], "sample_spacing_m": SIZE / (N - 1),
            "crs": G.C.CRS_LABEL,
            "model_origin": [G.C.ORIGIN_E, G.C.ORIGIN_N, G.C.BASE_H],
            "unity_frame": {"x": "easting - %.1f" % TE["xmin"], "z": "northing - %.1f" % TE["ymin"], "y": "height - %.1f" % hmin},
            "utm_extent": TE, "build_extent_utm": G.C.CORE, "svg_document_mm": [SIZE, TE["ymax"] - TE["ymin"]],
            "overlay": "overlay_8192.jpg",
            "terrain_sunk_below_meshes_m": SINK}
    json.dump(meta, open(OUT / "terrain.json", "w"), indent=1)
    return hmin, hmax


def _paint_before(out, a, feather_px=48):
    m = a.max(-1) > 0
    if not m.any():
        return
    w = np.clip(ndimage.distance_transform_edt(m) / feather_px, 0, 1)[..., None]
    have = (out.max(-1) > 0)[..., None]
    w = np.where(have, w, m[..., None].astype(float))
    out[:] = np.clip(out * (1 - w) + a * w + 0.5, 0, 255).astype(np.uint8)


def _overlay_before(px=8192):
    TE, OUT = G.TE, G.OUT
    out = np.zeros((px, px, 3), np.uint8)
    from build_backdrop import NEAR_IMG
    for src in (NEAR_IMG.with_suffix(".tif"), G.C.IMAGERY):  # later sources paint over earlier ones
        if not src.exists():
            continue
        with rasterio.open(src) as ds:
            a = ds.read([1, 2, 3], window=from_bounds(TE["xmin"], TE["ymin"], TE["xmax"], TE["ymax"], transform=ds.transform),
                        out_shape=(3, px, px), resampling=Resampling.lanczos, boundless=True, fill_value=0)
        _paint_before(out, np.moveaxis(a, 0, -1))
    for old in OUT.glob("overlay_*.jpg"):
        old.unlink()
    Image.fromarray(out).save(OUT / "overlay_8192.jpg", quality=88)


def _outer_terrain_before(n=4097, px=8192):
    TE, OUT, OUTER_SINK = G.TE, G.OUT, G.OUTER_SINK
    oe = G.outer_extent()
    from build_backdrop import require_cover   # past the DEM's border sample() would repeat its edge heights
    require_cover(G.C.DATA / "dem/backdrop_dem.tif", oe, "the GSPro outer plot")
    xs = oe["xmin"] + np.arange(n) * (oe["xmax"] - oe["xmin"]) / (n - 1)
    ys = oe["ymax"] - np.arange(n) * (oe["ymax"] - oe["ymin"]) / (n - 1)
    X, Y = np.meshgrid(xs, ys)
    z = _sample_before(G.C.DATA / "dem/backdrop_dem.tif", X, Y)
    d_in = np.minimum.reduce([X - TE["xmin"], TE["xmax"] - X, Y - TE["ymin"], TE["ymax"] - Y])
    z = z - OUTER_SINK * np.clip(d_in / 10.0, 0, 1)
    hmin, hmax = float(np.floor(z.min() - 1)), float(np.ceil(z.max() + 1))
    q = np.round((z - hmin) / (hmax - hmin) * 65535).astype("<u2")
    q.tofile(OUT / f"outer_heightmap_{n}.raw")
    Image.fromarray(q.astype(np.uint16)).save(OUT / f"outer_heightmap_{n}.png")
    out = np.zeros((px, px, 3), np.uint8)
    from build_backdrop import NEAR_IMG, FAR_IMG, summer_tif
    # the summer-graded backdrop photos (build_backdrop.summer_grade) where built; finer sources on top
    for src in (*(summer_tif(p) if summer_tif(p).exists() else p.with_suffix(".tif") for p in (FAR_IMG, NEAR_IMG)), G.C.IMAGERY):
        if not src.exists():
            continue
        with rasterio.open(src) as ds:
            a = ds.read([1, 2, 3], window=from_bounds(oe["xmin"], oe["ymin"], oe["xmax"], oe["ymax"], transform=ds.transform),
                        out_shape=(3, px, px), resampling=Resampling.lanczos, boundless=True, fill_value=0)
        _paint_before(out, np.moveaxis(a, 0, -1))
    Image.fromarray(out).save(OUT / f"outer_overlay_{px}.jpg", quality=90)
    return {"heightmap": f"outer_heightmap_{n}.raw", "resolution": n, "overlay": f"outer_overlay_{px}.jpg",
            "terrain_size_m": {"width_x": oe["xmax"] - oe["xmin"], "length_z": oe["ymax"] - oe["ymin"], "height_y": hmax - hmin},
            "height_range_m": [hmin, hmax], "utm_extent": oe, "sunk_inside_inner_m": OUTER_SINK,
            "unity_position": {"x": oe["xmin"] - TE["xmin"], "z": oe["ymin"] - TE["ymin"], "y": hmin},
            "note": "OPCD 'Plot (Outer)': import like the inner terrain (16-bit, Windows byte order, Flip Vertically) and place "
                    "it at unity_position relative to the inner terrain's origin (y relative to the inner terrain's height base)."}


# ---- synthetic data

def _peak(f, *a, **k):
    """(result, peak bytes traced while f runs)."""
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        r = f(*a, **k)
        return r, tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()


class _Spy:
    """Wraps a function, recording size(argument `arg`) of each call (default: the first argument's length)."""
    def __init__(self, f, size=len, arg=0):
        self.f, self.size, self.arg, self.sizes = f, size, arg, []

    def __call__(self, *a, **k):
        self.sizes.append(self.size(a[self.arg]))
        return self.f(*a, **k)


def _photo(path, x0, y1, res, shape, seed, hole=None, crs=None):
    """A 3-band uint8 GeoTIFF: smooth colour fields plus noise; `hole` (x0, y0, x1, y1) is black (no data, as at the
    edges of a backdrop photo)."""
    rng = np.random.default_rng(seed)
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    a = np.stack([90 + 60 * np.sin(xx / (17 + 5 * b)) * np.cos(yy / (23 - 3 * b)) for b in range(3)])
    a = np.clip(a + rng.normal(0, 18, a.shape), 1, 255).astype(np.uint8)
    if hole is not None:
        c0, r0 = int((hole[0] - x0) / res), int((y1 - hole[3]) / res)
        c1, r1 = int((hole[2] - x0) / res), int((y1 - hole[1]) / res)
        a[:, max(r0, 0):max(r1, 0), max(c0, 0):max(c1, 0)] = 0
    with rasterio.open(path, "w", driver="GTiff", width=w, height=h, count=3, dtype="uint8", crs=crs or C.CRS,
                       transform=from_origin(x0, y1, res, res)) as d:
        d.write(a)


def _dem(path, x0, y1, res, z):
    with rasterio.open(path, "w", driver="GTiff", width=z.shape[1], height=z.shape[0], count=1, dtype="float32",
                       crs=C.CRS, transform=from_origin(x0, y1, res, res), nodata=np.nan) as d:
        d.write(z.astype(np.float32), 1)


def _relief(h, w, x0, y0, res, seed, base=300.0):
    rng = np.random.default_rng(seed)
    x = x0 + (np.arange(w) + 0.5) * res; y = y0 - (np.arange(h) + 0.5) * res
    X, Y = np.meshgrid(x, y)
    return base + 6 * np.sin(X / 37.0) + 4 * np.cos(Y / 53.0) + 0.02 * (X - x0) + rng.normal(0, 0.05, X.shape)


@pytest.fixture
def course(tmp_path, monkeypatch):
    """A small synthetic course for export_gspro: build extent 1000..1200, GSPro terrain 950..1250 (outer plot
    800..1400), a course DEM over the build extent with a few cells without data, a backdrop DEM over the outer plot,
    backdrop photos (near: summer-graded, with a black corner) and the course photo (a black strip)."""
    core = dict(xmin=1000.0, ymin=1000.0, xmax=1200.0, ymax=1200.0)
    te = dict(xmin=950.0, ymin=950.0, xmax=1250.0, ymax=1250.0)
    build, data = tmp_path / "build", tmp_path / "data"
    for d in (build, data / "dem", data / "imagery"):
        d.mkdir(parents=True)
    monkeypatch.setattr(G.C, "CORE", core); monkeypatch.setattr(G.C, "BUILD", build); monkeypatch.setattr(G.C, "DATA", data)
    monkeypatch.setattr(G, "TE", te); monkeypatch.setattr(G, "SIZE", 300.0); monkeypatch.setattr(G, "N", 257)
    monkeypatch.setattr(G, "OUT", tmp_path / "gspro")
    z = _relief(800, 800, 1000.0, 1200.0, 0.25, 1)
    z[400:403, 100:180] = np.nan
    _dem(build / "dem_final.tif", 1000.0, 1200.0, 0.25, z)
    _dem(data / "dem/backdrop_dem.tif", 780.0, 1420.0, 2.0, _relief(320, 320, 780.0, 1420.0, 2.0, 2, base=299.0))
    import build_backdrop as B
    near, far = data / "imagery/backdrop_near.jpg", data / "imagery/backdrop_far.jpg"
    monkeypatch.setattr(B, "NEAR_IMG", near); monkeypatch.setattr(B, "FAR_IMG", far)
    _photo(far.with_suffix(".tif"), 790.0, 1410.0, 2.0, (310, 310), 3)
    _photo(near.with_suffix(".tif"), 900.0, 1300.0, 1.0, (400, 400), 4, hole=(900, 1220, 980, 1300))
    _photo(B.summer_tif(near), 900.0, 1300.0, 1.0, (400, 400), 5, hole=(900, 1220, 980, 1300))
    img = data / "imagery/course_reg.tif"
    _photo(img, 1000.0, 1200.0, 0.5, (400, 400), 6, hole=(1100, 1000, 1110, 1200))
    monkeypatch.setattr(G.C, "IMAGERY", img)
    return tmp_path


def _files(d):
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


# ---- export_gspro.paint

def _layers(h, w, seed):
    """(out, a) pairs for paint: nothing painted yet; a layer over half the image with a ragged edge, a hole and
    single-pixel islands; a layer covering everything; an empty layer."""
    rng = np.random.default_rng(seed)
    a = rng.integers(1, 256, (h, w, 3), dtype=np.uint8)
    half = a.copy(); half[:, : w // 2 + 7] = 0
    half[h // 3: h // 3 + 9, -40:-20] = 0                          # a hole in the layer
    half[rng.integers(0, h, 50), rng.integers(0, w // 2, 50)] = 9  # islands
    out = np.zeros((h, w, 3), np.uint8)
    painted = rng.integers(1, 256, (h, w, 3), dtype=np.uint8); painted[: h // 4] = 0
    return [(out, a), (out, half), (painted, half), (painted, a), (painted, np.zeros_like(a))]


def test_paint_is_bit_for_bit_as_before(monkeypatch):
    monkeypatch.setattr(G, "PAINT_ROWS", 37, raising=False)   # several bands and a short last one
    for out, a in _layers(301, 233, 0):
        want = out.copy(); _paint_before(want, a, 48)
        got = out.copy(); G.paint(got, a, 48)
        assert np.array_equal(got, want)
        want = out.copy(); _paint_before(want, a, 5)
        got = out.copy(); G.paint(got, a, 5)
        assert np.array_equal(got, want)
    # the layout overlay() gives it: a channel-last view of rasterio's (3, h, w) read
    out, a = _layers(160, 190, 1)[2]
    planar = np.moveaxis(np.ascontiguousarray(np.moveaxis(a, -1, 0)), 0, -1)
    want = out.copy(); _paint_before(want, planar)
    got = out.copy(); G.paint(got, planar)
    assert np.array_equal(got, want)


def test_paint_holds_no_image_sized_float64_arrays():
    """Whistle Bear: painting the 8192 px course photo over the backdrop photo took the gspro step from 3.3 to 8.4 GB:
    the distance transform's float64 temporaries and the blend's full-image float64 arrays (out * (1 - w), a * w,
    their sum, the clip), 70+ bytes a pixel. Now the blend goes a band of rows at a time from the transform's
    indices (8 bytes a pixel)."""
    out, a = _layers(2048, 1024, 2)[2]
    got, peak = _peak(G.paint, out.copy(), a)
    per_px = peak / (2048 * 1024)
    assert per_px < 30, f"paint traced {per_px:.0f} bytes a pixel"


def test_paint_skips_the_distance_transform_on_an_empty_image(monkeypatch):
    """Where nothing is painted yet the layer is copied as it is (its weight is its mask): the first source needs no
    distance transform."""
    spy = _Spy(ndimage.distance_transform_edt)
    monkeypatch.setattr(ndimage, "distance_transform_edt", spy)
    out, a = _layers(120, 90, 3)[1]
    want = out.copy(); _paint_before(want, a)
    spy.sizes.clear()
    G.paint(out, a)
    assert np.array_equal(out, want) and spy.sizes == []


# ---- export_gspro.sample, heightmap, overlay, outer_terrain

def test_sample_is_bit_for_bit_as_before(course, monkeypatch):
    monkeypatch.setattr(G, "SAMPLE_ROWS", 7, raising=False)
    dem = course / "build/dem_final.tif"
    xs = np.linspace(990.0, 1210.0, 97); ys = np.linspace(1205.0, 995.0, 61)
    X, Y = np.meshgrid(xs, ys)
    want = _sample_before(dem, X, Y)
    assert np.array_equal(G.sample(dem, X, Y), want)
    assert np.array_equal(G.sample(dem, xs[None, :], ys[:, None]), want)   # a grid from its axes
    rng = np.random.default_rng(0)
    e, n = rng.uniform(995, 1205, 333), rng.uniform(995, 1205, 333)       # points (trees, rings)
    assert np.array_equal(G.sample(dem, e, n), _sample_before(dem, e, n))
    bd = course / "data/dem/backdrop_dem.tif"                              # no cell without data
    assert np.array_equal(G.sample(bd, xs[None, :], ys[:, None]), _sample_before(bd, X, Y))


def test_sample_reads_a_grid_a_band_of_rows_at_a_time(course, monkeypatch):
    """The heightmaps sample 4097^2 points: their coordinate grids (X, Y, rows, cols, the stacked pair) were 1.3 GB of
    float64 at once. A grid is now given by its axes and sampled SAMPLE_ROWS rows at a time."""
    spy = _Spy(ndimage.map_coordinates, size=lambda a: np.asarray(a).shape, arg=1)   # the coordinates
    monkeypatch.setattr(ndimage, "map_coordinates", spy)
    monkeypatch.setattr(G, "SAMPLE_ROWS", 16, raising=False)
    G.heightmap()
    assert spy.sizes and max(s[1] for s in spy.sizes) <= 16, spy.sizes[:3]


def test_heightmap_overlay_and_outer_plot_are_byte_for_byte_as_before(course, monkeypatch):
    monkeypatch.setattr(G, "PAINT_ROWS", 29, raising=False); monkeypatch.setattr(G, "SAMPLE_ROWS", 11, raising=False)
    monkeypatch.setattr(G, "OUT", course / "before")
    hb = _heightmap_before(); _overlay_before(px=300); ob = _outer_terrain_before(n=129, px=310)
    monkeypatch.setattr(G, "OUT", course / "after")
    ha = G.heightmap(); G.overlay(px=300); oa = G.outer_terrain(n=129, px=310)
    assert ha == hb and oa == ob
    before, after = _files(course / "before"), _files(course / "after")
    assert sorted(after) == sorted(before) == ["heightmap_257.png", "heightmap_257.raw", "outer_heightmap_129.png",
                                               "outer_heightmap_129.raw", "outer_overlay_310.jpg", "overlay_8192.jpg",
                                               "terrain.json"]
    for k in before:
        assert after[k] == before[k], k
    q = np.fromfile(course / "after/heightmap_257.raw", "<u2")
    assert q.min() < 10000 and q.max() > 55000 and len(np.unique(q)) > 1000  # not a flat or clipped heightmap


# ---- export_course.imagery_linear, constrain_grass, tint_for_surface

@pytest.fixture
def photo(tmp_path, monkeypatch):
    core = dict(xmin=1000.0, ymin=1000.0, xmax=1100.0, ymax=1075.0)
    img = tmp_path / "course_reg.tif"
    _photo(img, 990.0, 1085.0, 0.1, (1100, 1200), 7)
    monkeypatch.setattr(E.C, "CORE", core); monkeypatch.setattr(E.C, "IMAGERY", img)
    return 400, 300   # W, H at 0.25 m


def test_imagery_linear_is_bit_for_bit_as_before(photo, monkeypatch):
    """Same values and the same memory layout (a plane per channel): img @ weights (the luminance) and the turf
    statistics depend on the layout, not only on the values."""
    monkeypatch.setattr(E, "IMG_ROWS", 23, raising=False)
    want = _imagery_linear_before(*photo)
    got = E.imagery_linear(*photo)
    assert got.dtype == want.dtype and got.shape == want.shape and got.strides == want.strides
    assert np.array_equal(got, want)
    w = np.array([0.2126, 0.7152, 0.0722], np.float32)
    assert np.array_equal(got @ w, want @ w)


def test_imagery_linear_converts_a_band_of_rows_at_a_time(photo, monkeypatch):
    """Whistle Bear's 6144^2 photo (453 MB as linear float32) took about 1.6 GB more to convert: four image-sized
    float32 temporaries of the sRGB curve. Now a band of rows at a time."""
    W, H = photo
    monkeypatch.setattr(E, "IMG_ROWS", 16, raising=False)          # bands of 16 of the test photo's 300 rows
    img, peak = _peak(E.imagery_linear, W, H)
    assert peak < 2.0 * img.nbytes, f"imagery_linear traced {peak / img.nbytes:.1f} x its result"


def _turf(h=300, w=420, seed=0):
    """A linear-colour tint map with grass, sand and path colours, and a turf mask over most of it."""
    rng = np.random.default_rng(seed)
    res = rng.uniform(0.02, 0.25, (h, w, 3)).astype(np.float32)
    res[..., 1] *= 1.3
    res[h // 2:, : w // 3] = np.float32([0.45, 0.40, 0.30])       # sand / path leaking into the photo statistics
    m = np.ones((h, w), bool); m[: h // 5] = False; m[rng.random((h, w)) < 0.05] = False
    samples = res[m][::3]
    return res, samples, m


def test_constrain_grass_is_bit_for_bit_as_before(monkeypatch):
    """The colour conversions go a chunk of LAB_CHUNK pixels at a time, the last chunk taking the remainder: the
    matrix products in skimage give other bits for rows a BLAS call leaves over (Accelerate: an odd row at the end
    of a call), so chunks start at whole multiples of LAB_CHUNK and no call is shorter than one."""
    res, samples, m = _turf()
    want = _constrain_grass_before(res, samples, m)
    for chunk in (4096, 1 << 20):                                  # many chunks with a remainder; one chunk
        monkeypatch.setattr(E, "LAB_CHUNK", chunk, raising=False)
        got = E.constrain_grass(res.copy(), samples, m)
        assert got.dtype == want.dtype and np.array_equal(got, want), chunk


def test_constrain_grass_converts_a_chunk_at_a_time(monkeypatch):
    """Whistle Bear's rough (20 M pixels) took the export step from 3.7 to 6.9 GB: the Lab round trip of every turf
    pixel at once (a dozen float32 copies) and a copy of the whole tint map."""
    import skimage.color
    res, samples, m = _turf()
    monkeypatch.setattr(E, "LAB_CHUNK", 4096, raising=False)
    spy = _Spy(skimage.color.rgb2lab, size=lambda a: np.asarray(a).shape[-2])
    monkeypatch.setattr(skimage.color, "rgb2lab", spy)
    E.constrain_grass(res, samples, m)
    assert max(spy.sizes[1:]) < 2 * 4096, spy.sizes                   # the first call is the median's (1 pixel)
    monkeypatch.setattr(skimage.color, "rgb2lab", spy.f)
    _, peak = _peak(E.constrain_grass, res, samples, m)
    assert peak < 2.0 * res.nbytes, f"constrain_grass traced {peak / res.nbytes:.1f} x the tint map"


def test_tint_for_surface_is_bit_for_bit_as_before(monkeypatch):
    monkeypatch.setattr(E, "LAB_CHUNK", 8192, raising=False)
    monkeypatch.setattr(E.C, "DEM_RES", 0.25)
    rng = np.random.default_rng(5)
    H, W = 360, 400
    T = from_origin(1000.0, 1090.0, 0.25, 0.25)
    img = rng.uniform(0.01, 0.3, (H, W, 3)).astype(np.float32)
    img = np.moveaxis(np.ascontiguousarray(np.moveaxis(img, -1, 0)), 0, -1)   # imagery_linear's layout
    img[100:140, 60:200] *= 0.3                                               # a cast shadow
    Y = img @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    openm = np.ones((H, W), bool); openm[200:260, 250:330] = False             # a tree crown
    gs = [box(1010, 1010, 1080, 1060).difference(Point(1050, 1040).buffer(8)), Point(1090, 1080).buffer(6)]
    for s in ("rough", "fairway", "bunker"):
        want = _tint_for_surface_before(s, gs, img, Y, openm, W, H, T)
        got = E.tint_for_surface(s, gs, img, Y, openm, W, H, T)
        assert np.array_equal(got[0], want[0]) and np.array_equal(got[1], want[1]), s
    assert E.tint_for_surface("green", [box(2000, 2000, 2010, 2010)], img, Y, openm, W, H, T) == (None, None)


def test_blur_is_bit_for_bit_as_before():
    """The pyramid level is now block-averaged in place when the image divides into whole blocks (no padded copy)."""
    rng = np.random.default_rng(3)
    for shape in ((384, 512), (377, 509), (256, 256)):
        a = rng.random(shape, dtype=np.float32)
        for sigma in (1.2, 6.0, 7.2, 16.0, 24.0, 96.0, 384.0):
            assert np.array_equal(E.blur(a, sigma), _blur_before(a, sigma)), (shape, sigma)
    b = (rng.random((384, 512)) > 0.5).astype(np.float32)
    assert np.array_equal(E.blur(b, 16.0), _blur_before(b, 16.0))


def test_blur_makes_no_padded_copy_of_an_image_of_whole_blocks():
    a = np.random.default_rng(4).random((1024, 1536), dtype=np.float32)   # whole blocks of 2, 8, 32, 128 px
    for sigma in (7.2, 24.0, 96.0, 384.0):
        _, peak = _peak(E.blur, a, sigma)
        assert peak < 1.6 * a.nbytes, (sigma, peak / a.nbytes)            # the result (no padding) and the small level


def test_season_grade_can_grade_in_place():
    rng = np.random.default_rng(6)
    tint = rng.uniform(0.04, 0.2, (40, 50, 3)).astype(np.float32)
    stats = np.percentile(tint.reshape(-1, 3), [50, 95], axis=0)
    want = _season_grade_before(tint, stats, (86, 128, 54))
    got = E.season_grade(tint.copy(), stats, (86, 128, 54))
    assert np.array_equal(got[0], want[0]) and np.array_equal(got[1], want[1])
    t = tint.copy()
    got = E.season_grade(t, stats, (86, 128, 54), out=t)
    assert got[0] is t and np.array_equal(t, want[0]) and np.array_equal(got[1], want[1])


def test_tint_for_surface_picks_pixels_without_index_arrays(monkeypatch):
    """A 2-D mask on an (H, W, 3) array (img[valid], res[m], res[~filled] = ...) makes numpy build two int64 index
    arrays first, 16 bytes per selected pixel: on Whistle Bear's 6144^2 grid filling a small surface's tint map
    (res[~filled], 37 M pixels) was the export step's live peak, 0.6 GB of indices. Pixels are now picked and set a
    channel at a time. Here the indices took the peak to 3.85 x the tint map; the blur loop's grids are 3.1 x."""
    monkeypatch.setattr(E.C, "DEM_RES", 0.25)
    H, W = 1024, 1024
    T = from_origin(1000.0, 1256.0, 0.25, 0.25)
    rng = np.random.default_rng(7)
    img = np.moveaxis(rng.uniform(0.01, 0.3, (3, H, W)).astype(np.float32), 0, -1)
    Y = img @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    (res, _), peak = _peak(E.tint_for_surface, "semirough", [Point(1100, 1100).buffer(10)], img, Y, np.ones((H, W), bool),
                           W, H, T)
    assert peak < 3.5 * res.nbytes, f"tint_for_surface traced {peak / res.nbytes:.2f} x the tint map"


def test_pick_and_put_are_mask_indexing_without_index_arrays():
    rng = np.random.default_rng(8)
    planar = np.moveaxis(rng.random((3, 700, 900), dtype=np.float32), 0, -1)
    packed = np.ascontiguousarray(planar)
    m = rng.random((700, 900)) < 0.7
    for a in (planar, packed):
        got, peak = _peak(E.pick, a, m)
        assert np.array_equal(got, a[m]) and got.flags.c_contiguous and got.dtype == a.dtype
        assert peak < 1.5 * got.nbytes, peak / got.nbytes           # a[m] traced 2.3 x (its int64 indices)
        b = a.copy(); want = a.copy(); v = rng.random((m.sum(), 3), dtype=np.float32)
        want[m] = v; E.put(b, m, v)
        assert np.array_equal(b, want)


# ---- export_course.add_terrain (a small synthetic course)

@pytest.fixture
def terrain(tmp_path, monkeypatch):
    """A 64 x 48 m course for add_terrain: a 1 m triangle mesh labelled rough, semirough, fairway, green, two bunkers
    with their lips (holes 1 and 2) and a pond; the course photo, a canopy height model with one tree, surface polygons,
    small textures (re-encoded at 2048 px as on a course), hole lines for the mowing stripes and a season grade."""
    core = dict(xmin=1000.0, ymin=1000.0, xmax=1064.0, ymax=1048.0)
    build = tmp_path / "build"; build.mkdir()
    for k, v in (("CORE", core), ("BUILD", build), ("DEM_RES", 0.25), ("TILE", 32.0),
                 ("TURF_TINT", {"rough": (95, 125, 60), "fairway": (80, 120, 55)})):
        monkeypatch.setattr(E.C, k, v)
    monkeypatch.setattr(E, "CACHE", tmp_path / "tex_cache"); monkeypatch.setattr(E, "_AO", None)
    monkeypatch.setattr(E, "_HOLE_LINES", {1: np.array([[1004.0, 1024.0], [1048.0, 1028.0]]),
                                           2: np.array([[1040.0, 1044.0], [1060.0, 1030.0]])})
    green, b1, b2, pond = Point(1022, 1024).buffer(6), Point(1036, 1030).buffer(3), Point(1052, 1038).buffer(2.5), Point(1056, 1010).buffer(4)
    lip1, lip2 = b1.buffer(1.0).difference(b1), b2.buffer(1.0).difference(b2)
    fairway = box(1004, 1012, 1046, 1036).difference(green).difference(b1.buffer(1.0))
    semi = box(1002, 1008, 1048, 1040).difference(box(1004, 1012, 1046, 1036))
    feats = [(box(1000, 1000, 1064, 1048), "rough", 99), (semi, "semirough", 99), (fairway, "fairway", 1), (green, "green", 1),
             (b1, "bunker", 1), (b2, "bunker", 2), (pond, "water", 99)]
    names = ["rough", "semirough", "fairway", "green", "bunker", "water", "bunkerlip"]
    xs, ys = np.meshgrid(np.arange(1000.0, 1064.5, 1.0), np.arange(1000.0, 1048.5, 1.0))
    V = np.c_[xs.ravel(), ys.ravel(), (300 + 0.05 * (xs - 1000) + np.sin(ys / 5.0)).ravel()]
    nx = xs.shape[1]
    q = (np.arange(48)[:, None] * nx + np.arange(64)[None, :]).ravel()
    F = np.r_[np.c_[q, q + 1, q + nx + 1], np.c_[q, q + nx + 1, q + nx]].astype(np.int32)
    cen = V[F].mean(1)
    surf = np.zeros(len(F), np.int16); hole = np.full(len(F), 99, np.int16)
    import shapely
    pts = shapely.points(cen[:, :2])
    for g, s_, h_ in feats[1:] + [(lip1, "bunkerlip", 1), (lip2, "bunkerlip", 2)]:
        inside = shapely.contains(g, pts)
        surf[inside] = names.index(s_); hole[inside] = h_
    np.savez(build / "terrain_mesh.npz", V=V, F=F, surf=surf, hole=hole, surfaces=np.array(names))
    chm = np.zeros((96, 128), np.float32); yy, xx = np.mgrid[0:96, 0:128]
    chm[(yy - 30) ** 2 + (xx - 90) ** 2 < 64] = 9.0
    _dem(build / "chm.tif", 1000.0, 1048.0, 0.5, chm)
    _photo(tmp_path / "course_reg.tif", 995.0, 1053.0, 0.1, (580, 740), 9)
    monkeypatch.setattr(E.C, "IMAGERY", tmp_path / "course_reg.tif")
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": mapping(g),
                                                      "properties": {"surface": s_, "hole": h_}} for g, s_, h_ in feats]}
    (tmp_path / "course_surfaces.geojson").write_text(json.dumps(fc))
    tex = tmp_path / "tex"
    mats = {}
    rng = np.random.default_rng(10)
    for s_ in names:
        d = tex / s_; d.mkdir(parents=True)
        for f_ in ("albedo.jpg", "normal.png", "orm.jpg"):
            Image.fromarray(rng.integers(40, 220, (32, 32, 3), dtype=np.uint8)).save(d / f_)
        m = E.MATS[s_]
        mats[s_] = (m[0], d / "albedo.jpg", d / "normal.png", d / "orm.jpg") + tuple(m[4:])
    monkeypatch.setattr(E, "MATS", mats)
    return tmp_path / "course_surfaces.geojson"


def _terrain_glb(add, feats, path):
    E._AO = None
    glb = GLB()
    add(glb, glb.node("Course"), feats)
    glb.save(path)
    return path.read_bytes()


def test_add_terrain_is_byte_for_byte_as_before(terrain, monkeypatch):
    monkeypatch.setattr(E, "LAB_CHUNK", 4096, raising=False); monkeypatch.setattr(E, "IMG_ROWS", 37, raising=False)
    want = _terrain_glb(_add_terrain_before, terrain, terrain.parent / "before.glb")
    got = _terrain_glb(E.add_terrain, terrain, terrain.parent / "after.glb")
    assert len(want) > 1e6 and got == want
    js = json.loads(want[20:20 + int.from_bytes(want[12:16], "little")])
    nodes = {n["name"] for n in js["nodes"]}
    assert {"Hole01_Bunker_Lip", "Hole02_Bunker_Lip", "Hole01_Green", "Hole99_Water_Base"} <= nodes
    assert any(n.startswith("Hole99_Rough_t") for n in nodes)


def test_add_terrain_keeps_no_tint_map_for_the_bunker_lips(terrain, monkeypatch):
    """The bunker lips take the rough's photo colour (TINT_FROM): the whole rough tint map (453 MB on Whistle Bear,
    616 MB on Brambles) was kept through every later surface. The lip vertices are now sampled when the rough tint is
    made; the map is freed before the next surface's tint."""
    made = []   # weak references to every tint map made (and graded)
    def spy(f):
        def g(*a, **k):
            if f is tint_for_surface:
                assert all(r() is None for r in made), "an earlier surface's tint map is still alive"
            res = f(*a, **k)
            if res[0] is not None:
                made.append(weakref.ref(res[0]))
            return res
        return g
    tint_for_surface, season_grade = E.tint_for_surface, E.season_grade
    monkeypatch.setattr(E, "tint_for_surface", spy(tint_for_surface)); monkeypatch.setattr(E, "season_grade", spy(season_grade))
    E._AO = None
    glb = GLB()
    E.add_terrain(glb, glb.node("Course"), terrain)
    assert len(made) >= 4
