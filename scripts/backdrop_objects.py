"""Trees and buildings on the backdrop beyond the course, so the horizon is not a flat photo drape.

Trees: canopy peaks of the HRDEM surface model minus its terrain model (data/dem/backdrop_dsm.tif - backdrop_dem.tif,
same 2018 survey, 2 m), one billboard tree (the archetypes' distant LOD) per crown. Buildings: OpenStreetMap footprints
outside the build extent, extruded to their LiDAR roof height with a hipped roof. Both cover the near backdrop ring
only (core + 640 m); they are viewer / glTF scenery and do not go to GSPro (its outer plot is a heightmap + photo).
"""
import sys, zlib
import numpy as np
import rasterio
from scipy import ndimage

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C

DSM = C.DATA / "dem" / "backdrop_dsm.tif"
DTM = C.DATA / "dem" / "backdrop_dem.tif"
DEFAULT_HEIGHT = 6.0      # m: a two-storey house, for footprints without building returns
MIN_TREE_H = 5.0          # m: lower peaks are hedges, shrubs, cars, fences
ROOF_PALETTE = ((0.34, 0.33, 0.32), (0.28, 0.24, 0.22), (0.45, 0.42, 0.38), (0.38, 0.27, 0.22), (0.22, 0.23, 0.25))


def tree_peaks(chm, T, min_h=MIN_TREE_H, min_sep=6.0):
    """(n, 4) array of x, y, height, crown radius: local maxima of the canopy height model at least `min_sep` m apart
    and `min_h` m tall. The radius scales with height (Southern Ontario parkland: about a third of the height)."""
    res = abs(T.a)
    s = ndimage.gaussian_filter(np.nan_to_num(chm, nan=0.0), 0.6)
    k = int(np.ceil(min_sep / res)) | 1
    peak = (s == ndimage.maximum_filter(s, size=k)) & (s >= min_h)
    lab, n = ndimage.label(peak, structure=np.ones((3, 3)))       # tied maxima of one crown -> one tree
    if n == 0:
        return np.zeros((0, 4))
    rc = np.array(ndimage.center_of_mass(peak, lab, range(1, n + 1)))
    r, c = rc[:, 0], rc[:, 1]
    raw = ndimage.maximum_filter(np.nan_to_num(chm, nan=0.0), size=3)  # the height from the unsmoothed canopy
    h = raw[np.round(r).astype(int), np.round(c).astype(int)]
    x = T.c + (c + 0.5) * T.a; y = T.f + (r + 0.5) * T.e
    return np.c_[x, y, h, np.clip(0.3 * h + 0.5, 2.0, 8.0)]


def building_top(dsm_vals, ground):
    """Roof-top height of a footprint from its DSM samples: drop ground-level and overhanging-tree returns, then the
    90th percentile. DEFAULT_HEIGHT above the ground when there are no roof returns."""
    v = np.asarray(dsm_vals, float)
    v = v[np.isfinite(v) & (v > ground + 1.5)]
    if len(v) < 2:
        return ground + DEFAULT_HEIGHT
    v = v[v <= np.median(v) + 3.0]
    return float(np.percentile(v, 90))


def building_mesh(poly, ground, top, pitch=0.5, rise_max=3.0, with_roof_count=False):
    """Light extruded building: walls from 0.3 m below `ground` to the eaves, a hipped roof (pitch, at most rise_max)
    up to `top`. Returns UTM vertices (n, 3) and triangles (m, 3), upward / outward facing; the roof vertices come
    first (their count is returned too with with_roof_count=True)."""
    import shapely, triangle
    from shapely.geometry import Polygon
    g = poly.simplify(0.5)
    if g.geom_type != "Polygon" or g.is_empty:
        g = poly.convex_hull
    g = Polygon(g.exterior.coords) if g.exterior.is_ccw else Polygon(g.exterior.coords[::-1])
    ring = np.asarray(g.exterior.coords)[:-1]; n = len(ring)
    o = ring.mean(0)
    t = triangle.triangulate({"vertices": ring - o, "segments": np.c_[np.arange(n), (np.arange(n) + 1) % n]},
                             f"pqa{max(4.0, g.area / 60):.1f}")
    V2 = t["vertices"] + o; Fr = t["triangles"]
    d = shapely.distance(shapely.points(V2), g.exterior)
    rise = min(rise_max, pitch * float(d.max()), max(top - ground - 2.5, 0.5))
    eave = top - rise
    z = np.minimum(eave + pitch * d, top)
    P = [np.c_[V2, z]]
    e1 = P[0][Fr[:, 1], :2] - P[0][Fr[:, 0], :2]; e2 = P[0][Fr[:, 2], :2] - P[0][Fr[:, 0], :2]
    Fr = np.where(((e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) > 0)[:, None], Fr, Fr[:, [0, 2, 1]])
    F = [Fr]
    base = len(V2)
    W, Fw = [], []
    for i in range(n):
        p0, p1 = ring[i], ring[(i + 1) % n]
        b = base + len(W)
        W += [[*p0, ground - 0.3], [*p1, ground - 0.3], [*p1, eave], [*p0, eave]]
        Fw += [[b, b + 1, b + 2], [b, b + 2, b + 3]]
    P.append(np.array(W)); F.append(np.array(Fw))
    out = (np.concatenate(P), np.concatenate(F).astype(np.int64))
    return out + (base,) if with_roof_count else out


def _sampler(path):
    with rasterio.open(path) as ds:
        z = ds.read(1).astype(np.float32); T = ds.transform
    def f(x, y):
        c = ((np.asarray(x) - T.c) / T.a - 0.5); r = ((np.asarray(y) - T.f) / T.e - 0.5)
        return ndimage.map_coordinates(z, [r, c], order=1, mode="nearest", cval=np.nan)
    return z, T, f


def _flat_normals(P, F):
    N = np.zeros_like(P)
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    return N / (np.linalg.norm(N, axis=1, keepdims=True) + 1e-9)


def add(glb, root):
    """Backdrop_Trees (instanced billboards) and Backdrop_Buildings (merged per 512 m tile) in the near ring."""
    if not (DSM.exists() and DTM.exists()):
        print("backdrop objects: no backdrop_dsm.tif, skipped")
        return
    import shapely
    from shapely.geometry import box
    from rasterio.features import rasterize
    from build_backdrop import NEAR
    from export_course import to_model
    from add_structures import wall_colour
    from surface_classify import osm_geoms
    dsm, T, fdsm = _sampler(DSM)
    dtm, T2, fdtm = _sampler(DTM)
    ring = box(NEAR["xmin"], NEAR["ymin"], NEAR["xmax"], NEAR["ymax"]).difference(
        box(C.CORE["xmin"] + 1, C.CORE["ymin"] + 1, C.CORE["xmax"] - 1, C.CORE["ymax"] - 1))
    blds = [(oid, g) for oid, t, g in osm_geoms() if "building" in t and g.geom_type == "Polygon" and g.area >= 12
            and ring.contains(g.centroid)]
    # ---- trees: canopy height outside building footprints
    chm = np.where(np.isfinite(dsm) & np.isfinite(dtm), dsm - dtm, 0).astype(np.float32)
    if blds:
        bm = rasterize([(g.buffer(2.0), 1) for _, g in blds], out_shape=chm.shape, transform=T, fill=0, dtype="uint8")
        chm[bm.astype(bool)] = 0
    pk = tree_peaks(chm, T)
    pk = pk[shapely.contains_xy(ring, pk[:, 0], pk[:, 1])]
    rng = np.random.default_rng(31)
    kinds = ("maple", "oak", "spruce")
    pick = rng.choice(len(kinds), len(pk), p=(0.5, 0.35, 0.15))
    leaf = {}
    tgrp = glb.node("Backdrop_Trees", parent=root)
    nt = 0
    for ki, arch in enumerate(kinds):
        f = C.DATA / "trees" / f"{arch}_v1_bb.npz"
        sel = np.flatnonzero(pick == ki)
        if not f.exists() or not len(sel):
            continue
        d = np.load(f)
        if arch not in leaf:
            leaf[arch] = glb.material(f"Foliage_{arch}_backdrop", base_color=str(C.DATA / "textures_gen" / f"foliage_{arch}.png"),
                                      alpha_mode="MASK", alpha_cutoff=0.45, double_sided=True, rough=0.8)
        mesh = glb.mesh(f"Backdrop_Tree_{arch}", [dict(pos=d["leaf_p"], nrm=d["leaf_n"], uv0=d["leaf_uv"], idx=d["leaf_i"],
                                                       material=leaf[arch], col=d["leaf_c"])])
        x, y, h, r = pk[sel].T
        gz = fdtm(x, y)
        tr = np.c_[x - C.ORIGIN_E, gz - C.BASE_H - 0.1, -(y - C.ORIGIN_N)]
        yaw = rng.uniform(0, 2 * np.pi, len(sel))
        rot = np.c_[np.zeros(len(sel)), np.sin(yaw / 2), np.zeros(len(sel)), np.cos(yaw / 2)]
        sy = h / float(d["H"]); sxz = np.clip(r / float(d["R"]), 0.55 * sy, 1.7 * sy)
        glb.node(f"Backdrop_Trees_{arch}", mesh=mesh, parent=tgrp, instances=(tr, rot, np.c_[sxz, sy, sxz]))
        nt += len(sel)
    # ---- buildings: merged per 512 m tile, colours in COLOR_0
    mat = glb.material("Backdrop_Building", base_factor=(1, 1, 1, 1), rough=0.85)
    tiles = {}
    for oid, g in blds:
        try:
            gx, gy = np.meshgrid(np.arange(g.bounds[0], g.bounds[2], 2.0) + 1, np.arange(g.bounds[1], g.bounds[3], 2.0) + 1)
            inside = shapely.contains_xy(g, gx.ravel(), gy.ravel())
            ring_xy = np.asarray(g.exterior.coords)
            ground = float(np.nanmin(fdtm(ring_xy[:, 0], ring_xy[:, 1])))
            top = building_top(fdsm(gx.ravel()[inside], gy.ravel()[inside]) if inside.any() else [], ground)
            P, F, n_roof = building_mesh(g, ground, top, with_roof_count=True)
        except Exception:      # degenerate OSM footprints (self-touching rings, slivers): skip that building
            continue
        k = (int((g.centroid.x - NEAR["xmin"]) // 512), int((g.centroid.y - NEAR["ymin"]) // 512))
        wall = wall_colour(oid); roof = np.asarray(ROOF_PALETTE[zlib.crc32(str(oid).encode()) % len(ROOF_PALETTE)], np.float32)
        col = np.r_[np.tile(roof, (n_roof, 1)), np.tile(wall, (len(P) - n_roof, 1))]
        tiles.setdefault(k, []).append((P, F, col))
    bgrp = glb.node("Backdrop_Buildings", parent=root)
    for k, parts in sorted(tiles.items()):
        off = np.cumsum([0] + [len(p[0]) for p in parts[:-1]])
        P = np.concatenate([p[0] for p in parts]); F = np.concatenate([p[1] + o for p, o in zip(parts, off)])
        col = np.concatenate([p[2] for p in parts])
        N = _flat_normals(P, F)
        m = glb.mesh(f"Backdrop_Buildings_{k[0]}_{k[1]}", [dict(pos=to_model(P), nrm=np.c_[N[:, 0], N[:, 2], -N[:, 1]],
                                                                uv0=np.zeros((len(P), 2)), idx=F, material=mat, col=col)])
        glb.node(f"Backdrop_Buildings_{k[0]}_{k[1]}", mesh=m, parent=bgrp)
    print("backdrop objects: trees", nt, "buildings", sum(len(v) for v in tiles.values()))
