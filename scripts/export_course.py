"""Export the course model (terrain surfaces, later vegetation + structures) to glTF binary.

Terrain shading: tiled PBR detail textures per surface, multiplied by per-vertex colour (COLOR_0) derived from the
aerial imagery (tree canopy and cast shadows are masked out and in-filled from surrounding open turf).
Node names follow OPCD/GSPro conventions (Hole01_Fairway, Hole99_Rough, Hole98_Concrete ...).
"""
import sys, io, json
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import from_bounds
from rasterio.features import rasterize
from scipy import ndimage
from scipy.interpolate import RegularGridInterpolator
from shapely.geometry import shape
from PIL import Image

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C
from gltf_builder import GLB

GEN = C.DATA / "textures_gen"; PH = C.DATA / "textures"
_GROUND = C.REGION["materials"]   # wooded-rough and native ground textures (regions/<region>.toml [materials])
# surface -> OPCD material name, albedo, normal, orm, tile size (m), normal scale, tint blur (m)
MATS = {
    "green":     ("Green",       GEN / "green/albedo.jpg",     GEN / "green/normal.png",     GEN / "green/orm.jpg",     1.0, 0.6, 0.30),
    "fringe":    ("GreenFringe", GEN / "fringe/albedo.jpg",    GEN / "fringe/normal.png",    GEN / "fringe/orm.jpg",    1.2, 0.7, 0.35),
    "fairway":   ("Fairway",     GEN / "fairway/albedo.jpg",   GEN / "fairway/normal.png",   GEN / "fairway/orm.jpg",   1.5, 0.8, 0.40),
    "tee":       ("Tee",         GEN / "tee/albedo.jpg",       GEN / "tee/normal.png",       GEN / "tee/orm.jpg",       1.5, 0.8, 0.40),
    "semirough": ("SemiRough",   GEN / "semirough/albedo.jpg", GEN / "semirough/normal.png", GEN / "semirough/orm.jpg", 2.0, 0.7, 0.50),
    "rough":     ("Rough",       GEN / "rough/albedo.jpg",     GEN / "rough/normal.png",     GEN / "rough/orm.jpg",     2.5, 0.65, 0.60),
    "bunker":    ("Bunker",      PH / "sand_01/diffuse.jpg",   PH / "sand_01/nor_gl.jpg",    PH / "sand_01/arm.jpg",    2.5, 1.0, 0.35),
    "deeprough": ("DeepRough",   PH / f"{_GROUND['deeprough']}/diffuse.jpg", PH / f"{_GROUND['deeprough']}/nor_gl.jpg", PH / f"{_GROUND['deeprough']}/arm.jpg", 3.0, 1.0, 0.6),
    "native":    ("Pinestraw",   PH / f"{_GROUND['native']}/diffuse.jpg", PH / f"{_GROUND['native']}/nor_gl.jpg", PH / f"{_GROUND['native']}/arm.jpg", 3.0, 1.0, 0.6),
    "cartpath":  ("Concrete",    PH / "concrete_floor_worn_001/diffuse.jpg", PH / "concrete_floor_worn_001/nor_gl.jpg", PH / "concrete_floor_worn_001/arm.jpg", 4.0, 0.6, 0.4),
    "road":      ("Road",        PH / "asphalt_02/diffuse.jpg", PH / "asphalt_02/nor_gl.jpg", PH / "asphalt_02/arm.jpg", 6.0, 0.8, 0.6),
    "building":  ("Building_Base", PH / "concrete_floor_worn_001/diffuse.jpg", PH / "concrete_floor_worn_001/nor_gl.jpg", PH / "concrete_floor_worn_001/arm.jpg", 4.0, 0.6, 0.6),
    "court":     ("Court",       PH / "concrete_floor_worn_001/diffuse.jpg", PH / "concrete_floor_worn_001/nor_gl.jpg", PH / "concrete_floor_worn_001/arm.jpg", 6.0, 0.3, 0.3),
    # the pond bed under the WaterPlane (OPCD Water_Base) and its 0.15 m edge band (Water_Edge, 2nd material slot)
    "water":     ("Water_Base",  PH / "brown_mud_leaves_01/diffuse.jpg", PH / "brown_mud_leaves_01/nor_gl.jpg", PH / "brown_mud_leaves_01/arm.jpg", 3.0, 1.0, 0.5),
    "wateredge": ("Water_Edge",  PH / "dry_ground_01/diffuse.jpg", PH / "dry_ground_01/nor_gl.jpg", PH / "dry_ground_01/arm.jpg", 2.0, 1.0, 0.5),
    # OPCD Bunker_Lip: the turf edge of the bunker (photo colour of the surrounding rough, shaded)
    "bunkerlip": ("Bunker_Lip",  GEN / "rough/albedo.jpg",     GEN / "rough/normal.png",     GEN / "rough/orm.jpg",     2.5, 0.9, 0.60),
}
# OPCD object name for a surface, when it differs from "<Hole>_<material>": the water edge band is the 2nd material
# slot of the Water_Base object (SetMeshMaterial.cs assigns sharedMaterials [Water_Base, Water_Edge]); every object
# name carries exactly one SetMeshMaterial token (roads -> concrete physics, courts -> Custom1, ground under
# buildings -> concrete)
OBJECT = {"wateredge": "Water_Base", "road": "Concrete_Road", "court": "Custom1_Court", "building": "Concrete_Building"}
# course-wide (Hole99) grass surfaces are split into TILE x TILE m pieces: a single 900k-vertex Hole99_Rough is a
# MeshCollider / 3DG cost and is never culled (research/GSPRO_COSMETICS.md 3.1)
TILED = ("rough", "semirough", "deeprough", "native")
TINT_FROM = {"bunkerlip": "rough"}   # photo colour source for surfaces with no polygons of their own
SHADE = {"bunkerlip": 0.82}          # vertex-colour multiplier (the lip face is in shadow)
TEX_SIZE = 2048
CACHE = C.BUILD / "tex_cache"


def srgb_to_lin(c):
    c = np.asarray(c, np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def encode(path, kind, gain=None, size=TEX_SIZE):
    """Re-encode a texture for embedding (JPEG). Albedo may be brightness-calibrated by `gain` (linear)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    stamp = int(path.stat().st_mtime)  # source changes invalidate the cached encode
    gtag = "" if gain is None else "-".join("%.3f" % g for g in np.atleast_1d(gain))
    key = CACHE / f"{path.parent.name}_{path.stem}_{kind}_{size}_{gtag}_{stamp}.jpg"
    if not key.exists():
        im = Image.open(path).convert("RGB")
        if im.size != (size, size):
            im = im.resize((size, size), Image.LANCZOS)
        if gain is not None and np.any(np.abs(np.atleast_1d(gain) - 1) > 1e-3):
            a = srgb_to_lin(np.asarray(im, np.float32) / 255) * np.asarray(gain, np.float32)
            im = Image.fromarray((lin_to_srgb(a) * 255 + 0.5).astype(np.uint8))
        im.save(key, quality=90 if kind != "albedo" else 88)
    return str(key)


def mean_lin(path):
    a = srgb_to_lin(np.asarray(Image.open(path).convert("RGB").resize((256, 256), Image.BOX), np.float32) / 255)
    return a.reshape(-1, 3).mean(0)


def grid_arrays():
    e = C.CORE; r = C.DEM_RES
    W = int(round((e["xmax"] - e["xmin"]) / r)); H = int(round((e["ymax"] - e["ymin"]) / r))
    T = rasterio.transform.from_origin(e["xmin"], e["ymax"], r, r)
    return W, H, T


def imagery_linear(W, H):
    e = C.CORE
    with rasterio.open(C.IMAGERY) as ds:
        a = ds.read([1, 2, 3], window=from_bounds(e["xmin"], e["ymin"], e["xmax"], e["ymax"], transform=ds.transform),
                    out_shape=(3, H, W), resampling=Resampling.average)
    return srgb_to_lin(np.moveaxis(a, 0, -1).astype(np.float32) / 255)


def open_mask(W, H):
    chm = rasterio.open(C.BUILD / "chm.tif").read(1)
    chm = np.kron(chm, np.ones((2, 2), np.float32))[:H, :W]
    canopy = ndimage.binary_dilation(ndimage.gaussian_filter(chm, 0.8) > 1.2, iterations=3)
    return ~canopy


def blur(a, sigma):
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


GRASS = {"green", "fringe", "fairway", "tee", "semirough", "rough"}
NO_TINT = {"water", "wateredge"}  # keep their texture colour (the photo shows the water surface, not the bed)


def constrain_grass(res, samples, m):
    """Keep turf tints inside a plausible grass gamut around the surface's median colour (Lab), so paths, dirt,
    shadows or sand that leak into the photo statistics cannot turn turf grey/pink."""
    from skimage.color import rgb2lab, lab2rgb
    med = rgb2lab(lin_to_srgb(np.median(samples, 0))[None, None, :])[0, 0]
    sub = res[m]
    lab = rgb2lab(lin_to_srgb(sub)[None])[0]
    lab[:, 0] = np.clip(lab[:, 0], med[0] - 14, med[0] + 12)
    lab[:, 1] = np.clip(lab[:, 1], med[1] - 7, min(med[1] + 6, -6))   # stay green (a* negative)
    lab[:, 2] = np.clip(lab[:, 2], med[2] - 8, med[2] + 9)
    out = res.copy()
    out[m] = srgb_to_lin(lab2rgb(lab[None])[0])
    return out


def tint_for_surface(s, gs, img, Y, openm, W, H, T):
    """Linear colour map for one surface (shadow/canopy in-filled from surrounding open turf) + (median, p95) stats."""
    m = rasterize([(g, 1) for g in gs], out_shape=(H, W), transform=T, fill=0, dtype="uint8").astype(bool)
    if not m.any():
        return None, None
    r = C.DEM_RES
    base = m & openm
    num = blur(Y * base, 4 / r); den = blur(base.astype(np.float32), 4 / r)
    ref = np.where(den > 1e-3, num / np.maximum(den, 1e-6), np.nan)
    del num, den
    shadow = Y < 0.6 * np.nan_to_num(ref, nan=np.nanmedian(Y[base]) if base.any() else 0.1)
    del ref
    shadow = ndimage.binary_dilation(shadow, iterations=2)
    valid = base & ~shadow
    del shadow, base
    if valid.sum() < 50:
        valid = m.copy()
    sigma0 = MATS[s][6] / r
    res = np.zeros((H, W, 3), np.float32); filled = np.zeros((H, W), bool)
    near_m = ndimage.binary_dilation(m, iterations=3)
    vf = valid.astype(np.float32)
    for k, sg in enumerate((sigma0, sigma0 * 3, sigma0 * 10, sigma0 * 40, sigma0 * 160)):
        den = blur(vf, sg)
        ok = (den > (0.25 if k == 0 else 0.02)) & ~filled & near_m
        if not ok.any():
            continue
        for c in range(3):
            num = blur(img[..., c] * vf, sg)
            res[..., c][ok] = (num[ok] / den[ok])
        filled |= ok
    samples = img[valid]
    if not filled.all():
        res[~filled] = np.median(samples, 0)
    if s in GRASS:
        res = constrain_grass(res, samples, m)
    stats = np.percentile(res[m], [50, 95], axis=0)
    print(f"tint {s}: valid {valid.sum()} px, median {np.round(lin_to_srgb(stats[0]) * 255).astype(int)}", flush=True)
    return res, stats


def season_grade(tint, stats, target_srgb):
    """Move a surface's median tint to target_srgb (0-255), keeping the photo's relative variation per channel."""
    tgt = srgb_to_lin(np.asarray(target_srgb, np.float32) / 255.0)
    k = (tgt / np.maximum(stats[0], 1e-4)).astype(np.float32)
    return tint * k, stats * k


STRIPES = {  # surface: (stripe width m, contrast, cross-cut contrast)
    "fairway": (4.2, 0.12, 0.0), "tee": (1.6, 0.07, 0.0), "green": (0.85, 0.06, 0.03), "semirough": (2.4, 0.03, 0.0)}
_HOLE_LINES = None


def hole_lines():
    """Course hole number -> line of play (holes.json centre lines where available, else the OSM hole line)."""
    global _HOLE_LINES
    if _HOLE_LINES is None:
        from surface_classify import osm_geoms
        _HOLE_LINES = {C.course_hole(t["ref"]): np.asarray(g.coords) for _, t, g in osm_geoms()
                       if t.get("golf") == "hole" and t.get("ref") and g.geom_type == "LineString"}
        try:
            for h in json.load(open(C.OUTPUT / "holes.json"))["holes"]:
                if h.get("centerline_utm"):
                    _HOLE_LINES[h["hole"]] = np.asarray(h["centerline_utm"], float)
        except FileNotFoundError:
            pass
    return _HOLE_LINES


def stripe_factor(P, surface, hole):
    """Mowing stripes along the line of play: alternating light/dark passes (+ optional cross-cut)."""
    if surface not in STRIPES:
        return np.ones(len(P))
    lines = hole_lines()
    line = lines.get(int(hole))
    if line is None:
        return np.ones(len(P))
    w, c, cc = STRIPES[surface]
    xy = P[:, :2]
    best = np.full(len(P), np.inf); u = np.zeros(len(P)); v = np.zeros(len(P))
    for a, b in zip(line[:-1], line[1:]):
        d = (b - a) / np.linalg.norm(b - a); nrm = np.array([-d[1], d[0]])
        t = np.clip((xy - a) @ d, 0, np.linalg.norm(b - a))
        dist = np.linalg.norm(xy - (a + t[:, None] * d), axis=1)
        sel = dist < best
        best[sel] = dist[sel]; u[sel] = ((xy - a) @ nrm)[sel]; v[sel] = ((xy - a) @ d)[sel]
    s1 = np.tanh(2.5 * np.sin(np.pi * u / w))
    f = 1 + c * s1
    if cc:
        f *= 1 + cc * np.tanh(2.5 * np.sin(np.pi * v / w))
    return f


_AO = None


PATCH_WAVES = None


def turf_patches(P, amp=0.06):
    """Moisture / wear patches on turf: a smooth random field (plane waves of 24-55 m wavelength in random directions,
    fixed seed so every build agrees) as a per-vertex colour factor (n, 3). Brightness varies about +/- amp; brighter
    patches are a little yellower, darker ones a little bluer, like drier and lusher grass."""
    global PATCH_WAVES
    if PATCH_WAVES is None:
        rng = np.random.default_rng(1931)
        lam = np.repeat([24.0, 36.0, 55.0], 6)
        th = rng.uniform(0, np.pi, len(lam))
        PATCH_WAVES = (np.c_[np.cos(th), np.sin(th)] * (2 * np.pi / lam)[:, None], rng.uniform(0, 2 * np.pi, len(lam)))
    k, ph = PATCH_WAVES
    n = np.sin(P[:, :2] @ k.T + ph).sum(1) / np.sqrt(len(ph) / 2)      # ~ unit variance
    t = np.clip(n, -2.5, 2.5)
    lum = 1 + amp * t
    return lum[:, None] * (1 + np.outer(t, [0.02, 0.008, -0.04]))


def sand_shade(nz, depth=0.2):
    """Vertex-colour factor for bunker sand from the surface normal's vertical component: steep faces (compacted,
    raked less, often in their own shade) up to `depth` darker than the floor, rising smoothly to ~40 degrees."""
    x = np.clip((1 - np.asarray(nz, float)) / 0.25, 0, 1)
    return 1 - depth * x * x * (3 - 2 * x)


def canopy_ao(P):
    """Sky-occlusion under/near tree crowns (direct shadows are rendered live; this is the ambient part)."""
    global _AO
    if _AO is None:
        with rasterio.open(C.BUILD / "chm.tif") as ds:
            chm = ds.read(1); T = ds.transform
        cover = np.clip((chm - 1.5) / 4.0, 0, 1)            # 0 open sky .. 1 under a full crown
        occ = 0.65 * ndimage.gaussian_filter(cover, 1.5 / T.a) + 0.35 * ndimage.gaussian_filter(cover, 5.0 / T.a)
        _AO = (1 - 0.32 * np.clip(occ, 0, 1), T)
    ao, T = _AO
    c = (P[:, 0] - T.c) / T.a - 0.5; r = (P[:, 1] - T.f) / T.e - 0.5
    return ndimage.map_coordinates(ao, [r, c], order=1, mode="nearest")


def vertex_normals(V, F):
    n = np.zeros_like(V)
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    for k in range(3):
        np.add.at(n, F[:, k], fn)
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    return n


def to_model(P):
    return np.c_[P[:, 0] - C.ORIGIN_E, P[:, 2] - C.BASE_H, -(P[:, 1] - C.ORIGIN_N)]


def add_terrain(glb, root, feats_path=None):
    feats_path = feats_path or (C.FEATURES / "course_surfaces.geojson")
    d = np.load(C.BUILD / "terrain_mesh.npz")
    V, F, surf, hole = d["V"], d["F"], d["surf"], d["hole"]
    SURF = [str(x) for x in d["surfaces"]]
    N = vertex_normals(V, F)
    W, H, T = grid_arrays()
    img = imagery_linear(W, H)
    Y = img @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    openm = open_mask(W, H)
    feats = [(shape(f["geometry"]), f["properties"]["surface"], f["properties"]["hole"]) for f in json.load(open(feats_path))["features"]]
    by_surface = {}
    for g, s_, h_ in feats:
        by_surface.setdefault(s_, []).append(g)
    xs = T.c + (np.arange(W) + 0.5) * T.a; ys = T.f + (np.arange(H) + 0.5) * T.e
    # 3DG grass density masks per vertex (COLOR_1 -> FBX colour layer 'Col'); see grass_spec.py
    import grass_spec
    with rasterio.open(C.BUILD / "chm.tif") as ds:
        chm = ndimage.gaussian_filter(ds.read(1).astype(np.float32), 2.0); chm_T = ds.transform
    dry = grass_spec.dryness_grid(img, 8)
    masks = grass_spec.vertex_masks(V, F, surf, SURF, chm, chm_T, dry, T * rasterio.Affine.scale(8))
    del chm, dry
    materials = {}
    groups = {}
    tint_cache = {}
    for si in np.unique(surf):
        sname = SURF[si]
        if sname not in MATS:
            continue
        opcd, alb, nrm, orm, tile, nscale, _ = MATS[sname]
        tsrc = TINT_FROM.get(sname, sname)
        if tsrc in tint_cache:
            tint, stats = tint_cache[tsrc]
        else:
            tint, stats = (tint_for_surface(tsrc, by_surface.get(tsrc, []), img, Y, openm, W, H, T)
                           if tsrc in by_surface and sname not in NO_TINT else (None, None))
            if tint is not None and C.TURF_TINT and tsrc in C.TURF_TINT:
                tint, stats = season_grade(tint, stats, C.TURF_TINT[tsrc])
            if tsrc in TINT_FROM.values():
                tint_cache[tsrc] = (tint, stats)
        if alb is not None:
            tm = mean_lin(alb)
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
                materials[key] = (glb.material(f"{opcd}", base_color=encode(alb, "albedo", gain), normal=encode(nrm, "normal"),
                                               orm=encode(orm, "orm"), normal_scale=nscale,
                                               specular=0.25 if sname in GRASS | {"bunkerlip"} else (0.6 if sname in ("bunker", "native") else None),
                                               extras={"surface": sname, "tile_m": tile}), tm * np.asarray(gain))
        else:
            key = (opcd, sname)
            # water: dark, slightly green-blue, glossy (vertex colour carries the photo's tint)
            materials[key] = (glb.material(opcd, base_factor=(0.18, 0.24, 0.22, 1.0), rough=0.06, metal=0.0,
                                           extras={"surface": sname}), np.array([0.18, 0.24, 0.22], np.float32))
        mat_index, tex_mean = materials[key]
        interp = [RegularGridInterpolator((ys[::-1], xs), tint[::-1, :, c], bounds_error=False, fill_value=None) for c in range(3)] if tint is not None else None
        for h in np.unique(hole[surf == si]):
            fsel = np.flatnonzero((surf == si) & (hole == h))
            vid, inv = np.unique(F[fsel], return_inverse=True)
            P = V[vid]
            if interp is not None:
                col = np.stack([f(np.c_[P[:, 1], P[:, 0]]) for f in interp], 1) / tex_mean
                col *= stripe_factor(P, sname, h)[:, None] / (1 + STRIPES.get(sname, (1, 0, 0))[1])
                col *= canopy_ao(P)[:, None] * SHADE.get(sname, 1.0)
                if sname in GRASS:
                    col *= turf_patches(P)
                elif sname == "bunker":
                    col *= sand_shade(N[vid, 2])[:, None] * turf_patches(P, amp=0.04)
                col = np.clip(col, 0, 1)
            else:
                col = np.ones((len(P), 3)) * (canopy_ao(P)[:, None] * 0.9 if sname in NO_TINT else 1.0)
            pos = to_model(P)
            nrm_m = np.c_[N[vid, 0], N[vid, 2], -N[vid, 1]]
            uv0 = np.c_[P[:, 0] / tile, -P[:, 1] / tile]
            uv0 -= np.floor(uv0.mean(0))  # keep numbers small
            name = f"Hole{int(h):02d}_{OBJECT.get(sname, opcd)}"
            col1 = masks[vid] if sname in grass_spec.GRASS3DG else np.zeros((len(vid), 3), np.float32)
            idx = inv.reshape(-1, 3)
            if int(h) == 99 and sname in TILED:
                cen = P[idx].mean(1)
                ti = ((cen[:, 0] - C.CORE["xmin"]) // C.TILE).astype(int); tj = ((cen[:, 1] - C.CORE["ymin"]) // C.TILE).astype(int)
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
    add_water_planes(glb, terrain)


def add_water_planes(glb, parent):
    """OPCD <Hole>_WaterPlane: flat at the water level, outset under the banks (build/water_planes.json from the
    mesh step). In GSPro this mesh's collider carries the water physic material: it makes the pond a hazard."""
    import triangle
    path = C.BUILD / "water_planes.json"
    if not path.exists():
        return
    mat = glb.material("WaterPlane", base_factor=(0.035, 0.075, 0.08, 0.86), rough=0.04, metal=0.0, alpha_mode="BLEND",
                       extras={"surface": "waterplane"}, specular=1.0)
    n = 0
    seen = {}
    for w in sorted(json.load(open(path)), key=lambda w: (w["hole"], -len(w["polygon_utm"]))):
        ring = np.asarray(w["polygon_utm"])[:-1]
        S = np.c_[np.arange(len(ring)), (np.arange(len(ring)) + 1) % len(ring)]
        t = triangle.triangulate({"vertices": ring - [C.ORIGIN_E, C.ORIGIN_N], "segments": S}, "pq25a4")
        P = np.c_[t["vertices"] + [C.ORIGIN_E, C.ORIGIN_N], np.full(len(t["vertices"]), w["level"])]
        tri = t["triangles"]
        e1 = P[tri[:, 1], :2] - P[tri[:, 0], :2]; e2 = P[tri[:, 2], :2] - P[tri[:, 0], :2]
        a = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
        tri = np.where((a < 0)[:, None], tri[:, ::-1], tri)  # counter-clockwise from above = faces up
        pos = to_model(P)
        nrm = np.tile([0.0, 1.0, 0.0], (len(P), 1))
        uv0 = np.c_[P[:, 0] / 8.0, -P[:, 1] / 8.0]; uv0 -= np.floor(uv0.mean(0))
        base = f"Hole{int(w['hole']):02d}_WaterPlane"
        seen[base] = seen.get(base, 0) + 1
        name = base if seen[base] == 1 else f"{base}_{seen[base]}"
        m = glb.mesh(name, [dict(pos=pos, nrm=nrm, uv0=uv0, col=None, idx=tri, material=mat)])
        glb.node(name, mesh=m, parent=parent, extras={"water_level_m": w["level"]})
        n += 1
    print("water planes", n)


SKY = ((0.0, "#2f6db8"), (0.3, "#5f97d3"), (0.45, "#a9c7e3"), (0.5, "#d6e2ea"), (0.53, "#c2cdb8"), (1.0, "#7d8a64"))


def viewer_config():
    """output/<slug>/viewer.json, read by viewer/index.html: title, model file, crown tint per archetype and the sky
    gradient (regions/<region>.toml [viewer])."""
    v = C.REGION.get("viewer", {})
    tint = v.get("species_tint", {})
    return {"title": C.COURSE_SHORT, "name": C.COURSE_NAME, "model": f"{C.MODEL_NAME}.glb",
            "species_tint": {a: list(tint.get(a, (1.0, 1.0, 1.0))) for a in C.TREE_ARCHETYPES},
            "sky": [list(s) for s in v.get("sky", SKY)]}


def main(out=None):
    out = out or (C.OUTPUT / f"{C.MODEL_NAME}.glb")
    C.OUTPUT.mkdir(exist_ok=True)
    json.dump(viewer_config(), open(C.OUTPUT / "viewer.json", "w"), indent=1)
    glb = GLB()
    root = glb.node(C.COURSE_SHORT.replace(" ", "_").replace("&", "and"), extras={
        "course": C.COURSE_NAME, "crs": C.CRS, "crs_label": C.CRS_LABEL, "origin_utm": [C.ORIGIN_E, C.ORIGIN_N], "base_height": C.BASE_H,
        "axes": "x=east, y=up, z=south (glTF); metres"})
    add_terrain(glb, root)
    try:
        import add_backdrop
        add_backdrop.add(glb, root)
    except ImportError:
        pass
    try:
        import add_structures
        add_structures.add(glb, root)
    except ImportError:
        pass
    # snapshot without vegetation (input for the Blender FBX export: 60k+ tree instances would become 60k objects)
    nv = glb.save(out.with_name(out.stem + "_noveg.glb"))
    print("wrote", out.with_name(out.stem + "_noveg.glb"), round(nv / 1e6, 1), "MB")
    try:
        import add_vegetation
        add_vegetation.add(glb, root)
    except ImportError:
        pass
    n = glb.save(out)
    print("wrote", out, round(n / 1e6, 1), "MB")


if __name__ == "__main__":
    main()
