"""OPCD edge features derived from the surface partition: bunker lips, water edge bands, the water bed and plane.

Conventions follow the OPCD Blender add-on and SetMeshMaterial.cs (research/opcd_toolset_dl, v06-2021):
  <Hole>_Bunker_Lip   the outer band of each bunker; the sand drops across it. The 2021 add-on insets 5 + 2 + 1 cm and
                      drops ~3.5 cm; the V4 add-on (2026) defaults to a 0.05 m lip depth with a 'concave' profile,
                      which is what we use. Unity: Bunker_Lip material, rough physics.
  <Hole>_Water_Base   ONE object with material slots [Water_Base, Water_Edge]; the edge is a 0.15 m inset band.
                      It is the bed under the water (rough physics).
  <Hole>_WaterPlane   flat at the water level and outset 2 m under the banks; it carries the water physic material,
                      so it is what makes the pond a water hazard in GSPro.
The rings are added only where the mesh is fine (the detail zone around the playable holes): a 10 cm band would not
survive the coarse simplification used elsewhere.
"""
import sys
import numpy as np
import shapely
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from scipy import ndimage

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent)); import config as C

LIP_W = 0.10           # bunker lip band width (m)
LIP_DEPTH = 0.05       # sand sits this much below the lip edge (OPCD V4 add-on default 'bunker lip depth')
LIP_HOLES = C.PLAYABLE
WATER_EDGE_W = 0.15    # OPCD Water_Edge inset
PLANE_OUTSET = 2.0     # OPCD WaterPlane outset under the banks
BED_SHORE, BED_SLOPE, BED_MAX = 0.08, 0.35, 1.2   # bed depth below the water level: shore, gradient, maximum (m)
BERM = 0.08            # land inside the plane's outset is kept at least this much above the water (no spill; 2 cm z-fought)
WATER_STEP = C.tuning("water_step", 0.3)  # m: a water body whose shoreline falls more than this (a river) is cut in reaches


def _polys(g):
    if g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon" and not p.is_empty]


def derive_rings(feats, zone):
    """Split bunkers (playable holes) and water bodies inside the detail zone into an interior and an edge ring.

    feats: [(polygon, surface, hole)]. Returns (feats with the splits applied, rings) where rings is
    [(ring polygon, ring surface, hole, original polygon)]. Interior + ring == original polygon (a partition)."""
    zb = zone.buffer(1.0) if zone is not None and not zone.is_empty else None
    out, rings = [], []
    for g, s, h in feats:
        if s == "bunker" and h in LIP_HOLES:
            w, rs = LIP_W, "bunkerlip"
        elif s == "water":
            w, rs = WATER_EDGE_W, "wateredge"
        else:
            out.append((g, s, h)); continue
        for p in _polys(g):
            if zb is None or not p.within(zb):
                out.append((p, s, h)); continue
            inner = p.buffer(-w, quad_segs=2, join_style="mitre", mitre_limit=2.0)
            inner = unary_union([q for q in _polys(inner) if q.area > 0.05])
            if inner.is_empty or inner.area < 0.3 * p.area:
                out.append((p, s, h)); continue
            ring = p.difference(inner)
            for q in _polys(inner):
                out.append((q, s, h))
            out.append((ring, rs, h))
            rings.append((ring, rs, h, p))
    return out, rings


QUERY_CHUNK = 1 << 18  # points made into GEOS points at a time (lip_drop, label_rings)


def _point_chunks(pts):
    """(offset, GEOS points) for points (n, 2), QUERY_CHUNK at a time. A GEOS point for each of Whistle Bear's 5.3 M
    triangle centroids at once was 0.9 GB; an STRtree query gives the same pairs, in the same order, chunk by chunk."""
    for s in range(0, len(pts), QUERY_CHUNK):
        yield s, shapely.points(pts[s:s + QUERY_CHUNK])


def lip_drop(pts, rings):
    """Sand drop (m, >= 0) at points (n, 2): 0 on the bunker edge, LIP_DEPTH from LIP_W inside, linear across the lip."""
    pts = np.asarray(pts, np.float64)
    drop = np.zeros(len(pts))
    outers = [p for _, rs, _, p in rings if rs == "bunkerlip"]
    if not outers or not len(pts):
        return drop
    tree = shapely.STRtree(outers)
    # each bunker's boundary made once: a copy for every point in the bunker was 7.5 GB on Whistle Bear (270 k mesh
    # vertices in 84 bunkers of ~700 boundary points), half of the mesh step's peak
    bnd = shapely.boundary(outers)
    for s, P in _point_chunks(pts):
        pi, gi = tree.query(P, predicate="intersects")
        if len(pi):
            d = shapely.distance(P[pi], bnd[gi])
            t = np.clip(d / LIP_W, 0.0, 1.0)
            pi += s
            drop[pi] = np.maximum(drop[pi], LIP_DEPTH * (1.0 - (1.0 - t) ** 2))   # concave lip profile
    return drop


def lip_drop_raster(rings, T, shape):
    """Raster version for dem_final (the heightmap): the full drop inside the lip, 0 elsewhere."""
    from rasterio.features import rasterize
    inner = [p.difference(r) for r, rs, _, p in rings if rs == "bunkerlip"]
    if not inner:
        return np.zeros(shape, np.float32)
    return LIP_DEPTH * rasterize([(g, 1) for g in inner], out_shape=shape, transform=T, fill=0, dtype="uint8").astype(np.float32)


def label_rings(cent, surf, hole, rings, sid):
    """Relabel triangles whose centroid lies in an edge ring (the label raster is coarser than a 10 cm band)."""
    surf = np.array(surf, copy=True); hole = np.array(hole, copy=True)
    if not rings:
        return surf, hole
    tree = shapely.STRtree([r for r, _, _, _ in rings])
    ring_s = np.array([sid[rs] for _, rs, _, _ in rings], surf.dtype)
    ring_h = np.array([h for _, _, h, _ in rings], hole.dtype)
    for s, P in _point_chunks(np.asarray(cent)[:, :2]):
        pi, gi = tree.query(P, predicate="within")
        surf[pi + s] = ring_s[gi]; hole[pi + s] = ring_h[gi]
    return surf, hole


def _shoreline(p, dem, T):
    """Points every 0.5 m round p's outline and the DEM under them."""
    ring = np.asarray(p.exterior.segmentize(0.5).coords)
    cc = (ring[:, 0] - T.c) / T.a - 0.5; rr = (ring[:, 1] - T.f) / T.e - 0.5
    return ring, ndimage.map_coordinates(dem, [rr, cc], order=1, mode="nearest")


def water_levels(feats, dem, T):
    """[(polygon, level, hole)]: a flat water level per water body at its lowest ~20 % shoreline (LiDAR has few
    returns on water) minus 5 cm; a body that falls more than WATER_STEP, per reach (water_bodies)."""
    return [(r, lv, h) for _, reaches, h in water_bodies(feats, dem, T) for r, lv in reaches]


def water_bodies(feats, dem, T):
    """[(polygon, [(reach, level)], hole)] for every water polygon of feats (water_reaches)."""
    return [(p, water_reaches(p, dem, T), h) for g, s, h in feats if s == "water" for p in _polys(g)]


def water_reaches(p, dem, T, step=None, radius=60.0, cell=1.0, min_piece=50.0):
    """[(reach, level)] of water body p. A pond: [(p, its lowest ~20 % shoreline minus 5 cm)]. A body whose local
    level - the 20th percentile of the shoreline within `radius` m of a point on it - falls more than `step` m
    (WATER_STEP; Deer Ridge's Grand River 1.7-3.8 m across the course, a Whistle Bear pond 1.65 m at a rock cascade)
    is cut across into reaches falling at most that much: each cell of a `cell` m grid takes the local level of the
    shoreline point nearest it, banded; at a step in the shoreline, the 80th percentile of the local levels within
    `radius` m, so the cut falls at the step (the 20th percentile alone put it 20-45 m up Whistle Bear's pond from the
    cascade, and 40 m above a weir on Deer Ridge's river: the upper water 1.4-1.6 m low). Each reach is flat at its
    band's lower end minus 5 cm, so its water is never above its banks. Pieces under `min_piece` m2 join the neighbour
    they share the longest edge with. The reaches tile p."""
    from scipy.spatial import cKDTree
    from rasterio.features import rasterize, shapes
    from rasterio.transform import from_origin
    from shapely.geometry import shape
    step = WATER_STEP if step is None else step
    ring, z = _shoreline(p, dem, T)
    level = float(np.percentile(z, 20)) - 0.05
    tree = cKDTree(ring[:, :2])
    near = tree.query_ball_point(ring[:, :2], radius)
    L = np.array([np.percentile(z[i], 20) for i in near])
    lo, span = float(L.min()), float(L.max() - L.min())
    if step <= 0 or span <= step:
        return [(p, level)]
    # the 20th percentile moves a step in the shoreline (a cascade, a weir) up to 0.6 radius uphill; the 80th
    # percentile of those levels over the same radius moves it back (a rank opening). It is taken only where it is more
    # than a step above: it also widens a high bank along one side of a wide river into a plateau (Deer Ridge's Grand
    # River, a 100 m levee 0.5 m above the water on one bank, 165 m from the other)
    up = np.array([np.percentile(L[i], 80) for i in near])
    L = np.where(up - L > step, up, L)
    n = int(np.ceil(span / step)); w = span / n
    band = np.minimum(n - 1, ((L - lo) / w).astype(np.int32))
    x0, y0, x1, y1 = p.buffer(2 * cell).bounds
    tw = from_origin(x0, y1, cell, cell)
    sh = (int(np.ceil((y1 - y0) / cell)), int(np.ceil((x1 - x0) / cell)))
    cover = rasterize([(p.buffer(2 * cell), 1)], out_shape=sh, transform=tw, fill=0, dtype="uint8").astype(bool)
    rr, cc = np.nonzero(cover)
    _, near = tree.query(np.c_[x0 + (cc + 0.5) * cell, y1 - (rr + 0.5) * cell])
    lab = np.zeros(sh, np.int32); lab[rr, cc] = band[near] + 1
    pieces = [[q, int(v) - 1] for g, v in shapes(lab, mask=cover, transform=tw) for q in _polys(shape(g).intersection(p))
              if q.area > 0]
    pieces.sort(key=lambda x: -x[0].area)
    keep = [x for x in pieces if x[0].area >= min_piece]
    for q, k in pieces:
        if q.area >= min_piece:
            continue
        edge = max(((q.boundary.intersection(o[0].boundary).length, i) for i, o in enumerate(keep)), default=(0.0, 0))
        if edge[0] > 0:
            keep[edge[1]][0] = keep[edge[1]][0].union(q)
        else:
            keep.append([q, k])
    return [(q, lo + k * w - 0.05) for q, k in keep]


def water_planes(p, reaches, dem_out, T):
    """[(WaterPlane outline, level)] of water body p cut in `reaches` (water_reaches): one per reach, outset
    PLANE_OUTSET under the banks (water_plane_polygon) but not over another reach's water, which is higher or lower."""
    if len(reaches) == 1:
        return [(water_plane_polygon(p, dem_out, T, reaches[0][1]), reaches[0][1])]
    out = []
    for i, (r, lv) in enumerate(reaches):
        others = unary_union([q for j, (q, _) in enumerate(reaches) if j != i])
        g = water_plane_polygon(r, dem_out, T, lv).difference(others)
        out += [(q, lv) for q in _polys(g) if q.area >= 1.0]
    return out


def _window(T, shape, bounds, pad):
    H, W = shape
    c0 = max(0, int((bounds[0] - pad - T.c) / T.a)); c1 = min(W, int((bounds[2] + pad - T.c) / T.a) + 1)
    r0 = max(0, int((bounds[3] + pad - T.f) / T.e)); r1 = min(H, int((bounds[1] - pad - T.f) / T.e) + 1)
    return r0, r1, c0, c1


def carve_water(out, T, p, level, reaches=None):
    """In place: a shelving bed under the water (BED_* below the level), the shoreline band at the level, and a berm so
    no land inside the plane's outset lies below the water (it would show the plane = spilled water). A body cut in
    several `reaches` (water_reaches) is carved at each cell's own level (carve_reaches)."""
    if reaches is not None and len(reaches) > 1:
        return carve_reaches(out, T, p, reaches)
    from rasterio.features import rasterize
    from rasterio.windows import Window, transform as wtransform
    r0, r1, c0, c1 = _window(T, out.shape, p.bounds, PLANE_OUTSET + 2.0)
    if r1 <= r0 or c1 <= c0:
        return out
    tw = wtransform(Window(c0, r0, c1 - c0, r1 - r0), T)
    sh = (r1 - r0, c1 - c0)
    sub = out[r0:r1, c0:c1]
    inside = rasterize([(p, 1)], out_shape=sh, transform=tw, fill=0, dtype="uint8").astype(bool)
    shore = rasterize([(p.buffer(0.3), 1)], out_shape=sh, transform=tw, fill=0, dtype="uint8").astype(bool) & ~inside
    berm = rasterize([(p.buffer(PLANE_OUTSET + 0.5), 1)], out_shape=sh, transform=tw, fill=0, dtype="uint8").astype(bool)
    berm &= ~inside & ~shore
    d = ndimage.distance_transform_edt(inside) * abs(T.a)
    bed = level - np.minimum(BED_MAX, BED_SHORE + BED_SLOPE * d)
    sub[inside] = bed[inside]
    sub[shore] = level - BED_SHORE
    sub[berm] = np.maximum(sub[berm], level + BERM)
    return out


def carve_reaches(out, T, p, reaches):
    """carve_water for a body cut in reaches: the bed deepens from the body's own shore (no ridge where reaches meet)
    below each cell's reach level; the shoreline band takes the level of the reach nearest it; the berm keeps the land
    under every reach's WaterPlane outset (water_planes) above the highest plane over it."""
    from rasterio.features import rasterize
    from rasterio.windows import Window, transform as wtransform
    r0, r1, c0, c1 = _window(T, out.shape, p.bounds, PLANE_OUTSET + 2.0)
    if r1 <= r0 or c1 <= c0:
        return out
    tw = wtransform(Window(c0, r0, c1 - c0, r1 - r0), T)
    sh = (r1 - r0, c1 - c0)
    sub = out[r0:r1, c0:c1]
    burn = lambda g: rasterize([(g, 1)], out_shape=sh, transform=tw, fill=0, dtype="uint8").astype(bool)
    inside = burn(p)
    shore = burn(p.buffer(0.3)) & ~inside
    berm = burn(p.buffer(PLANE_OUTSET + 0.5)) & ~inside & ~shore
    lab = rasterize([(r, i + 1) for i, (r, _) in enumerate(reaches)], out_shape=sh, transform=tw, fill=0, dtype="int32")
    levels = np.array([0.0] + [lv for _, lv in reaches])
    iy, ix = ndimage.distance_transform_edt(lab == 0, return_distances=False, return_indices=True)
    lvl = levels[lab[iy, ix]]
    top = lvl.copy()
    for g, lv in sorted(water_planes(p, reaches, out, T), key=lambda x: x[1]):
        m = burn(g.buffer(0.5)); top[m] = np.maximum(top[m], lv)
    d = ndimage.distance_transform_edt(inside) * abs(T.a)
    bed = lvl - np.minimum(BED_MAX, BED_SHORE + BED_SLOPE * d)
    sub[inside] = bed[inside]
    sub[shore] = lvl[shore] - BED_SHORE
    sub[berm] = np.maximum(sub[berm], top[berm] + BERM)
    return out


def water_plane_polygon(p, dem_out, T, level):
    """The WaterPlane outline: the water body outset PLANE_OUTSET under the banks (carve_water keeps that land above
    the level)."""
    return p.buffer(PLANE_OUTSET, quad_segs=4).simplify(0.1)
