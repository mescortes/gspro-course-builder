"""Cart-path centre lines traced from the photo + LiDAR, for courses where OSM maps no paths (Westmount: no
golf=cartpath / highway=path inside the course; the paths are 2-2.5 m stone-dust / asphalt strips).

Candidates (DEM grid): dark ridges of NDVI 1-2.5 m wide (Sato line filter): a path is a narrow strip of no vegetation
between turf, or between leaf litter under the trees. NDVI is a band ratio, so the bare-tree shadow streaks of the
leaf-off photo barely show in it (they dominate RGB). Also required: low absolute NDVI, not black (shadowed roofs,
water), inside the course, away from mapped greens / bunkers / water / buildings / roads (their rims are NDVI ridges
too). Candidates are cleaned, skeletonised and kept as centre lines where the strip is path-wide and the line is long
(>= MIN_LEN); aligned gaps (trunks, cars, leaf litter) up to MAX_GAP are bridged.

Output: build/<slug>/paths_detected.geojson (LineStrings, properties golf=cartpath, source=trace_paths) in config.CRS.
surface_classify.osm_geoms() reads it like OSM paths, so classification, vectorize and the cart-path surfaces use it.
QA overrides correct what this misses. A photo without a NIR band has no NDVI: the file is written empty.
"""
import json, sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize
from scipy import ndimage
from shapely.geometry import LineString, mapping
from shapely.ops import linemerge, unary_union

sys.path.insert(0, str(Path(__file__).parent))
import config as C

OUT = C.BUILD / "paths_detected.geojson"
RIDGE_MIN, NDVI_MAX, L_MIN = 0.05, 0.25, 35.0
SIGMAS_M = (0.5, 0.75, 1.0, 1.25)   # Sato scales (m): ridges ~1-2.5 m wide
WIDTH = (0.6, 4.5)      # m, full strip width at the skeleton
MIN_LEN = 25.0          # m, shortest kept line (after bridging)
MAX_GAP, MAX_ANGLE = 6.0, 35.0          # short gaps (a trunk, a cart): loose alignment
LONG_GAP, LONG_ANGLE = 35.0, 25.0       # under a spruce / a long shadow (QA round 1): ends must face each other closely


def candidates(ridge, L, ndvi, exclude):
    """Per-pixel path rule (arrays of the same shape): ridge = Sato dark-line response of NDVI."""
    return (ridge > RIDGE_MIN) & (ndvi < NDVI_MAX) & (L > L_MIN) & ~exclude


def ndvi_ridges(ndvi, res):
    from skimage.filters import sato
    return sato(ndvi, sigmas=[s / res for s in SIGMAS_M], black_ridges=True, mode="reflect")


def _trace(skel):
    """8-connected skeleton pixels -> list of pixel paths [(r, c), ...] between junctions / ends (and closed loops)."""
    pts = set(map(tuple, np.argwhere(skel)))
    nb = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    def nbrs(p):
        return [(p[0] + a, p[1] + b) for a, b in nb if (p[0] + a, p[1] + b) in pts]
    deg = {p: len(nbrs(p)) for p in pts}
    nodes = {p for p, d in deg.items() if d != 2}
    seen = set(); paths = []
    def walk(a, b):
        path = [a, b]; prev, cur = a, b
        while cur not in nodes:
            nxt = [q for q in nbrs(cur) if q != prev and (min(cur, q), max(cur, q)) not in seen]
            if not nxt:
                break
            seen.add((min(cur, nxt[0]), max(cur, nxt[0])))
            prev, cur = cur, nxt[0]; path.append(cur)
            if cur == a:
                break
        return path
    for n in nodes:
        for q in nbrs(n):
            e = (min(n, q), max(n, q))
            if e in seen:
                continue
            seen.add(e)
            paths.append(walk(n, q))
    for p in pts:  # loops without junctions
        if deg[p] == 2 and not any((min(p, q), max(p, q)) in seen for q in nbrs(p)):
            q = nbrs(p)[0]; seen.add((min(p, q), max(p, q)))
            paths.append(walk(p, q))
    return paths


def centrelines(mask, T, min_len=MIN_LEN, width=WIDTH):
    """Clean candidate mask -> list of simplified centre LineStrings (map coordinates) of long strips whose full
    width at the skeleton lies in `width` (m)."""
    from skimage.morphology import skeletonize
    res = abs(T.a)
    m = ndimage.binary_closing(mask, iterations=2)
    m = ndimage.binary_opening(m, iterations=1)
    half = ndimage.distance_transform_edt(m) * res
    skel = skeletonize(m)
    w = 2 * half
    skel &= (w >= width[0]) & (w <= width[1])
    # drop skeleton spurs inside blobs: a pixel whose strip is wider than a path anywhere nearby
    wide = ndimage.maximum_filter(np.where(m, w, 0), size=int(round(3.0 / res)) | 1) > width[1] + 1.0
    skel &= ~wide
    lines = []
    for path in _trace(skel):
        if len(path) < 3:
            continue
        rc = np.asarray(path, float)
        x = T.c + (rc[:, 1] + 0.5) * T.a; y = T.f + (rc[:, 0] + 0.5) * T.e
        g = LineString(np.c_[x, y]).simplify(0.3)
        if g.length > 2 * res:
            lines.append(g)
    return [g for g in _merge(lines) if g.length >= min_len]


def _merge(geoms):
    """Union + line merge -> list of LineStrings (shapely's linemerge refuses a lone LineString)."""
    u = unary_union(list(geoms))
    if u.is_empty:
        return []
    if u.geom_type == "MultiLineString":
        u = linemerge(u)
    return [g for g in getattr(u, "geoms", [u]) if g.geom_type == "LineString"]


def _end_dir(g, at_start):
    c = np.asarray(g.coords)
    if at_start:
        p, q = c[0], c[min(len(c) - 1, 1)]
        for k in range(1, len(c)):
            if np.linalg.norm(c[k] - c[0]) > 2.0:
                q = c[k]; break
    else:
        p, q = c[-1], c[max(0, len(c) - 2)]
        for k in range(len(c) - 2, -1, -1):
            if np.linalg.norm(c[k] - c[-1]) > 2.0:
                q = c[k]; break
    d = p - q
    return p, d / max(np.linalg.norm(d), 1e-9)  # outward direction at that end


def bridge(lines, max_gap=MAX_GAP, max_angle=MAX_ANGLE, ok=None):
    """Join line ends that face each other across a gap (shadow / trunk / conifer interruptions). `ok(segment)` may
    veto a connector (e.g. one crossing a green, a bunker or a fairway)."""
    ends = []
    for i, g in enumerate(lines):
        for s in (True, False):
            p, d = _end_dir(g, s)
            ends.append((i, p, d))
    cos = np.cos(np.radians(max_angle))
    used = set(); conn = []
    pairs = []
    for a in range(len(ends)):
        for b in range(a + 1, len(ends)):
            ia, pa, da = ends[a]; ib, pb, db = ends[b]
            if ia == ib:
                continue
            v = pb - pa; L = np.linalg.norm(v)
            if L > max_gap or L < 1e-6:
                continue
            u = v / L
            if u @ da >= cos and (-u) @ db >= cos and (ok is None or ok(LineString([pa, pb]))):
                pairs.append((L, a, b))
    for L, a, b in sorted(pairs):
        if a in used or b in used:
            continue
        used |= {a, b}
        conn.append(LineString([ends[a][1], ends[b][1]]))
    return _merge(list(lines) + conn)


def write(lines):
    feats = [{"type": "Feature", "geometry": mapping(g), "properties": {"golf": "cartpath", "source": "trace_paths",
                                                                        "length_m": round(g.length, 1)}} for g in lines]
    OUT.parent.mkdir(exist_ok=True)
    json.dump({"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::" + C.CRS.split(":")[1]}},
               "features": feats}, open(OUT, "w"))
    print(f"traced {len(lines)} path lines, {sum(g.length for g in lines):.0f} m -> {OUT}")


def main():
    from skimage.color import rgb2lab
    from surface_classify import grid, has_nir, read_imagery_window, read_nir_window, osm_geoms
    if not has_nir():
        # the paths are NDVI ridges: without NIR nothing is traced, and the empty file replaces any older trace
        print("trace_paths: the photo has no NIR band (paths are traced from NDVI), so no cart path is traced: map them "
              f"in OSM or the course overrides, or set [tuning] trace_paths = false in courses/{C.SLUG}/course.toml",
              flush=True)
        write([])
        return
    W, H, T = grid()
    G = [x for x in osm_geoms() if x[1].get("source") != "trace_paths"]
    def burn(geoms):
        geoms = [g for g in geoms if not g.is_empty]
        return rasterize([(g, 1) for g in geoms], out_shape=(H, W), transform=T, fill=0, dtype="uint8").astype(bool) \
            if geoms else np.zeros((H, W), bool)
    course = burn([g.buffer(5) for _, t, g in G if t.get("leisure") == "golf_course"])
    excl = burn([g.buffer(3.0) for _, t, g in G if t.get("golf") == "green" and g.geom_type == "Polygon"])
    excl |= burn([g.buffer(2.0) for _, t, g in G if (t.get("golf") in ("bunker", "water_hazard") or t.get("natural") == "water"
                                                        or "building" in t or t.get("amenity") == "parking") and g.geom_type != "LineString"])
    excl |= burn([g.buffer(4.0) for _, t, g in G if t.get("highway") and t.get("highway") not in ("path", "footway", "track")
                  and g.geom_type == "LineString"])
    # paths run beside fairways, not inside them: mowing stripes and dormant patches inside a fairway are NDVI ridges too
    excl |= burn([g.buffer(-0.5) for _, t, g in G if t.get("golf") == "fairway" and g.geom_type == "Polygon"])
    excl |= burn([g.buffer(2.0) for _, t, g in G if (t.get("leisure") in ("pitch", "sports_centre") or t.get("sport") not in (None, "golf"))
                  and t.get("leisure") != "golf_course"
                  and g.geom_type == "Polygon"])
    cand = np.zeros((H, W), bool)
    pad = 32
    for r0 in range(0, H, 1024):
        r1 = min(H, r0 + 1024); p0, p1 = max(0, r0 - pad), min(H, r1 + pad)
        rgb = read_imagery_window(T, p0, p1, 0, W)
        nir = read_nir_window(T, p0, p1, 0, W)
        ndvi = (nir - rgb[0]) / (nir + rgb[0] + 1e-3)
        ridge = ndvi_ridges(ndvi, C.DEM_RES)
        L = ndimage.gaussian_filter(rgb2lab(np.moveaxis(rgb, 0, -1))[..., 0], 1.0)
        c = candidates(ridge, L, ndimage.gaussian_filter(ndvi, 1.0), excl[p0:p1]) & course[p0:p1]
        cand[r0:r1] = c[r0 - p0:r0 - p0 + (r1 - r0)]
    lines = centrelines(cand, T, min_len=6.0)
    def clear(seg, frac=0.1):
        """A long connector may not cross excluded ground (greens, bunkers, water, buildings, fairway interiors)."""
        P = np.asarray(seg.segmentize(0.5).coords)
        c = ((P[:, 0] - T.c) / T.a).astype(int); r = ((P[:, 1] - T.f) / T.e).astype(int)
        inb = (c >= 0) & (c < W) & (r >= 0) & (r < H)
        return inb.all() and excl[r, c].mean() <= frac and course[r, c].all()
    lines = bridge(lines)
    lines = bridge([g for g in lines if g.length >= 6.0], LONG_GAP, LONG_ANGLE, ok=clear)
    lines = [g for g in lines if g.length >= MIN_LEN]
    write(lines)


if __name__ == "__main__":
    main()
