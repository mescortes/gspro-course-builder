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
import numpy as np
import shapely
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from scipy import ndimage

LIP_W = 0.10           # bunker lip band width (m)
LIP_DEPTH = 0.05       # sand sits this much below the lip edge (OPCD V4 add-on default 'bunker lip depth')
LIP_HOLES = range(1, 19)
WATER_EDGE_W = 0.15    # OPCD Water_Edge inset
PLANE_OUTSET = 2.0     # OPCD WaterPlane outset under the banks
BED_SHORE, BED_SLOPE, BED_MAX = 0.08, 0.35, 1.2   # bed depth below the water level: shore, gradient, maximum (m)
BERM = 0.08            # land inside the plane's outset is kept at least this much above the water (no spill; 2 cm z-fought)


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


def lip_drop(pts, rings):
    """Sand drop (m, >= 0) at points (n, 2): 0 on the bunker edge, LIP_DEPTH from LIP_W inside, linear across the lip."""
    pts = np.asarray(pts, np.float64)
    drop = np.zeros(len(pts))
    outers = [p for _, rs, _, p in rings if rs == "bunkerlip"]
    if not outers or not len(pts):
        return drop
    P = shapely.points(pts)
    tree = shapely.STRtree(outers)
    pi, gi = tree.query(P, predicate="intersects")
    if len(pi):
        bnd = np.array([outers[i].boundary for i in gi], object)
        d = shapely.distance(P[pi], bnd)
        t = np.clip(d / LIP_W, 0.0, 1.0)
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
    geoms = [r for r, _, _, _ in rings]
    tree = shapely.STRtree(geoms)
    pi, gi = tree.query(shapely.points(np.asarray(cent)[:, :2]), predicate="within")
    surf[pi] = np.array([sid[rings[i][1]] for i in gi], surf.dtype)
    hole[pi] = np.array([rings[i][2] for i in gi], hole.dtype)
    return surf, hole


def water_levels(feats, dem, T):
    """[(polygon, level, hole)]: a flat water level per water body at its lowest ~20 % shoreline (LiDAR has few
    returns on water) minus 5 cm."""
    out = []
    for g, s, h in feats:
        if s != "water":
            continue
        for p in _polys(g):
            ring = np.asarray(p.exterior.segmentize(0.5).coords)
            cc = (ring[:, 0] - T.c) / T.a - 0.5; rr = (ring[:, 1] - T.f) / T.e - 0.5
            z = ndimage.map_coordinates(dem, [rr, cc], order=1, mode="nearest")
            out.append((p, float(np.percentile(z, 20)) - 0.05, h))
    return out


def _window(T, shape, bounds, pad):
    H, W = shape
    c0 = max(0, int((bounds[0] - pad - T.c) / T.a)); c1 = min(W, int((bounds[2] + pad - T.c) / T.a) + 1)
    r0 = max(0, int((bounds[3] + pad - T.f) / T.e)); r1 = min(H, int((bounds[1] - pad - T.f) / T.e) + 1)
    return r0, r1, c0, c1


def carve_water(out, T, p, level):
    """In place: a shelving bed under the water (BED_* below the level), the shoreline band at the level, and a berm so
    no land inside the plane's outset lies below the water (it would show the plane = spilled water)."""
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


def water_plane_polygon(p, dem_out, T, level):
    """The WaterPlane outline: the water body outset PLANE_OUTSET under the banks (carve_water keeps that land above
    the level)."""
    return p.buffer(PLANE_OUTSET, quad_segs=4).simplify(0.1)
