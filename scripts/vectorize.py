"""Turn the per-pixel classification into a clean planar partition of course surfaces (GeoJSON, config.CRS).

Output: build/<slug>/features/auto_core.geojson — one feature per polygon with properties
  surface: green | fringe | fairway | semirough | rough | tee | bunker | cartpath | native | road | building | court | water
  hole:    course hole (config.course_hole of the OSM ref), 98 (cart paths), 99 (course-wide background)
The partition has no overlaps and covers the whole CORE extent (rough fills the remainder).
"""
import sys, json
import numpy as np
import rasterio
from rasterio.features import shapes, rasterize
from scipy import ndimage
from shapely.geometry import shape, mapping, box, Polygon, MultiPolygon, LineString, Point
from shapely.ops import unary_union
from shapely import make_valid

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C
from surface_classify import CLASSES, CID, osm_geoms, grid, ROAD_HALF_WIDTH, is_water, SAND, SHADOW_SAND, TURF, tuned
from surface_classify import TURF_TRACK, turf_track

RES = C.DEM_RES
# OSM/override water outranks everything (dark water is easily mistaken for green by the classifier)
PRIORITY = ["water", "green", "bunker", "tee", "cartpath", "road", "building", "court", "fairway", "native", "deeprough"]
STROKE = {"green": "#BCE5A4", "fringe": "#A4C88F", "fairway": "#43E561", "semirough": "#36B74D", "rough": "#278438",
          "deeprough": "#164B20", "tee": "#A0E5B8", "bunker": "#E5E5AA", "cartpath": "#BEBEBB", "native": "#BE751D",
          "road": "#555555", "building": "#C83C3C", "court": "#3355AA", "water": "#0000C0"}
FORWARD_TEE_FRAC = C.tuning("forward_tee_frac", 0.45)   # tee pads past this fraction of a hole are not its tees (Westmount <= 0.35)
FORWARD_TEE_REACH = C.tuning("forward_tee_reach", 60.0)        # m: a mapped tee no line claims, off its hole's line ...
FORWARD_TEE_CARD_TOL = C.tuning("forward_tee_card_tol", 10.0)  # yd: ... playing the hole's card within this (card_tee_hole)
BUNKER_CLEARANCE = C.tuning("bunker_clearance", (1.0, 10.0))  # unmapped bunkers: m clear of roads / of buildings
SHARED_FAIRWAY_MIN_PART = C.tuning("shared_fairway_min_part", 150.0)  # m2: smallest part of a shared fairway a hole takes
SHARED_FAIRWAY_MIN_RUN = C.tuning("shared_fairway_min_run", 80.0)     # m of a line inside a fairway it runs along ...
SHARED_FAIRWAY_GREEN_REACH = C.tuning("shared_fairway_green_reach", 30.0)  # ... or m from it to the line's green end
GREEN_OFF_COURSE = C.tuning("green_off_course", 15.0)  # m: a classifier green farther off the course outline is a lawn
MIN_AREA = {"deeprough": 60, "green": 60, "bunker": 10, "tee": 12, "fairway": 150, "cartpath": 6, "native": 25, "road": 25,
            "building": 25, "court": 50, "water": 4, "fringe": 4, "semirough": 4}
# Photo colour rules SAND, SHADOW_SAND and TURF ([tuning.sand], [tuning.shadow_sand], [tuning.turf]): surface_classify.py
# An unmapped bunker's LiDAR hollow must be closed or faced ([tuning.bunker_hollow], closed_hollow; pond_frac = 0 turns
# the test off; open and outlet: open_both_ends) ...
BUNKER_HOLLOW_DEFAULT = dict(pond=0.05, pond_frac=0.2, face=0.35, open=0.2, outlet=4.0)
BUNKER_HOLLOW = tuned("bunker_hollow", BUNKER_HOLLOW_DEFAULT)
# ... and with a photo of photo_res m or coarser the bunkers are cut to their LiDAR pans ([tuning.bunker_trim],
# bunker_bowls; photo_res = 0 always, a large value never)
BUNKER_TRIM_DEFAULT = dict(photo_res=0.3, radius=5.0, depth=0.08, lip=0.5, seed=0.02, seed_area=1.0)
BUNKER_TRIM = tuned("bunker_trim", BUNKER_TRIM_DEFAULT)


def under_canopy_labels(lab, canopy, leaf_off_photo):
    """Labels under tree canopy. Leaf-on photo: the ground is hidden, so canopy pixels inherit the nearest open
    'soft' surface (fairway) or become rough. Leaf-off photo: the ground shows through the bare crowns, so the
    classifier's labels stand - except 'native', which under trees is leaf litter / bare woodland floor (QA round 1:
    orange patches in the woods on every hole), i.e. wooded rough."""
    if leaf_off_photo:
        out = lab.copy()
        out[canopy & (lab == CID["native"])] = CID["rough"]
        return out
    open_lab = np.where(canopy, 0, lab)
    idx = ndimage.distance_transform_edt(open_lab == 0, return_distances=False, return_indices=True).astype(np.int32)
    near = open_lab[idx[0], idx[1]]
    soft = np.isin(near, [CID["fairway"], CID["native"]])
    return np.where(canopy, np.where(soft, near, CID["rough"]), lab).astype(np.uint8)


def is_deck(P, R, tol=0.06, max_slope=0.05, step=0.12, fill=0.2):
    """LiDAR signature of a built tee deck. P: ground points (N x 3) on the pad, R: a ring 1-4 m outside it. The pad fits
    a plane (std < `tol`, slope < `max_slope`), the ground around it leaves that plane by more than `step` m, and at
    least a fraction `fill` of the ring falls away *below* it (a fill bank or the downhill side of a cut-in deck).
    Without that last test flat natural ground at the bottom of a swale, or a flat strip beside a bank, read as decks
    (QA round 1, holes 7 and 18)."""
    m = P[:, :2].mean(0)
    A = np.c_[P[:, :2] - m, np.ones(len(P))]
    coef, *_ = np.linalg.lstsq(A, P[:, 2], rcond=None)
    resid = P[:, 2] - A @ coef
    ring_res = R[:, 2] - np.c_[R[:, :2] - m, np.ones(len(R))] @ coef
    return bool(resid.std() < tol and np.hypot(coef[0], coef[1]) < max_slope
                and np.percentile(np.abs(ring_res), 75) > step and np.mean(ring_res < -step) >= fill)


def off_course_paths(cartpath, road, course, margin=5.0):
    """Cart path more than `margin` m outside the golf_course boundary is a municipal sidewalk (OSM footways along the
    streets feed the path corridor): it becomes road, OPCD Concrete_Road (QA round 1, holes 7 and 11)."""
    if course.is_empty:
        return cartpath, road
    off = cartpath.difference(course.buffer(margin))
    if off.is_empty:
        return cartpath, road
    return cartpath.difference(off), unary_union([road, off])


def bunker_ok(p, osm_bunk, course, is_hollow, paved=None, buildings=None, kerb=1.0, wall=10.0):
    """Keep a bunker polygon: it overlaps a mapped (OSM) bunker, or it is a LiDAR hollow on the course (garden beds and
    sandpits in the neighbouring lots are hollows too). An empty `course` means no boundary is mapped. An unmapped
    bunker must also be `kerb` m clear of paved ground (OSM roads, parking) and `wall` m from buildings: bright bare
    concrete below a kerb or a bed along a wall is a hollow too (clubhouse drive and parking island, hole 12)."""
    if p.intersection(osm_bunk).area >= 0.3 * p.area:
        return True
    if paved is not None and not paved.is_empty and p.distance(paved) < kerb:
        return False
    if buildings is not None and not buildings.is_empty and p.distance(buildings) < wall:
        return False
    return (course.is_empty or course.intersection(p).area >= 0.5 * p.area) and is_hollow(p)


def held_water(z, basin):
    """Depth (m) of the water each cell of the DEM window z holds before it spills over the lowest way out of `basin`
    (bool; the cells outside it are outlets, and the window border is one). A morphological fill (reconstruction by
    erosion, 8-connected), with scipy: skimage's reconstruction sets an array's shape, deprecated in NumPy 2.5."""
    ok = np.isfinite(z)
    z = np.where(ok, z, z[ok].min() if ok.any() else 0.0)   # no ground: an outlet
    basin = basin.copy(); basin[[0, -1], :] = False; basin[:, [0, -1]] = False
    level, square = np.where(basin, z.max(), z), np.ones((3, 3), bool)
    while True:   # water drains to the lowest neighbour's level, never below the ground
        nxt = np.maximum(ndimage.grey_erosion(level, footprint=square), z)
        if np.array_equal(nxt, level):
            return level - z
        level = nxt


def closed_hollow(z, inside, basin, sunk, H=None, res=None):
    """Is an unmapped bunker's hollow closed or faced? At least H pond_frac of the polygon (`inside`, on the DEM window
    z, cells of `res` m) holds `pond` m of water before it spills out of `basin` (a bowl), or the polygon lies `face` m
    or more below the ring around it (`sunk`, m) and the ring is not open at both ends (open_both_ends): a bunker cut
    into a slope is open on its low side only but has a real face. An open channel (barranca floor, drainage ditch, path
    cut) drains along its length: 0.03-0.3 m below its banks on Brambles (QA round 1), and a deeper one, or a scour hole
    on a barranca thalweg, is open at both ends (round 3). H: BUNKER_HOLLOW ([tuning.bunker_hollow]); pond_frac 0 turns
    the test off."""
    H = BUNKER_HOLLOW if H is None else H
    if H["pond_frac"] <= 0:
        return True
    if sunk >= H["face"] and not open_both_ends(z, inside, basin, RES if res is None else res, H):
        return True
    return bool(inside.any()) and float(np.mean(held_water(z, basin)[inside] >= H["pond"])) >= H["pond_frac"]


def open_both_ends(z, inside, basin, res, H=None, floor_r=1.5, apart=120.0):
    """Is the ground round a polygon (`inside` on the DEM window z, cells of `res` m; the ring: `basin` outside it) open
    on two opposite sides, as a channel is at both ends? A ring cell is open when it lies less than H `open` m above
    either the floor next to it - the lowest polygon cell within `floor_r` m of the one nearest to it (a polygon takes
    in a lip up its faces) - or the plane fitted to the polygon's lower half (a channel's bed runs on at its slope). An
    outlet is a patch of open cells (8-connected, H `outlet` m2 or more) that leads out of the basin (reaches its outer
    edge); two outlets `apart` degrees or more apart seen from the polygon's centre are opposite ends. A bunker cut
    into a slope has one outlet, its low side. H: BUNKER_HOLLOW ([tuning.bunker_hollow])."""
    import math
    H = BUNKER_HOLLOW if H is None else H
    ok = np.isfinite(z)
    ring = basin & ~inside & ok
    floor = inside & ok
    if not ring.any() or floor.sum() < 3:
        return False
    rpx = max(1, int(round(floor_r / res)))
    yy, xx = np.mgrid[-rpx:rpx + 1, -rpx:rpx + 1]
    low = ndimage.grey_erosion(np.where(floor, z, np.inf), footprint=xx * xx + yy * yy <= rpx * rpx)
    iy, ix = ndimage.distance_transform_edt(~floor, return_distances=False, return_indices=True)
    fy, fx = np.nonzero(floor); fz = z[floor]; lo = fz <= np.median(fz)
    coef, *_ = np.linalg.lstsq(np.c_[fx[lo], fy[lo], np.ones(lo.sum())], fz[lo], rcond=None)
    YY, XX = np.mgrid[0:z.shape[0], 0:z.shape[1]]
    bed = coef[0] * XX + coef[1] * YY + coef[2]
    lab, n = ndimage.label(ring & ((z - low[iy, ix] < H["open"]) | (z - bed < H["open"])), structure=np.ones((3, 3)))
    if n < 2:
        return False
    out = ndimage.binary_dilation(~basin)
    cy, cx = fy.mean(), fx.mean()
    dirs = []
    for k in range(1, n + 1):
        m = lab == k
        if m.sum() * res * res >= H["outlet"] and (m & out).any():
            ry, rx = np.nonzero(m)
            dirs.append(math.degrees(math.atan2(cy - ry.mean(), rx.mean() - cx)))
    return any(abs((a - b + 180.0) % 360.0 - 180.0) >= apart for i, a in enumerate(dirs) for b in dirs[i + 1:])


def bunker_bowls(z, inside, basin, res, T=None):
    """The pans of a bunker polygon (bool mask of `inside` on the DEM window z), or None to leave it as it is: the
    cells below the rim around them (a grey closing with a `radius` m disc, minus the DEM, at least `depth` m) in the
    bowls that hold water (`seed` m before it spills out of `basin`, on seed_area m2 or more), widened by `lip` m up
    the faces. A bunker that holds no water (cut into a slope, open on its low side) has no pan to trim it to.
    T: BUNKER_TRIM ([tuning.bunker_trim]). For photos too coarse to separate the sand from the grass faces (Brambles'
    0.6 m NAIP: the 18th greenside polygon held two pans and the steep face above them)."""
    T = BUNKER_TRIM if T is None else T
    seeds = inside & (held_water(z, basin) >= T["seed"])
    lab, n = ndimage.label(seeds)
    if n:
        big = ndimage.sum(seeds, lab, range(1, n + 1)) * res * res >= T["seed_area"]
        seeds = np.r_[False, big][lab]
    if not seeds.any():
        return None
    rpx = max(1, int(round(T["radius"] / res)))
    yy, xx = np.mgrid[-rpx:rpx + 1, -rpx:rpx + 1]
    below = ndimage.grey_closing(z, footprint=xx * xx + yy * yy <= rpx * rpx) - z >= T["depth"]
    lab, n = ndimage.label(inside & (below | seeds))
    floor = ndimage.binary_fill_holes(np.isin(lab, np.unique(lab[seeds])))
    return ndimage.binary_dilation(floor, iterations=max(1, int(round(T["lip"] / res)))) & inside


def dem_points(dem, T, geom):
    """The cells of the DEM `dem` (north-up affine T) whose centres are inside geom: an N x 3 array of x, y, z."""
    from rasterio.features import geometry_mask
    from rasterio.windows import Window, transform as window_transform
    x0, y0, x1, y1 = geom.bounds
    c0 = max(0, int((x0 - T.c) / T.a) - 1); c1 = min(dem.shape[1], int((x1 - T.c) / T.a) + 2)
    r0 = max(0, int((T.f - y1) / -T.e) - 1); r1 = min(dem.shape[0], int((T.f - y0) / -T.e) + 2)
    if c1 <= c0 or r1 <= r0:
        return np.zeros((0, 3))
    tw = window_transform(Window(c0, r0, c1 - c0, r1 - r0), T)
    m = ~geometry_mask([geom], out_shape=(r1 - r0, c1 - c0), transform=tw)
    rr, cc = np.nonzero(m)
    return np.c_[tw.c + (cc + 0.5) * tw.a, tw.f + (rr + 0.5) * tw.e, dem[r0:r1, c0:c1][m]]


def dem_window(dem, T, p, pad):
    """The DEM `pad` m round polygon p (float64), its transform, p's cells and the basin water poured into p spills out
    of (p and the ground within 2.5 m of it: the ring is_hollow compares p with)."""
    from rasterio.features import geometry_mask
    from rasterio.windows import Window, transform as window_transform
    x0, y0, x1, y1 = p.bounds
    c0 = max(0, int((x0 - pad - T.c) / T.a) - 1); c1 = min(dem.shape[1], int((x1 + pad - T.c) / T.a) + 2)
    r0 = max(0, int((T.f - y1 - pad) / -T.e) - 1); r1 = min(dem.shape[0], int((T.f - y0 + pad) / -T.e) + 2)
    tw = window_transform(Window(c0, r0, c1 - c0, r1 - r0), T)
    z = dem[r0:r1, c0:c1].astype(np.float64)
    inside = ~geometry_mask([p], out_shape=z.shape, transform=tw)
    return z, tw, inside, ~geometry_mask([p.buffer(2.5)], out_shape=z.shape, transform=tw)


def _hollow_means(dem, T, p):
    """Mean DEM height inside p (inset 0.3 m) and on the ring 0.5-2.5 m round it, or None with under 8 cells in
    either."""
    inner = p.buffer(-0.3)
    P = dem_points(dem, T, inner if not inner.is_empty else p)
    R = dem_points(dem, T, p.buffer(2.5).difference(p.buffer(0.5)))
    return (P[:, 2].mean(), R[:, 2].mean()) if len(P) >= 8 and len(R) >= 8 else None


def is_hollow(dem, T, p, depth=0.08):
    """p lies `depth` m or more below the ground 0.5-2.5 m round it, on average (a bunker's LiDAR hollow)."""
    m = _hollow_means(dem, T, p)
    return m is not None and m[0] < m[1] - depth


def unmapped_hollow(dem, T, p, H=None):
    """The LiDAR test for a bunker no map has: is_hollow, and closed or faced (closed_hollow, H: [tuning.bunker_hollow]),
    because an open channel is lower than its banks too."""
    m = _hollow_means(dem, T, p)
    if m is None or not m[0] < m[1] - 0.08:
        return False
    z, _, inside, basin = dem_window(dem, T, p, 3.5)
    return closed_hollow(z, inside, basin, float(m[1] - m[0]), H, abs(T.a))


def is_drafted(t):
    """A feature draft_features drew from the photo (draft=yes in features/golf.geojson): a training label for a course
    OSM does not map, not survey data."""
    return t.get("draft") == "yes"


def survey_bunkers(G, buf=1.5):
    """The mapped bunkers (OSM's, and those drawn by hand in features/golf.geojson), `buf` m round them: a photo bunker
    over one skips the LiDAR test (bunker_ok). Drafted bunkers are not among them (Brambles: bare soil in the hole-7
    barranca and a hole-1 road cut, drafted as sand, kept their false bunkers)."""
    return unary_union([g for _, t, g in G if t.get("golf") == "bunker" and not is_drafted(t)]).buffer(buf)


def mapped_bunker_hollow(dem, T, g, t, course, paved=None, buildings=None, H=None):
    """May a mapped bunker the photo missed (in shade or under a crown) be added? Its LiDAR hollow must show (5 cm), and
    a drafted one (is_drafted) must pass the unmapped bunkers' tests (bunker_ok: on the course, clear of roads and
    buildings, a closed hollow; H: [tuning.bunker_hollow]), or what the LiDAR rejected as a photo bunker would come
    back here."""
    if is_drafted(t):
        return bunker_ok(g, Polygon(), course, lambda q: unmapped_hollow(dem, T, q, H), paved, buildings,
                         *BUNKER_CLEARANCE)
    return is_hollow(dem, T, g, 0.05)


def trims_bunkers(photo_res, Tr=None):
    """Are bunkers cut to their LiDAR pans (trim_faces) with a photo of `photo_res` m? Tr: BUNKER_TRIM
    ([tuning.bunker_trim] photo_res)."""
    return photo_res >= (BUNKER_TRIM if Tr is None else Tr)["photo_res"]


def trim_faces(dem, T, g, Tr=None):
    """Bunker polygons g cut to their LiDAR pans (bunker_bowls on the DEM `dem`, affine T), each pan a polygon of at
    least MIN_AREA["bunker"] m2; a polygon with no such pan is kept as it is. Tr: BUNKER_TRIM ([tuning.bunker_trim])."""
    Tr = BUNKER_TRIM if Tr is None else Tr
    out = []
    for p in polys_of(g):
        z, tw, inside, basin = dem_window(dem, T, p, max(2.5, Tr["radius"]) + 1.0)
        m = bunker_bowls(z, inside, basin, abs(T.a), Tr)
        parts = []
        if m is not None and m.any():
            q = unary_union([shape(s_) for s_, v in shapes(m.astype(np.uint8), mask=m, transform=tw, connectivity=8) if v == 1])
            parts = [r for r in polys_of(make_valid(smooth_poly(q, close=0.2)).intersection(p)) if r.area >= MIN_AREA["bunker"]]
        out.extend(parts or [p])
    return unary_union(out) if out else Polygon()


def sand_mask(L, a, b, ndvi=None, green=None, parts=False):
    """Bunker sand in the photo: bright, slightly yellow, low chroma - or, with a NIR band, bare (NDVI ~0) and not black,
    which also catches sand in the branch shadows of a leaf-off photo (NDVI is a band ratio, shadows barely move it).
    Shadow sand is only kept where it connects to sunlit sand (hysteresis): alone, the shadow rule also takes bare soil,
    shaded roofs and pavement (build 4: 61 off-course 'bunkers'). Dormant greens are pale too, but NDVI ~0.05-0.14: kept
    out by the NDVI cut and the mapped-green mask. parts=True returns (sunlit, shadow) for a hysteresis over a mosaic.
    Thresholds: SAND and SHADOW_SAND ([tuning.sand], [tuning.shadow_sand])."""
    s, w = SAND, SHADOW_SAND
    strong = (L > s["L_min"]) & (a > s["a_min"]) & (b > s["b_min"]) & (b < s["b_max"])
    weak = np.zeros_like(strong)
    if ndvi is not None:
        strong &= ndvi < s["ndvi_max"]
        weak = (ndvi < w["ndvi_max"]) & (L > w["L_min"]) & (a > w["a_min"]) & (b > w["b_min"])
    if green is not None:
        strong &= ~green; weak &= ~green
    return (strong, weak) if parts else sand_hysteresis(strong, weak)


def turf_mask(a, ndvi=None):
    """Clearly green turf (bunker grass faces) or tree crowns in the photo: sand sits near a* -3. In a spring photo turf
    is rarely that green, but live turf is NDVI > 0.25 and sand ~0. Thresholds: TURF ([tuning.turf])."""
    m = a < TURF["a_max"]
    return m | (ndvi > TURF["ndvi_min"]) if ndvi is not None else m


def sand_hysteresis(strong, weak):
    """strong, plus every connected (8-neighbour) component of strong | weak that contains strong pixels."""
    lab, n = ndimage.label(strong | weak, structure=np.ones((3,) * strong.ndim))
    if not n:
        return strong.copy()
    keep = np.zeros(n + 1, bool); keep[np.unique(lab[strong])] = True; keep[0] = False
    return keep[lab]


def split_shared_greens(greens, ends, pins, reach=4.0, pin_near=8.0):
    """[(green polygon, hole)] in the order of `greens`. A green belongs to the hole whose line of play ends in it
    (within `reach` m, or a golf=pin in it within pin_near m of the end); one that holds the ends of several holes (a
    double green, or neighbouring greens the classifier joined: Brambles 3 and 14) is split between them along the
    Voronoi cells of their ends. No end: hole 99. ends: {hole: Point}."""
    from shapely.geometry import MultiPoint
    from shapely.ops import voronoi_diagram
    out = []
    for p in greens:
        zone = p.buffer(reach)
        mine = [(ref, e) for ref, e in sorted(ends.items())
                if zone.contains(e) or any(zone.contains(q) and q.distance(e) < pin_near for q in pins)]
        if len(mine) < 2:
            out.append((p, mine[-1][0] if mine else 99))
            continue
        cells = voronoi_diagram(MultiPoint([e for _, e in mine]), envelope=p.envelope.buffer(50))
        for ref, e in mine:
            cell = next(c for c in cells.geoms if c.contains(e))
            for q in polys_of(p.intersection(cell)):
                out.append((q, ref))
    return out


def runs_along(line, p, min_run=None, reach=None):
    """Does a line of play run along fairway polygon p, so that it may take a part of it? At least `min_run` m of the
    line lie inside p (default [tuning] shared_fairway_min_run), or its green end (the line's last point) is within
    `reach` m of p (shared_fairway_green_reach: the approach and green surround of a par 3). A line that only crosses p
    does not: a tee shot over another hole's fairway or green surround (Brambles: the tees of holes 7, 9, 12, 16 and 17
    sit by other holes' greens), or a dogleg over its corner, unless its green end is within `reach` (a par 3 played
    over another fairway to a green beside it: it takes a part)."""
    min_run = SHARED_FAIRWAY_MIN_RUN if min_run is None else min_run
    reach = SHARED_FAIRWAY_GREEN_REACH if reach is None else reach
    run = line.intersection(p).length
    return run > 0 and (run >= min_run or Point(line.coords[-1]).distance(p) <= reach)


def split_shared_fairways(fairways, lines, min_part=None, step=2.0, min_run=None, reach=None):
    """[(fairway polygon, hole or None)] in the order of `fairways`. A fairway polygon that the lines of play of several
    holes run along (runs_along; connected zoysia: Brambles' 13th polygon also held the whole 14th and 5th fairways,
    and its 18th fairway was part of the 1st's) is split between them along the boundaries of their corridors in it:
    the Voronoi cells of the lines' points (every `step` m) inside it or within `step` m of it, each part to its hole.
    A line whose part would be under `min_part` m2 (a green or tee beside the fairway, default [tuning]
    shared_fairway_min_part) takes none, and nor does a line that only crosses the polygon. When only one of the lines
    through it runs along it, the whole polygon is that line's hole (the nearest-line rule could give it to a line
    crossing its middle). None: at most one line runs through the polygon, or none runs along it; it is assigned as
    before, to the nearest line. lines: {course hole: LineString}; hole 99 (no course hole) takes no part."""
    from shapely.geometry import MultiPoint
    from shapely.ops import voronoi_diagram
    from shapely import STRtree, segmentize
    min_part = SHARED_FAIRWAY_MIN_PART if min_part is None else min_part
    out = []
    for p in fairways:
        through = [h for h, l in sorted(lines.items()) if h != 99 and l.intersects(p) and l.intersection(p).length > 0]
        cand = {h: lines[h] for h in through if runs_along(lines[h], p, min_run, reach)}
        near = p.buffer(step)
        parts = {}
        while len(cand) >= 2:
            pts, own = [], []
            for h, l in cand.items():
                l = l.intersection(near)
                for g in getattr(l, "geoms", [l]):
                    if g.geom_type == "LineString":
                        for c in segmentize(g, step).coords:
                            pts.append(Point(c)); own.append(h)
            tree = STRtree(pts)
            cells = {h: [] for h in cand}
            for c in voronoi_diagram(MultiPoint(pts), envelope=p.envelope.buffer(50)).geoms:
                i = tree.query(c, predicate="contains")
                if len(i):
                    cells[own[min(i)]].append(c)
            # each cell made valid first: Voronoi sites on an exact lattice give cells the union cannot join
            parts = {h: p.intersection(unary_union([make_valid(c) for c in cs])) for h, cs in cells.items()}
            small = min(parts, key=lambda h: parts[h].area)
            if parts[small].area >= min_part:
                break
            del cand[small]; parts = {}
        if len(parts) < 2:
            out.append((p, next(iter(cand)) if len(cand) == 1 and len(through) > 1 else None))
            continue
        # a shard the corridor boundary cuts off a ragged edge (smaller than any fairway part vectorize keeps) joins
        # the piece it shares the longest edge with
        speck = 0.25 * MIN_AREA["fairway"]
        pieces = sorted(((r, h) for h, q in parts.items() for r in polys_of(q)), key=lambda x: -x[0].area)
        keep = [[r, h] for r, h in pieces if r.area >= speck]
        for r, h in pieces:
            if r.area >= speck:
                continue
            edge = max(((r.boundary.intersection(k[0].boundary).length, i) for i, k in enumerate(keep)), default=(0, 0))
            if edge[0] > 0:
                keep[edge[1]][0] = keep[edge[1]][0].union(r)
            else:
                keep.append([r, h])
        out.extend((r, h) for r, h in keep)
    return out


def nearest_line(p, holes, lim, end=None):
    """The hole whose line of play ({hole: LineString}) is nearest p's representative point, or 99 when none is within
    `lim` m. end="start": tee pads, which sit behind / along the first part of the line (forward tees can be far up it):
    the line is extended 35 m back past its tee, and a pad past FORWARD_TEE_FRAC of it counts 400 m further per unit
    of the fraction past it (a pad that far up a hole is not its tee)."""
    c = p.representative_point(); best, bd = 99, 1e9
    for ref, line in holes.items():
        if end == "start":
            a = np.asarray(line.coords[0]); b = np.asarray(line.coords[1]); u = (b - a) / np.linalg.norm(b - a)
            ext = LineString([a - 35 * u] + list(line.coords))
            d = c.distance(ext)
            frac = ext.project(c) / ext.length
            d += max(0.0, frac - FORWARD_TEE_FRAC) * 400
        else:
            d = c.distance(line)
        if d < bd:
            best, bd = ref, d
    return best if bd < lim else 99


def card_tee_hole(p, holes, cards, reach=None, tol=None, clear=0.5):
    """The hole of a mapped tee pad p that nearest_line leaves to no hole (99): an OSM forward tee beside the line of
    play (Deer Ridge holes 1, 3 and 8: 42-46 m off it) or a par 3's forward deck past FORWARD_TEE_FRAC of its line
    (Deer Ridge 13, Whistle Bear 5, 14 and 17, Brambles 12). A hole may take it when its line, extended 35 m back
    past the tee, is within `reach` m (FORWARD_TEE_REACH) of p's representative point, and p plays its card: the play
    distance (hole_data.play_distance, to the line's end) is within `tol` yd (FORWARD_TEE_CARD_TOL) of the hole's
    shortest to longest yardage (cards: {hole: yardages}; a hole without a card takes no tee). The nearest such hole
    takes it if every other one is more than 1 / `clear` times as far; otherwise, or with none, it stays 99 (a
    driving-range tee, a pad that plays no hole's card)."""
    from hole_data import play_distance, YD
    reach = FORWARD_TEE_REACH if reach is None else reach
    tol = FORWARD_TEE_CARD_TOL if tol is None else tol
    c = p.representative_point(); xy = c.coords[0]
    fits = []
    for ref, line in holes.items():
        card = cards.get(ref)
        if not card or ref == 99:
            continue
        a = np.asarray(line.coords[0]); b = np.asarray(line.coords[1]); u = (b - a) / np.linalg.norm(b - a)
        d = c.distance(LineString([a - 35 * u] + list(line.coords)))
        yards = play_distance(xy, [tuple(q) for q in line.coords[1:-1]], line.coords[-1]) * YD
        if d <= reach and min(card) - tol <= yards <= max(card) + tol:
            fits.append((d, ref))
    fits.sort()
    if not fits or (len(fits) > 1 and fits[0][0] > clear * fits[1][0]):
        return 99
    return fits[0][1]


def green_keep_area(course_area, osm_greens, margin=None):
    """Where the classifier's greens are kept: within `margin` m (GREEN_OFF_COURSE) of the course outline, or on an
    OSM-mapped green (a practice green off the outline). Off the course its "green" is a lawn, a sports field or a
    driving range: Deer Ridge's spring photo made 18 ha of park lawn round the course green, Whistle Bear's 5 ha. None
    (keep every green) for a course without an outline."""
    if course_area.is_empty:
        return None
    margin = GREEN_OFF_COURSE if margin is None else margin
    return unary_union([course_area.buffer(margin)] + [g for g in osm_greens if not g.is_empty])


def is_court(t):
    """OSM tags of a sports pitch or a tennis court (the court surface). A golf feature mapped as a pitch is not one:
    Deer Ridge maps hole 1's green and four tees golf=green / golf=tee + leisure=pitch + sport=golf, and a court erases
    the greens and tees under it."""
    if "golf" in t or t.get("sport") == "golf":
        return False
    return t.get("leisure") == "pitch" or t.get("sport") == "tennis"


def osm_vectors(G):
    """OSM-authoritative non-golf surfaces ({road, building, court, water: [polygons]}), the service roads and tracks
    that run inside the golf course, which are cart paths (GSPro surface: cart path, hole 98), and the course area.
    Roads are the highway classes of ROAD_HALF_WIDTH, drawn that wide each side of the centre line. A track or service
    way inside the course mapped as grass or earth (TURF_TRACK: mown maintenance routes) is left to the turf."""
    osm = lambda pred: [g for _, t, g in G if pred(t)]
    course_area = unary_union(osm(lambda t: t.get("leisure") == "golf_course"))
    roads, course_tracks = [], []
    for _, t, g in G:
        hw = t.get("highway")
        if hw in ROAD_HALF_WIDTH and g.geom_type == "LineString":
            if hw in ("service", "track") and not course_area.is_empty and g.intersection(course_area).length > 0.6 * g.length:
                if not turf_track(t):
                    course_tracks.append(g.buffer(1.4, cap_style=1))
                continue
            roads.append(g.buffer(ROAD_HALF_WIDTH[hw], cap_style=2))
    roads += osm(lambda t: t.get("amenity") == "parking")
    vector = {
        "road": [g for g in roads if g.geom_type in ("Polygon", "MultiPolygon")],
        "building": [g for g in osm(lambda t: "building" in t) if g.geom_type in ("Polygon", "MultiPolygon")],
        "court": [g for g in osm(is_court) if g.geom_type in ("Polygon", "MultiPolygon")],
        "water": [g for g in osm(lambda t: t.get("leisure") == "swimming_pool" or is_water(t))
                  if g.geom_type in ("Polygon", "MultiPolygon")],
    }
    return vector, course_tracks, course_area


def chaikin(coords, n=2):
    pts = np.asarray(coords)[:-1]
    for _ in range(n):
        q = 0.75 * pts + 0.25 * np.roll(pts, -1, 0)
        r = 0.25 * pts + 0.75 * np.roll(pts, -1, 0)
        pts = np.empty((2 * len(q), 2)); pts[0::2] = q; pts[1::2] = r
    return np.vstack([pts, pts[:1]])


def smooth_poly(g, close=0.3, simp=0.08, iters=2):
    g = g.buffer(close, join_style=1).buffer(-close, join_style=1)
    g = g.simplify(simp)
    out = []
    for p in getattr(g, "geoms", [g]):
        if p.is_empty or p.geom_type != "Polygon":
            continue
        ext = chaikin(p.exterior.coords, iters)
        ints = [chaikin(r.coords, iters) for r in p.interiors if Polygon(r).area > 1.0]
        q = make_valid(Polygon(ext, ints))
        out.append(q)
    return unary_union(out) if out else Polygon()


def polys_of(geom):
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon" and not g.is_empty]


def main():
    W, H, T = grid()
    from surface_classify import load_proba
    G = osm_geoms()
    def osm(pred):
        return [g for _, t, g in G if pred(t)]
    def burn_mask(geoms):
        geoms = [g for g in geoms if not g.is_empty]
        if not geoms:
            return np.zeros((H, W), bool)
        return rasterize([(g, 1) for g in geoms], out_shape=(H, W), transform=T, fill=0, dtype="uint8").astype(bool)

    # 1) golf ground surfaces from the classifier (only the classes it is reliable for); running argmax keeps
    #    memory at two float32 grids whatever the extent
    golf = ["green", "fairway", "tee", "bunker", "rough", "native", "cartpath"]
    best = np.full((H, W), -1.0, np.float32); lab = np.zeros((H, W), np.uint8)
    for n in golf:
        pc = ndimage.gaussian_filter(load_proba(CID[n]), 1.2)
        upd = pc > best
        best[upd] = pc[upd]; lab[upd] = CID[n]
        del pc, upd
    del best
    p_tree = ndimage.gaussian_filter(load_proba(CID["tree"]), 1.2)

    # 2) under tree canopy the photo cannot see the ground: inherit from the nearest open pixel,
    #    but only "soft" surfaces (fairway / native / rough) may propagate.
    chm = rasterio.open(C.BUILD / "chm.tif").read(1)
    chm = np.kron(chm, np.ones((2, 2), np.float32))[:H, :W]
    canopy = ndimage.binary_dilation(ndimage.gaussian_filter(chm, 1.0) > 1.5, iterations=2)
    canopy |= p_tree > 0.5
    # chaparral / brush: dense low canopy (0.6-5 m) with little tall-tree cover -> "deeprough" (OPCD Deep Rough).
    # Under tall trees (> 5 m) the understorey is usually mown rough, so those stay with their ground class.
    chm_s = ndimage.gaussian_filter(chm, 2.0)
    shrub_cov = ndimage.gaussian_filter(((chm_s > 0.6) & (chm_s < 5.0)).astype(np.float32), 3.0 / RES)
    tall_cov = ndimage.gaussian_filter((chm_s >= 5.0).astype(np.float32), 3.0 / RES)
    brush = (shrub_cov > 0.55) & (tall_cov < 0.5)
    del chm, p_tree, chm_s, shrub_cov, tall_cov
    if C.IMAGERY_LEAF_OFF:
        # litter test on the closed canopy (the leaf-off CHM is full of holes between bare branches)
        from detect_trees import smooth_chm
        c05 = rasterio.open(C.BUILD / "chm.tif").read(1)
        wide = np.kron(smooth_chm(c05, 0.5) > 2.0, np.ones((2, 2), bool))[:H, :W]
        lab = under_canopy_labels(lab, ndimage.binary_dilation(wide, iterations=int(2.0 / RES)), True)
        del c05, wide
    else:
        lab = under_canopy_labels(lab, canopy, False)

    surf = {n: np.zeros((H, W), bool) for n in PRIORITY}
    for n in ("green", "bunker", "tee", "fairway", "native"):
        surf[n] = lab == CID[n]

    # bunkers: the classifier (trained on generous OSM outlines) bleeds onto the grass faces; sand itself is
    # unambiguous in the photo (bright, slightly yellow, low chroma), so use colour near mapped/classified bunkers
    from surface_classify import read_on_grid
    from rasterio.enums import Resampling
    from skimage.color import rgb2lab
    from surface_classify import read_imagery_window, read_nir_window
    sand = np.zeros((H, W), bool); shade_sand = np.zeros((H, W), bool)
    grass = np.zeros((H, W), bool)
    osm_green = burn_mask([g.buffer(0.5) for g in osm(lambda t: t.get("golf") == "green") if g.geom_type == "Polygon"])
    for r0 in range(0, H, 1024):
        r1 = min(H, r0 + 1024)
        rgb = read_imagery_window(T, r0, r1, 0, W)
        Lab = rgb2lab(np.moveaxis(rgb, 0, -1))
        nir = read_nir_window(T, r0, r1, 0, W)
        ndvi = (nir - rgb[0]) / (nir + rgb[0] + 1e-3) if nir is not None else None
        sand[r0:r1], shade_sand[r0:r1] = sand_mask(Lab[..., 0], Lab[..., 1], Lab[..., 2], ndvi,
                                                   osm_green[r0:r1] if ndvi is not None else None, parts=True)
        grass[r0:r1] = turf_mask(Lab[..., 1], ndvi)
    del Lab, osm_green
    sand = sand_hysteresis(sand, shade_sand); del shade_sand
    osm_bunk = burn_mask(osm(lambda t: t.get("golf") == "bunker"))
    near = ndimage.binary_dilation(surf["bunker"] | osm_bunk, iterations=int(6 / RES))
    path_lines0 = [g for _, t, g in G if g.geom_type == "LineString" and
                   (t.get("golf") == "cartpath" or t.get("golf_cart") == "yes" or t.get("highway") in ("path", "footway"))]
    # (the raw classifier "cart path" class is over-predicted course-wide, so only trust it next to a mapped path)
    on_path = burn_mask([g.buffer(1.5) for g in path_lines0]) | ((lab == CID["cartpath"]) & burn_mask([g.buffer(3.0) for g in path_lines0]))
    # second route for darker / shaded sand: a confident classifier bunker inside a mapped bunker (validated below)
    p_bunk = ndimage.gaussian_filter(load_proba(CID["bunker"]), 1.2)
    mapped = (p_bunk > 0.85) & ndimage.binary_dilation(osm_bunk, iterations=int(1.5 / RES))
    del p_bunk
    # (leaf-off photo: the sand under bare branches is visible - keep it, the shadow-sand rule found it)
    hidden = np.zeros_like(canopy) if C.IMAGERY_LEAF_OFF else canopy
    surf["bunker"] = ndimage.binary_opening(ndimage.binary_closing(((sand & near) | mapped) & ~hidden & ~on_path, iterations=2),
                                            iterations=1)
    # ...but never onto clearly green turf: the classifier route and the closing spilled 1-2 m onto the grass faces of
    # greenside bunkers (QA round 2). Under canopy the photo shows crowns, so the trim only applies in the open.
    grass = (ndimage.gaussian_filter(grass.astype(np.float32), 0.25 / RES) > 0.5) & ~hidden
    surf["bunker"] = ndimage.binary_opening(surf["bunker"] & ~grass, iterations=1)

    # 3) cart paths: classifier evidence near mapped OSM paths, plus the OSM centre-line under canopy
    path_lines = [g for _, t, g in G if g.geom_type == "LineString" and
                  (t.get("golf") == "cartpath" or t.get("golf_cart") == "yes" or t.get("highway") in ("path", "footway"))
                  and t.get("bridge") != "yes"]
    corridor = burn_mask([g.buffer(3.0) for g in path_lines])
    backbone = burn_mask([g.buffer(1.1, cap_style=1) for g in path_lines])
    surf["cartpath"] = ((lab == CID["cartpath"]) & corridor) | (backbone & canopy)
    # stray classifier "path" pixels away from mapped paths are just worn turf -> rough
    # 4) OSM-authoritative non-golf features
    vector, course_tracks, course_area = osm_vectors(G)
    for n, gs in vector.items():
        surf[n] = burn_mask(gs)
    if course_tracks:
        surf["cartpath"] |= burn_mask(course_tracks)
    for n in ("green", "bunker", "tee", "fairway", "native", "cartpath"):
        surf[n] &= ~(surf["road"] | surf["building"] | surf["court"])
    # deep rough never touches maintained turf directly (keep >= 3 m of rough between)
    turf = surf["green"] | surf["tee"] | surf["fairway"] | surf["bunker"]
    surf["deeprough"] = brush & ~ndimage.binary_dilation(turf, iterations=int(3 / RES)) & \
        ~(surf["road"] | surf["building"] | surf["court"] | surf["water"] | surf["cartpath"])
    del brush, turf

    # morphological clean-up
    def clean(m, min_area, fill_holes=None, open_px=0, close_px=0):
        if close_px:
            m = ndimage.binary_closing(m, iterations=close_px)
        if open_px:
            m = ndimage.binary_opening(m, iterations=open_px)
        lab_, n = ndimage.label(m)
        if n:
            areas = ndimage.sum(np.ones_like(m), lab_, range(1, n + 1)) * RES * RES
            keep = np.zeros(n + 1, bool); keep[1:] = areas >= min_area
            m = keep[lab_]
        if fill_holes is not None:
            holes = ndimage.binary_fill_holes(m) & ~m
            hl, hn = ndimage.label(holes)
            if hn:
                ha = ndimage.sum(np.ones_like(m), hl, range(1, hn + 1)) * RES * RES
                small = np.zeros(hn + 1, bool); small[1:] = ha <= fill_holes
                m = m | small[hl]
        return m
    keep = green_keep_area(course_area, [g for g in osm(lambda t: t.get("golf") == "green")
                                         if g.geom_type in ("Polygon", "MultiPolygon")])
    if keep is not None:
        surf["green"] &= burn_mask([keep])
    surf["green"] = clean(surf["green"], MIN_AREA["green"], fill_holes=1e9, open_px=2)
    surf["bunker"] = clean(surf["bunker"], MIN_AREA["bunker"], fill_holes=1e9, open_px=1)
    surf["tee"] = clean(surf["tee"], MIN_AREA["tee"], fill_holes=1e9, open_px=2)
    surf["fairway"] = clean(surf["fairway"], MIN_AREA["fairway"], fill_holes=12, open_px=2, close_px=2)
    surf["cartpath"] = clean(surf["cartpath"], MIN_AREA["cartpath"], fill_holes=2, close_px=2)
    surf["native"] = clean(surf["native"], MIN_AREA["native"], fill_holes=20, open_px=2, close_px=2)
    surf["deeprough"] = clean(surf["deeprough"], MIN_AREA["deeprough"], fill_holes=40, open_px=3, close_px=3)

    def to_geom(m):
        if not m.any():
            return Polygon()
        gs = [shape(s) for s, v in shapes(m.astype(np.uint8), mask=m, transform=T, connectivity=8) if v == 1]
        return unary_union(gs)

    from rasterio.features import geometry_mask
    from rasterio.windows import Window as RWindow, transform as window_transform
    with rasterio.open(C.BUILD / "dem.tif") as ds:
        demv = ds.read(1); Tv = ds.transform
    # a photo too coarse to separate the sand from the grass faces (Brambles' 0.6 m NAIP): bunkers are cut to their
    # LiDAR pans (bunker_bowls); the faces go to the surfaces below in PRIORITY, else rough
    trim_bunkers = trims_bunkers(C.IMAGERY_RES)

    aoi = box(C.CORE["xmin"], C.CORE["ymin"], C.CORE["xmax"], C.CORE["ymax"])
    final = {}
    taken = Polygon()
    for n in PRIORITY:
        g = to_geom(surf[n])
        if n in vector:  # OSM vector geometry (exact edges), not the rasterised mask
            g = unary_union([make_valid(x) for x in vector[n]]).buffer(0)
        elif n in ("road", "building", "court"):
            g = g.buffer(0.2, join_style=2).buffer(-0.2, join_style=2).simplify(0.2)
        elif n == "cartpath":
            g = smooth_poly(g, close=0.4, simp=0.1)
        else:
            g = smooth_poly(g, close=0.35 if n != "bunker" else 0.2)
        g = make_valid(g).intersection(aoi).difference(taken)
        if n == "bunker" and trim_bunkers:
            n0 = len(polys_of(g)); a0 = g.area
            g = trim_faces(demv, Tv, g)
            print(f"bunker trim (photo {C.IMAGERY_RES} m): {n0} bunkers, {a0:.0f} m2 -> {len(polys_of(g))} pans, "
                  f"{g.area:.0f} m2", flush=True)
        g = unary_union([p for p in polys_of(g) if p.area >= max(1.0, 0.25 * MIN_AREA.get(n, 1))])
        final[n] = g
        taken = unary_union([taken, g])
    # lines of play (course hole numbers) for tee validation and hole assignment
    holes = {}  # course hole number (config.course_hole) -> line of play
    for _, t, g in G:
        if t.get("golf") == "hole" and t.get("ref") and g.geom_type == "LineString":
            holes[C.course_hole(t["ref"])] = g
    # LiDAR / OSM validation of the small features the photo classifier over-predicts (QA round 1 found many):
    # a tee must overlap a mapped tee or be a built, flat deck; a bunker must overlap a mapped bunker or be a hollow.
    osm_tees = unary_union(osm(lambda t: t.get("golf") == "tee")).buffer(2.0)
    osm_bunk = survey_bunkers(G)   # drafted bunkers (draft=yes) are not survey data: they get the LiDAR test
    def mapped_tee(p):
        return p.intersection(osm_tees).area >= 0.25 * p.area
    def tee_ok(p):
        if mapped_tee(p):
            return True
        if p.area < 40:
            return False
        inner = p.buffer(-0.5)
        P = dem_points(demv, Tv, inner if not inner.is_empty else p)
        R = dem_points(demv, Tv, p.buffer(4.0).difference(p.buffer(1.0)))
        if len(P) < 30 or len(R) < 30:
            return False
        return is_deck(P, R)
    def trim_grass(g):
        """Remove clearly green turf (outside canopy) from a mapped bunker outline (OSM outlines include the faces)."""
        if g.is_empty:
            return g
        c0, r0 = ~T * (g.bounds[0], g.bounds[3]); c1, r1 = ~T * (g.bounds[2], g.bounds[1])
        c0, r0 = max(0, int(c0) - 1), max(0, int(r0) - 1); c1, r1 = min(W, int(c1) + 2), min(H, int(r1) + 2)
        tw = window_transform(RWindow(c0, r0, c1 - c0, r1 - r0), T)
        m = ~geometry_mask([g], out_shape=(r1 - r0, c1 - c0), transform=tw) & ~grass[r0:r1, c0:c1]
        m = ndimage.binary_opening(m, iterations=1)
        if not m.any():
            return Polygon()
        gs = [shape(s_) for s_, v in shapes(m.astype(np.uint8), mask=m, transform=tw, connectivity=8) if v == 1]
        return make_valid(smooth_poly(unary_union(gs), close=0.2)).intersection(g)
    course_buf = course_area.buffer(5.0) if not course_area.is_empty else course_area
    fair = final["fairway"]
    path_corr = unary_union([g.buffer(2.5) for g in path_lines0]) if path_lines0 else Polygon()
    keep_t, to_fair, keep_b, to_path, dropped = [], [], [], [], 0
    for p in polys_of(final["tee"]):
        # a flat deck that is no hole's tee (lawn, terrace, court apron) is not a tee (QA round 2)
        if tee_ok(p) and (mapped_tee(p) or nearest_line(p, holes, 40, "start") != 99):
            keep_t.append(p); continue
        ring = p.buffer(1.5).difference(p)
        (to_fair if ring.intersection(fair).area > 0.5 * ring.area else []).append(p); dropped += 1
    paved = unary_union([make_valid(x) for x in vector["road"]]) if vector["road"] else Polygon()
    bldgs = unary_union([make_valid(x) for x in vector["building"]]) if vector["building"] else Polygon()
    for p in polys_of(final["bunker"]):
        if bunker_ok(p, osm_bunk, course_buf, lambda q: unmapped_hollow(demv, Tv, q), paved, bldgs, *BUNKER_CLEARANCE):
            keep_b.append(p); continue
        (to_path if p.intersection(path_corr).area > 0.5 * p.area else []).append(p); dropped += 1
    print(f"validation: tees kept {len(keep_t)}, bunkers kept {len(keep_b)}, rejected {dropped} "
          f"({len(to_fair)} -> fairway, {len(to_path)} -> cart path, rest -> rough)", flush=True)
    # mapped bunkers the photo cannot see (shade, canopy) are kept when the LiDAR shows the hollow
    kb = unary_union(keep_b) if keep_b else Polygon()
    blockers = unary_union([final[n] for n in ("water", "green", "tee", "cartpath", "road", "building", "court")])
    added = 0
    for _, t, g in G:
        if t.get("golf") != "bunker" or g.geom_type != "Polygon" or not g.intersects(aoi):
            continue
        g = make_valid(g).buffer(0)
        if g.intersection(kb).area >= 0.3 * g.area or not mapped_bunker_hollow(demv, Tv, g, t, course_buf, paved, bldgs):
            continue
        add = trim_grass(g.difference(blockers).difference(kb))
        if trim_bunkers and not add.is_empty:
            add = trim_faces(demv, Tv, add)
        if add.area > 4:
            keep_b.extend(polys_of(add)); added += 1
            for n in ("fairway", "native", "deeprough"):
                final[n] = final[n].difference(add)
    print(f"validation: {added} mapped bunkers added from OSM (LiDAR hollow confirmed)", flush=True)
    final["tee"] = unary_union(keep_t) if keep_t else Polygon()
    final["bunker"] = unary_union(keep_b) if keep_b else Polygon()
    if to_fair:
        final["fairway"] = unary_union([final["fairway"]] + to_fair)
    if to_path:
        final["cartpath"] = unary_union([final["cartpath"]] + to_path)
    final["cartpath"], final["road"] = off_course_paths(final["cartpath"], final["road"], course_area)

    # greens: clear banks (LiDAR slope > 12 %) in the outer 2.5 m of a green outline are not putting surface
    # (photo outlines can include a mown bank); tilted greens and interior tier slopes are left alone
    gm = burn_mask(polys_of(final["green"]))
    zs = ndimage.gaussian_filter(demv.astype(np.float32), 3.0)
    gy_, gx_ = np.gradient(zs, RES)
    ring = gm & (ndimage.distance_transform_edt(gm) * RES <= 2.5)
    trim = (np.hypot(gx_, gy_) > 0.12) & ring
    del zs, gy_, gx_, ring
    trim = ndimage.binary_opening(trim, iterations=1)
    lab_t, nt = ndimage.label(trim)
    if nt:
        areas = ndimage.sum(trim, lab_t, range(1, nt + 1)) * RES * RES
        trim = np.isin(lab_t, np.flatnonzero(areas >= 5.0) + 1)
    if trim.any():
        tg = unary_union([shape(s_) for s_, v in shapes(trim.astype(np.uint8), mask=trim, transform=T) if v == 1])
        tg = tg.buffer(0.25).buffer(-0.25)
        before = final["green"].area
        newg = unary_union([q for q in polys_of(final["green"].difference(tg)) if q.area > 30])
        moved = final["green"].difference(newg)
        final["green"] = newg
        final["fairway"] = unary_union([final["fairway"], moved])
        print(f"green trim: {before - newg.area:.0f} m2 of steep bank moved from green to approach", flush=True)

    # derived rings carved from lower-priority surfaces
    green = final["green"]
    fringe = green.buffer(1.0, join_style=1).difference(green)
    for n in ("bunker", "tee", "water", "cartpath", "road", "building", "court"):
        fringe = fringe.difference(final[n])
    final["fairway"] = final["fairway"].difference(fringe)
    final["native"] = final["native"].difference(fringe)
    final["fringe"] = fringe.intersection(aoi)
    taken = unary_union(list(final.values()))
    semi = final["fairway"].buffer(1.5, join_style=1).difference(taken)
    final["semirough"] = semi.intersection(aoi)

    # drop slivers / specks; whatever is dropped becomes rough so the partition stays gap-free
    def keep_part(p, n):
        if p.area < MIN_AREA.get(n, 0.5) * (0.25 if n in ("fringe", "semirough") else 1.0):
            return False
        thin = {"fringe": 0.1, "semirough": 0.15, "cartpath": 0.3, "road": 0.8, "building": 0.8}.get(n, 0.3)
        return not p.buffer(-thin).is_empty
    for n in list(final):
        final[n] = unary_union([p for p in polys_of(final[n]) if keep_part(p, n)])
    final["rough"] = aoi.difference(unary_union(list(final.values())))
    # tiny rough / semirough islands (< 15 m2) inside other surfaces render as odd patches: merge each into the
    # neighbouring surface it shares the most boundary with
    from shapely import STRtree
    merged_n = 0
    for small_s in ("rough", "semirough"):
        keep_parts = []
        for q in polys_of(final[small_s]):
            if q.area >= 15:
                keep_parts.append(q); continue
            ring = q.buffer(0.3).difference(q)
            best, best_a = None, 0.0
            for n2 in ("fairway", "fringe", "semirough", "rough", "native", "deeprough", "tee"):
                if n2 == small_s or final.get(n2) is None or final[n2].is_empty:
                    continue
                a = ring.intersection(final[n2]).area
                if a > best_a:
                    best, best_a = n2, a
            if best is not None and best_a > 0.5 * ring.area:
                final[best] = unary_union([final[best], q]); merged_n += 1
            else:
                keep_parts.append(q)
        final[small_s] = unary_union(keep_parts) if keep_parts else Polygon()
    print(f"merged {merged_n} tiny rough/semirough islands into their surroundings", flush=True)

    # hole assignment
    cards = {h: v[1:] for h, v in C.SCORECARD.items()}   # yardages per tee set
    pins = [g for _, t, g in G if t.get("golf") == "pin" and g.geom_type == "Point"]
    green_hole = split_shared_greens(polys_of(final["green"]), {ref: Point(l.coords[-1]) for ref, l in holes.items()}, pins)
    def nearest_green(p, maxd):
        best = (None, 1e9)
        for g, h in green_hole:
            d = g.distance(p)
            if d < best[1]:
                best = (h, d)
        return best[0] if best[1] <= maxd else None
    def assign(p, n):
        if n == "cartpath":
            return 98
        if n in ("rough", "road", "building", "court", "native", "semirough", "water", "deeprough"):
            return 99
        if n == "green":
            return next(h for g, h in green_hole if g.equals(p))   # (greens are emitted from green_hole below)
        if n == "fringe":
            h = nearest_green(p, 1.5)
            return h if h is not None else 99
        if n == "bunker":
            h = nearest_green(p, 20)
            return h if h is not None else nearest_line(p, holes, 45)
        if n == "tee":
            h = nearest_line(p, holes, 40, "start")
            return card_tee_hole(p, holes, cards) if h == 99 and mapped_tee(p) else h
        return nearest_line(p, holes, 45)
    # a fairway several lines of play run through is split between their corridors (the rest: nearest line)
    fairway_hole = split_shared_fairways(polys_of(final["fairway"]), holes)
    feats = []
    for n, g in final.items():
        for p, h in (green_hole if n == "green" else fairway_hole if n == "fairway" else [(q, None) for q in polys_of(g)]):
            if p.area < 1e-6:
                continue
            h = assign(p, n) if h is None else h
            feats.append({"type": "Feature", "geometry": mapping(p),
                          "properties": {"surface": n, "hole": h, "area": round(p.area, 2), "stroke": STROKE.get(n, "#ff00ff")}})
    # fringe/semirough adopt the hole of the green/fairway they surround
    out = {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::" + C.CRS.split(":")[1]}}, "features": feats}
    C.FEATURES.mkdir(exist_ok=True)
    json.dump(out, open(C.FEATURES / "auto_core.geojson", "w"))
    from collections import Counter
    print(Counter((f["properties"]["surface"]) for f in feats))
    tot = sum(f["properties"]["area"] for f in feats)
    print("total area", round(tot), "aoi", aoi.area)


if __name__ == "__main__":
    main()
