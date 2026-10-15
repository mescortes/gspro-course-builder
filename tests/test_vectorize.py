"""Unit tests for the leaf-off rules in vectorize.py (synthetic label / photo rasters)."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import vectorize as V  # noqa: E402
from surface_classify import CID  # noqa: E402


def test_leaf_off_canopy_keeps_turf_but_litter_is_rough():
    lab = np.full((20, 20), CID["rough"], np.uint8)
    lab[2:8, 2:8] = CID["fairway"]; lab[10:14, 10:14] = CID["native"]; lab[15:18, 2:6] = CID["green"]
    lab[2:5, 15:19] = CID["native"]                       # an open mulch bed (no canopy): stays native
    canopy = np.zeros((20, 20), bool); canopy[:, :14] = True
    out = V.under_canopy_labels(lab, canopy, leaf_off_photo=True)
    assert (out[2:8, 2:8] == CID["fairway"]).all() and (out[15:18, 2:6] == CID["green"]).all()
    assert (out[10:14, 10:14] == CID["rough"]).all()       # leaf litter under bare trees -> wooded rough
    assert (out[2:5, 15:19] == CID["native"]).all()


def test_leaf_on_canopy_inherits_soft_surfaces_only():
    lab = np.full((10, 10), CID["rough"], np.uint8); lab[:, :5] = CID["fairway"]; lab[0:2, 8:10] = CID["green"]
    canopy = np.zeros((10, 10), bool); canopy[:, 4:6] = True; canopy[0:3, 7:10] = True
    out = V.under_canopy_labels(lab, canopy, leaf_off_photo=False)
    assert (out[:, 4] == CID["fairway"]).all()              # fairway continues under the crown
    assert (out[0:2, 8:10] == CID["rough"]).all()           # a green cannot be seen under a leaf-on crown


def test_shadowed_sand_counts_but_dormant_green_does_not():
    L = np.array([80, 40, 40, 56, 40], float)
    a = np.array([-2, -1, -1, -1, -6], float)
    b = np.array([17, 12, 12, 17, 10], float)
    ndvi = np.array([-0.03, -0.01, 0.30, 0.09, -0.01], float)
    green = np.array([0, 0, 0, 0, 1], bool)
    # sunlit sand; sand in branch shadow (NDVI ~0); shaded turf (NDVI 0.3); dormant green (NDVI 0.09); excluded green
    assert V.sand_mask(L, a, b, ndvi, green).tolist() == [True, True, False, False, False]


def _grid(f, x0=-12, x1=12, step=0.25):
    xs = np.arange(x0, x1, step) + step / 2
    X, Y = np.meshgrid(xs, xs)
    return np.c_[X.ravel(), Y.ravel(), f(X.ravel(), Y.ravel())]


def _deck_test(f, half=6.0):
    pts = _grid(f)
    r = np.maximum(np.abs(pts[:, 0]), np.abs(pts[:, 1]))
    return V.is_deck(pts[r < half - 0.5], pts[(r > half + 1.0) & (r < half + 4.0)])


def test_raised_deck_on_flat_ground_is_a_deck():
    assert _deck_test(lambda x, y: 0.6 * ((np.abs(x) < 6.5) & (np.abs(y) < 6.5)))


def test_tee_cut_into_a_hillside_is_a_deck():
    # ground rises 10 % to the north; the deck is level, cut in at the back and filled at the front
    assert _deck_test(lambda x, y: np.where((np.abs(x) < 6.5) & (np.abs(y) < 6.5), 0.0, 0.10 * y))


def test_flat_swale_bottom_is_not_a_deck():
    """QA round 1 (holes 7, 18): flat natural ground at the bottom of a swale passed the old |ring| test, because the
    ground around it rises. A deck is built up: some of its surroundings fall away below it."""
    assert not _deck_test(lambda x, y: 0.05 * np.maximum(0, np.abs(x) - 6.5) ** 1.5 + 0.03 * np.maximum(0, np.abs(y) - 6.5))


def test_flat_strip_beside_a_bank_is_not_a_deck():
    # flat fairway edge with rough rising beside it on one side only
    assert not _deck_test(lambda x, y: np.where(x > 6.5, 0.25 * (x - 6.5), 0.0))


def test_sidewalks_off_the_course_are_road_not_cart_path():
    """QA round 1 (holes 7, 11): municipal sidewalks along the streets outside the course were cart path (hole 98).
    Outside the golf_course boundary a paved strip is road (OPCD Concrete_Road)."""
    from shapely.geometry import box
    course = box(0, 0, 100, 100)
    path = box(40, 50, 42, 130)                              # a cart path that runs out onto the street sidewalk
    road = box(0, 120, 100, 126)
    cp, rd = V.off_course_paths(path, road, course, margin=5.0)
    assert abs(cp.area - 2 * 55) < 1e-6 and cp.bounds[3] <= 105 + 1e-9
    assert abs(rd.area - (road.area + 2 * 25 - 2 * 6)) < 1e-6   # the sidewalk joins the road (overlap not counted twice)
    cp2, rd2 = V.off_course_paths(path, road, box(0, 0, 0, 0).buffer(0), margin=5.0)
    assert cp2.equals(path) and rd2.equals(road), "no course boundary mapped: leave everything"


def test_shadow_sand_only_extends_sunlit_sand():
    """Build 4: the shadow rule alone (NDVI ~0, not black) also took bare soil, shaded roofs and pavement off the course
    (61 non-OSM 'bunkers'). Shadow sand is kept only where it connects to sunlit sand: a branch shadow across a bunker."""
    n = 30
    L = np.full((n, n), 45.0); a = np.full((n, n), -1.0); b = np.full((n, n), 12.0); ndvi = np.full((n, n), 0.3)
    L[5:12, 5:12] = 80; b[5:12, 5:12] = 17; ndvi[5:12, 5:12] = -0.03     # sunlit sand
    ndvi[5:12, 12:16] = -0.01                                            # its shadowed part (L 45)
    ndvi[20:26, 20:26] = -0.01                                           # a shaded bare patch, no sunlit sand
    m = V.sand_mask(L, a, b, ndvi)
    assert m[5:12, 5:16].all()
    assert not m[20:26, 20:26].any()


def test_unmapped_bunker_must_be_a_hollow_on_the_course():
    """Mapped (OSM) bunkers are kept; an unmapped one must be a LiDAR hollow and lie on the course - garden beds and
    sandpits in the neighbouring lots are hollows too (build 4)."""
    from shapely.geometry import box
    course = box(0, 0, 100, 100); osm_bunk = box(10, 10, 20, 20)
    yes = lambda p: True; no = lambda p: False
    assert V.bunker_ok(box(11, 11, 19, 19), osm_bunk, course, no)
    assert V.bunker_ok(box(50, 50, 56, 56), osm_bunk, course, yes)
    assert not V.bunker_ok(box(50, 50, 56, 56), osm_bunk, course, no)
    assert not V.bunker_ok(box(120, 50, 126, 56), osm_bunk, course, yes)
    assert V.bunker_ok(box(50, 50, 56, 56), osm_bunk, box(0, 0, 0, 0).buffer(0), yes), "no boundary mapped"


def test_unmapped_bunker_is_not_pavement_or_a_bed_by_a_building():
    """Bright, bare hollows next to roads, parking or buildings are a kerbed drive, an asphalt island or a bed by the
    wall (clubhouse and hole 12, this build): an unmapped bunker must clear paved ground and stand off buildings. Mapped
    bunkers are kept wherever they are."""
    from shapely.geometry import box
    course = box(0, 0, 200, 100); osm_bunk = box(10, 10, 20, 20)
    yes = lambda p: True
    paved = box(60, 0, 70, 100); building = box(100, 40, 110, 60)
    kw = dict(paved=paved, buildings=building)
    assert not V.bunker_ok(box(66, 50, 74, 56), osm_bunk, course, yes, **kw)      # on the drive
    assert not V.bunker_ok(box(70.5, 50, 76, 56), osm_bunk, course, yes, **kw)    # 0.5 m off the kerb
    assert not V.bunker_ok(box(85, 45, 95, 55), osm_bunk, course, yes, **kw)      # 5 m from the wall
    assert V.bunker_ok(box(140, 45, 150, 55), osm_bunk, course, yes, **kw)        # open ground
    assert V.bunker_ok(box(11, 11, 19, 19), osm_bunk, course, yes, paved=box(0, 0, 50, 50), buildings=building)


def test_a_green_holding_two_holes_ends_is_split_between_them():
    """Brambles: the classifier joined the 3 and 14 greens (side by side on a ridge) into one polygon, and the whole of
    it went to hole 14 (the last line whose end it holds); hole 3 had no green. Each hole gets the part on its side."""
    from shapely.geometry import Point, LineString
    a, b = Point(0, 0).buffer(15), Point(40, 0).buffer(15)
    joined = a.union(b).union(LineString([(0, 0), (40, 0)]).buffer(3))
    single = Point(200, 0).buffer(12)
    ends = {3: Point(0, 0), 14: Point(40, 0), 7: Point(200, 0)}
    out = V.split_shared_greens([joined, single], ends, pins=[])
    got = sorted((h, round(p.area)) for p, h in out)
    assert [h for h, _ in got] == [3, 7, 14]
    part3 = next(p for p, h in out if h == 3)
    assert part3.contains(Point(0, 0)) and not part3.contains(Point(30, 0)) and part3.area > 0.9 * a.area
    assert next(p for p, h in out if h == 7).equals(single)


def test_a_fairway_shared_by_several_holes_is_split_between_their_corridors():
    """Brambles QA round 1: one connected zoysia area holds the 13th, 14th and 5th fairways, and all 39,134 m2 went to
    hole 13 (the line nearest its representative point): holes 5 and 14 had no fairway. A fairway polygon that several
    lines of play run through is split along the boundaries between their corridors, each part to its hole."""
    from shapely.geometry import LineString, Point, box
    lines = {13: LineString([(0, 0), (0, 300)]), 14: LineString([(60, 0), (60, 300)]), 2: LineString([(400, 0), (400, 300)])}
    shared = box(-20, 0, 80, 300)                                  # both corridors, one polygon
    own = box(380, 0, 420, 300)                                    # hole 2's own fairway
    out = V.split_shared_fairways([shared, own], lines)
    parts = {}
    for p, h in out:
        parts[h] = parts.get(h, 0.0) + p.area
    assert set(parts) == {13, 14, None}
    assert abs(parts[13] - 50 * 300) < 50 and abs(parts[14] - 50 * 300) < 50, parts
    assert abs(sum(p.area for p, _ in out) - shared.area - own.area) < 1e-6, "the parts tile the polygon"
    assert all(p.distance(Point(0, 150)) < 1e-9 for p, h in out if h == 13)
    (o,) = [p for p, h in out if h is None]
    assert o is own, "a fairway one line runs through is left whole, for the nearest-line assignment"
    # a line that is no course hole (course_hole 99: a practice hole, another course's) takes no part (vectorize.main
    # passes every line of play)
    out = V.split_shared_fairways([shared], {**lines, 99: LineString([(30, 0), (30, 300)])})
    assert {h for _, h in out} == {13, 14}


def test_a_shared_fairway_split_leaves_no_shards():
    """The corridor boundary can cut a small piece off a fairway's ragged edge (Brambles: 0.1 to 35 m2 pieces), a
    fairway smaller than any vectorize keeps. A shard joins the piece it shares the longest edge with."""
    from shapely.geometry import LineString, Point, box
    from shapely.ops import unary_union
    lines = {13: LineString([(0, 0), (0, 300)]), 14: LineString([(60, 0), (60, 300)])}
    fw = unary_union([box(-20, 0, 29, 300), box(31, 0, 80, 300), box(29, 140, 31, 160),     # two fairways, joined
                      box(25, 300, 27, 310), box(25, 310, 34, 312)])                       # a hook over the boundary
    out = V.split_shared_fairways([fw], lines)
    assert min(p.area for p, _ in out) >= 0.25 * V.MIN_AREA["fairway"]
    assert abs(sum(p.area for p, _ in out) - fw.area) < 1e-6
    assert next(h for p, h in out if p.distance(Point(33, 311)) < 1e-9) == 13, "the hook's tip stays with its hole"


def test_a_line_clipping_a_fairway_corner_does_not_take_a_sliver():
    """A neighbouring line of play that just clips a fairway (its green beside it) takes no part smaller than a
    fairway; the polygon stays whole, the hole of the line that runs along it."""
    from shapely.geometry import LineString, box
    lines = {10: LineString([(0, 0), (0, 300)]), 7: LineString([(26, 310), (19.5, 299.5)])}   # hole 7's green by the corner
    fw = box(-20, 0, 20, 300)
    out = V.split_shared_fairways([fw], lines, min_part=150.0)
    assert len(out) == 1 and out[0][0] is fw and out[0][1] == 10
    assert {h for _, h in V.split_shared_fairways([fw], lines, min_part=100.0)} == {7, 10}, "a bigger part is split off"


def test_a_line_crossing_a_fairway_takes_no_part_of_it():
    """Round-3 review: a hole whose line of play crosses another hole's fairway (a tee shot over it, a dogleg over its
    corner) took a bowtie of it round the crossing (800 m2 square-on, 644 m2 near its end) and cut it in two. On
    Brambles the tees of holes 7, 9, 12, 16 and 17 sit by other holes' greens, and their lines took 257-2041 m2 of
    those green surrounds. A line takes a part only if it runs along the polygon (80 m inside it) or ends by it."""
    from shapely.geometry import LineString, box
    fw = box(-20, 0, 20, 300)
    for cross in ([(-150, 150), (150, 160)], [(-150, 290), (150, 295)], [(30, 296), (-3, 302), (-250, 340)]):
        lines = {4: LineString([(0, -20), (0, 320)]), 9: LineString(cross)}     # the last: hole 9's tee by the corner
        out = V.split_shared_fairways([fw], lines)
        assert len(out) == 1 and out[0][0] is fw and out[0][1] == 4, (cross, [(round(p.area), h) for p, h in out])
    lines = {4: LineString([(0, -20), (0, 320)]), 9: LineString([(-150, 150), (150, 160)])}
    assert {h for _, h in V.split_shared_fairways([fw], lines, min_run=30.0)} == {4, 9}, \
        "shared_fairway_min_run 30: the 40 m crossing runs along it"


def test_a_par_3_keeps_the_surround_of_its_green_in_a_shared_fairway():
    """A par 3 runs a few metres inside the connected zoysia round its green (Brambles' 3rd, in the 13th's polygon):
    it ends by the polygon, so it takes the part round its green."""
    from shapely.geometry import LineString, Point, box
    green = Point(40, 270).buffer(12.0)
    fw = box(-20, 0, 60, 300).difference(green)
    lines = {13: LineString([(0, -50), (0, 350)]), 3: LineString([(200, 200), (40, 270)])}
    out = V.split_shared_fairways([fw], lines)
    parts = {h: sum(p.area for p, k in out if k == h) for h in {h for _, h in out}}
    assert set(parts) == {3, 13}, parts
    assert next(p for p, h in out if h == 3).distance(green) < 1e-6 and parts[3] < 0.2 * fw.area


def test_grass_and_dirt_tracks_on_the_course_are_not_cart_paths():
    """Classify review: every highway=track mostly inside the course became a 2.8 m cart path (OPCD Concrete). Tracks
    mapped as grass or earth (surface=grass / ground / dirt / earth, tracktype=grade4 / grade5) are mown maintenance
    routes: turf, neither cart path nor road. A gravel or paved track stays a cart path."""
    from shapely.geometry import LineString, Point, box
    from shapely.ops import unary_union
    G = [(1, {"leisure": "golf_course"}, box(0, 0, 400, 400)),
         (2, {"highway": "track", "surface": "grass"}, LineString([(50, 50), (350, 50)])),
         (3, {"highway": "track", "tracktype": "grade5"}, LineString([(50, 100), (350, 100)])),
         (4, {"highway": "track", "surface": "dirt"}, LineString([(50, 150), (350, 150)])),
         (5, {"highway": "track", "tracktype": "grade4", "surface": "ground"}, LineString([(50, 200), (350, 200)])),
         (6, {"highway": "track", "surface": "gravel", "tracktype": "grade2"}, LineString([(50, 250), (350, 250)])),
         (7, {"highway": "service", "surface": "earth"}, LineString([(50, 300), (350, 300)]))]
    vector, tracks, _ = V.osm_vectors(G)
    assert len(tracks) == 1 and tracks[0].contains(Point(200, 250))
    roads = unary_union(vector["road"]) if vector["road"] else box(0, 0, 0, 0)
    for y in (50, 100, 150, 200, 300):
        assert not roads.contains(Point(200, y)) and not tracks[0].contains(Point(200, y)), y


def test_cart_paths_tagged_service_road_are_cart_path_labels(monkeypatch):
    """Whistle Bear maps its cart paths golf=cartpath + highway=service (+ golf_cart=designated): the classifier's
    training labels must call them cart path, not road; a plain service road stays road."""
    import rasterio
    from shapely.geometry import LineString, box
    import surface_classify as S
    T = rasterio.transform.from_origin(0.0, 100.0, 0.25, 0.25)
    G = [(1, {"leisure": "golf_course"}, box(0, 0, 100, 100)),
         (2, {"golf": "cartpath", "highway": "service", "service": "driveway", "golf_cart": "designated"},
          LineString([(10, 30), (90, 30)])),
         (3, {"highway": "service"}, LineString([(10, 70), (90, 70)]))]
    monkeypatch.setattr(S, "osm_geoms", lambda: G)
    lab, _ = S.osm_label_raster(400, 400, T, np.zeros((400, 400), np.float32))
    row = lambda y: int((100 - y) / 0.25)
    assert lab[row(30), 200] == CID["cartpath"]
    assert lab[row(70), 200] == CID["road"]
    assert lab[row(30) - int(2.0 / 0.25), 200] != CID["road"]    # no 2.5 m road band around the cart path


def test_grass_tracks_are_not_road_in_the_training_labels(monkeypatch):
    """Round-3 review: vectorize leaves tracks mapped as grass or earth to the turf, but the classifier's training labels
    still burnt them as road (1.5 m each side), teaching it that mown grass is road. They are left out of the road
    class there too (and its unlabelled band): grass round them is rough. A plain track stays road."""
    import rasterio
    from shapely.geometry import LineString, box
    import surface_classify as S
    T = rasterio.transform.from_origin(0.0, 100.0, 0.25, 0.25)
    G = [(1, {"leisure": "golf_course"}, box(0, 0, 100, 100)),
         (2, {"highway": "track", "surface": "grass"}, LineString([(10, 30), (90, 30)])),
         (3, {"highway": "service", "surface": "mud"}, LineString([(10, 50), (90, 50)])),
         (4, {"highway": "track"}, LineString([(10, 70), (90, 70)]))]
    monkeypatch.setattr(S, "osm_geoms", lambda: G)
    lab, _ = S.osm_label_raster(400, 400, T, np.zeros((400, 400), np.float32))
    row = lambda y: int((100 - y) / 0.25)
    assert lab[row(30), 200] == CID["rough"] and lab[row(50), 200] == CID["rough"]
    assert lab[row(70), 200] == CID["road"]
    assert S.TURF_TRACK is V.TURF_TRACK, "one rule for vectorize and the training labels"


def test_tracks_on_the_course_are_cart_path_and_main_roads_are_road():
    """highway=primary / trunk / *_link / living_street / track had no road width, so a highway past the course played
    as rough, and the 'track inside the course is cart path' branch could never run. A pond mapped
    golf=lateral_water_hazard only was no water surface (nor a water hazard in holes.json)."""
    from shapely.geometry import LineString, Point, box
    from shapely.ops import unary_union
    G = [(1, {"leisure": "golf_course"}, box(0, 0, 400, 400)),
         (2, {"highway": "track"}, LineString([(50, 100), (350, 100)])),            # maintenance track on the course
         (3, {"highway": "primary"}, LineString([(-200, 450), (600, 450)])),         # the highway past the course
         (4, {"highway": "trunk_link"}, LineString([(-200, 500), (600, 500)])),
         (5, {"highway": "living_street"}, LineString([(-200, 550), (600, 550)])),
         (6, {"highway": "track"}, LineString([(-300, 600), (-100, 600)])),         # a farm track off the course
         (7, {"golf": "lateral_water_hazard"}, box(200, 200, 250, 240)),
         (8, {"leisure": "swimming_pool"}, box(300, 300, 310, 320))]
    vector, tracks, course = V.osm_vectors(G)
    assert course.equals(box(0, 0, 400, 400))
    assert len(tracks) == 1 and tracks[0].contains(Point(200, 100)) and abs(tracks[0].area - 300 * 2.8) < 30
    roads = unary_union(vector["road"])
    for p in ((0, 450), (0, 500), (0, 550), (-200, 600)):
        assert roads.contains(Point(p)), p
    assert not roads.contains(Point(200, 100))
    primary = next(g for g in vector["road"] if g.contains(Point(0, 450)))
    assert abs(primary.area - 800 * 2 * V.ROAD_HALF_WIDTH["primary"]) < 1e-6
    assert sorted(g.area for g in vector["water"]) == [200.0, 2000.0]


def _old_sand(L, a, b, ndvi=None):
    """The sand rule as it was written before [tuning.sand] / [tuning.shadow_sand] (literal constants)."""
    strong = (L > 66) & (a > -12) & (b > 8.5) & (b < 26)
    weak = np.zeros_like(strong)
    if ndvi is not None:
        strong &= ndvi < 0.12
        weak = (ndvi < 0.02) & (L > 25) & (a > -8) & (b > 2)
    return strong, weak


def test_sand_and_turf_colour_rules_default_to_the_old_constants():
    rng = np.random.default_rng(0)
    L, a, b = rng.uniform(0, 100, 20000), rng.uniform(-30, 30, 20000), rng.uniform(-10, 40, 20000)
    ndvi = rng.uniform(-0.2, 0.5, 20000)
    for nd in (None, ndvi):
        s, w = V.sand_mask(L, a, b, nd, parts=True)
        s0, w0 = _old_sand(L, a, b, nd)
        assert (s == s0).all() and (w == w0).all()
    assert (V.turf_mask(a) == (a < -14)).all()
    assert (V.turf_mask(a, ndvi) == ((a < -14) | (ndvi > 0.25))).all()


def test_white_bunker_sand_is_found_with_tuned_colour_rules(monkeypatch):
    """White silica sand (sRGB 235, 232, 222: Lab b* ~5) failed the b* > 8.5 rule tuned on one Ontario photo, so
    unmapped bunkers vanished; [tuning.sand] / [tuning.turf] in course.toml now set the thresholds."""
    from skimage.color import rgb2lab
    import surface_classify as S
    lab = rgb2lab(np.array([[[235, 232, 222], [226, 224, 216], [120, 150, 90]]]) / 255.0)[0]
    L, a, b = lab[:, 0], lab[:, 1], lab[:, 2]
    assert not V.sand_mask(L, a, b).any()
    monkeypatch.setattr(S.C, "tuning", lambda k, d: {"b_min": 3.0} if k == "sand" else
                        {"a_max": -10.0} if k == "turf" else d)
    monkeypatch.setattr(V, "SAND", S.tuned("sand", V.SAND))
    monkeypatch.setattr(V, "TURF", S.tuned("turf", V.TURF))
    assert V.sand_mask(L, a, b).tolist() == [True, True, False]
    assert V.SAND["L_min"] == 66.0 and V.TURF == {"a_max": -10.0, "ndvi_min": 0.25}
    assert V.turf_mask(a).tolist() == [False, False, True]


def _dem(f, n=200, res=0.25):
    """A synthetic DEM window: f(x, y) on cell centres (m), the window 50 m across."""
    x = (np.arange(n) + 0.5) * res
    X, Y = np.meshgrid(x, x)
    return f(X, Y), X, Y


def _hollow_args(z, X, Y, inside, reach=2.5):
    from scipy import ndimage
    basin = ndimage.binary_dilation(inside, iterations=int(reach / 0.25))
    ring = basin & ~ndimage.binary_dilation(inside, iterations=2)
    return z, inside, basin, float(z[ring].mean() - z[inside].mean())


def test_an_open_channel_is_not_an_unmapped_bunker():
    """Brambles QA round 1: bare soil on barranca floors, in drainage ditches and path cuts passed the hollow test (the
    polygon 0.08 m below the ring around it) - an open channel is lower than its banks too. 6 of 9 bunker polygons on
    holes 7-9 were false. A channel drains along its length: it holds no water and has no face."""
    z, X, Y = _dem(lambda x, y: 0.02 * x + np.where(np.abs(y - 25) < 1.5, -0.25, 0.0))   # 3 m wide ditch, 0.25 m deep
    inside = (np.abs(Y - 25) < 1.4) & (np.abs(X - 25) < 6)                              # 12 m of its floor
    args = _hollow_args(z, X, Y, inside)
    assert args[3] > 0.08, "the old test passes it"
    assert not V.closed_hollow(*args, H=V.BUNKER_HOLLOW_DEFAULT)
    assert V.closed_hollow(*args, H=dict(V.BUNKER_HOLLOW_DEFAULT, pond_frac=0.0)), "pond_frac 0: the closed test is off"


def test_a_deep_ditch_open_at_both_ends_has_no_face():
    """Round-3 review: the face rule (the polygon 0.35 m or more below the ring round it) is an average, and an open
    ditch deeper than that passed it (3 m wide: 0.6 m deep kept, 0.4 m dropped; on Brambles an 88 m2 scour hole on the
    barranca thalweg, 0.36 m below its ring, stayed a bunker). A bunker cut into a slope is open on its low side only;
    a channel is open at both ends - its floor runs out of the polygon at grade on two opposite sides."""
    for slope in (0.02, 0.05, 0.08):
        z, X, Y = _dem(lambda x, y: slope * x + np.where(np.abs(y - 25) < 1.5, -0.6, 0.0))      # 0.6 m deep ditch
        inside = (np.abs(Y - 25) < 1.4) & (np.abs(X - 25) < 6)
        args = _hollow_args(z, X, Y, inside)
        assert args[3] > V.BUNKER_HOLLOW_DEFAULT["face"], "deeper than a face"
        assert not V.closed_hollow(*args, H=V.BUNKER_HOLLOW_DEFAULT), slope
    # a pit at the head of a channel, open downhill only, is a faced hollow like a bunker cut into a slope
    z, X, Y = _dem(lambda x, y: 0.02 * x + np.where((np.abs(y - 25) < 1.5) & (x > 19), -0.6, 0.0))
    inside = (np.abs(Y - 25) < 1.4) & (np.abs(X - 25) < 6)
    assert V.closed_hollow(*_hollow_args(z, X, Y, inside), H=V.BUNKER_HOLLOW_DEFAULT)
    # open = the ring less than `open` m above the floor next to it: 0 counts only ground below the floor as open
    z, X, Y = _dem(lambda x, y: 0.05 * x + np.where(np.abs(y - 25) < 1.5, -0.6, 0.0))
    inside = (np.abs(Y - 25) < 1.4) & (np.abs(X - 25) < 6)
    assert V.closed_hollow(*_hollow_args(z, X, Y, inside), H=dict(V.BUNKER_HOLLOW_DEFAULT, open=0.0))


def test_a_bowl_and_a_bunker_cut_into_a_slope_are_closed_hollows():
    """A bowl holds water; a greenside bunker cut into a slope is open on its low side (Westmount: a quarter of the
    mapped bunkers hold no water in the LiDAR) but has a real face, 0.35 m or more over the ring."""
    r2 = lambda x, y: (x - 25) ** 2 + (y - 25) ** 2
    z, X, Y = _dem(lambda x, y: 0.03 * x + np.where(r2(x, y) < 16, 0.4 * (r2(x, y) / 16 - 1), 0.0))   # 0.4 m deep bowl
    inside = r2(X, Y) < 12
    assert V.closed_hollow(*_hollow_args(z, X, Y, inside), H=V.BUNKER_HOLLOW_DEFAULT)
    # cut into a 12 % slope rising to +y: a 0.8 m face on the high side, the floor running out at grade downhill
    z, X, Y = _dem(lambda x, y: np.where((np.abs(x - 25) < 4) & (y > 20) & (y < 27), 0.12 * 20, 0.12 * y))
    inside = (np.abs(X - 25) < 3.8) & (Y > 20.2) & (Y < 26.8)
    args = _hollow_args(z, X, Y, inside)
    assert V.held_water(z, args[2])[inside].max() < 0.01, "it holds no water"
    assert V.closed_hollow(*args, H=V.BUNKER_HOLLOW_DEFAULT)


def test_lidar_trim_keeps_the_pans_and_drops_the_grass_faces():
    """Brambles' 0.6 m photo blurs sand into the grass faces: the 18th greenside bunker polygon (372 m2) held two LiDAR
    pans plus the steep face above them. With a coarse photo the bunker is cut to its pans (the cells below the rim
    around them, in the bowls that hold water) and a lip up the faces."""
    from scipy import ndimage
    def pan(x, y, cx):
        r = np.hypot((x - cx) / 5.0, (y - 25) / 3.5)
        return np.where(r < 1, 0.5 * (r ** 4 - 1), 0.0)
    z, X, Y = _dem(lambda x, y: 0.05 * y + pan(x, y, 16) + pan(x, y, 34) + np.where(y > 30, 0.4 * (y - 30), 0.0))
    poly = (np.abs(X - 25) < 17) & (Y > 19) & (Y < 33)                                 # pans, the ridge between, the face
    basin = ndimage.binary_dilation(poly, iterations=10)
    m = V.bunker_bowls(z, poly, basin, 0.25, V.BUNKER_TRIM_DEFAULT)
    lab, n = ndimage.label(m)
    assert n == 2, "two pans, split at the ridge"
    assert m[(np.hypot((X - 16) / 5, (Y - 25) / 3.5) < 0.8)].all() and m[(np.hypot((X - 34) / 5, (Y - 25) / 3.5) < 0.8)].all()
    assert not m[Y > 31.5].any(), "the face above the pans is trimmed"
    assert m.sum() < 0.7 * poly.sum()


def test_lidar_trim_leaves_a_bunker_without_a_pan_alone():
    """A bunker cut into a slope holds no water: there is no pan to trim it to, and it is left as it is."""
    from scipy import ndimage
    z, X, Y = _dem(lambda x, y: np.where((np.abs(x - 25) < 4) & (y > 20) & (y < 27), 0.12 * 20, 0.12 * y))
    poly = (np.abs(X - 25) < 4.5) & (Y > 19.5) & (Y < 27.5)
    assert V.bunker_bowls(z, poly, ndimage.binary_dilation(poly, iterations=10), 0.25, V.BUNKER_TRIM_DEFAULT) is None


def _dem_raster(f, n=240, res=0.25, x0=1000.0, y1=2060.0):
    """A synthetic north-up DEM (float32, as dem.tif) of f(x, y) on cell centres, and its affine transform."""
    from rasterio.transform import from_origin
    T = from_origin(x0, y1, res, res)
    xs = x0 + (np.arange(n) + 0.5) * res; ys = y1 - (np.arange(n) + 0.5) * res
    X, Y = np.meshgrid(xs, ys)
    return f(X, Y).astype(np.float32), T


def test_dem_window_holds_the_polygon_and_its_spill_basin():
    """vectorize.main's DEM window round a bunker: the window, its transform, the polygon's cells and the basin (the
    polygon and 2.5 m round it), on the DEM's own cells."""
    from shapely.geometry import box
    dem, T = _dem_raster(lambda x, y: x - 1000 + 0.01 * (y - 2000))
    p = box(1020, 2020, 1030, 2026)
    z, tw, inside, basin = V.dem_window(dem, T, p, 3.5)
    assert z.dtype == np.float64 and abs(inside.sum() * 0.0625 - p.area) < 1.0
    assert abs(basin.sum() * 0.0625 - p.buffer(2.5).area) < 4.0 and (basin | ~inside).all()
    r, c = np.argwhere(inside)[0]
    x, y = tw.c + (c + 0.5) * tw.a, tw.f + (r + 0.5) * tw.e
    assert abs(z[r, c] - (x - 1000 + 0.01 * (y - 2000))) < 1e-3, "the window is the DEM under it"
    P = V.dem_points(dem, T, p)
    assert len(P) == inside.sum() and abs(P[:, 2].mean() - z[inside].mean()) < 1e-9


def test_unmapped_hollow_needs_a_closed_hollow_below_its_ring():
    """vectorize.main's test for an unmapped bunker: lower than the ring round it (not higher: a sign slip would keep
    mounds and drop bowls), and closed or faced (an open ditch is lower than its banks too)."""
    from shapely.geometry import Point, box
    H = V.BUNKER_HOLLOW_DEFAULT
    c = Point(1030, 2030)
    bowl, T = _dem_raster(lambda x, y: 0.02 * (x - 1000) - np.clip(0.4 * (1 - ((x - 1030) ** 2 + (y - 2030) ** 2) / 16), 0, None))
    assert V.unmapped_hollow(bowl, T, c.buffer(3.5), H)
    mound, _ = _dem_raster(lambda x, y: 0.02 * (x - 1000) + np.clip(0.4 * (1 - ((x - 1030) ** 2 + (y - 2030) ** 2) / 16), 0, None))
    assert not V.unmapped_hollow(mound, T, c.buffer(3.5), H)
    ditch, _ = _dem_raster(lambda x, y: 0.02 * (x - 1000) + np.where(np.abs(y - 2030) < 1.5, -0.25, 0.0))
    assert V.is_hollow(ditch, T, box(1024, 2028.6, 1036, 2031.4)), "lower than its banks"
    assert not V.unmapped_hollow(ditch, T, box(1024, 2028.6, 1036, 2031.4), H)
    deep, _ = _dem_raster(lambda x, y: 0.02 * (x - 1000) + np.where(np.abs(y - 2030) < 1.5, -0.6, 0.0))
    assert not V.unmapped_hollow(deep, T, box(1024, 2028.6, 1036, 2031.4), H), "a deep ditch has no face either"


def test_trim_faces_cuts_a_bunker_to_its_pans():
    """vectorize.main's coarse-photo trim, polygons in and out: a bunker with two pans and a face above them becomes
    the two pans; one with no pan, or whose pans are smaller than any bunker vectorize keeps, stays as it is."""
    from shapely.geometry import box
    def pan(x, y, cx, a=5.0, b=3.5, d=0.5):
        r = np.hypot((x - cx) / a, (y - 2025) / b)
        return np.where(r < 1, d * (r ** 4 - 1), 0.0)
    dem, T = _dem_raster(lambda x, y: 0.05 * (y - 2000) + pan(x, y, 1016) + pan(x, y, 1034)
                         + np.where(y > 2030, 0.4 * (y - 2030), 0.0))
    p = box(1008, 2019, 1042, 2033)
    out = V.polys_of(V.trim_faces(dem, T, p, V.BUNKER_TRIM_DEFAULT))
    assert len(out) == 2 and all(q.area >= V.MIN_AREA["bunker"] for q in out)
    assert sum(q.area for q in out) < 0.7 * p.area and all(q.bounds[3] < 2031.5 for q in out)
    slope, _ = _dem_raster(lambda x, y: np.where((np.abs(x - 1025) < 4) & (y > 2020) & (y < 2027), 0.12 * 20, 0.12 * (y - 2000)))
    q = box(1020.5, 2019.5, 1029.5, 2027.5)
    assert V.trim_faces(slope, T, q, V.BUNKER_TRIM_DEFAULT).equals(q), "no pan: left alone"
    tiny, _ = _dem_raster(lambda x, y: 0.05 * (y - 2000) + pan(x, y, 1025, 1.2, 1.0, 0.3))
    q = box(1018, 2018, 1032, 2032)
    assert V.trim_faces(tiny, T, q, V.BUNKER_TRIM_DEFAULT).equals(q), "a pan under MIN_AREA: left alone"


def test_bunkers_are_trimmed_only_with_a_coarse_photo():
    """[tuning.bunker_trim] photo_res: Westmount's 0.16 m photo separates sand from grass faces, Brambles' 0.6 m does
    not; photo_res = 0 always trims, a large value never."""
    T = V.BUNKER_TRIM_DEFAULT
    assert not V.trims_bunkers(0.16, T) and V.trims_bunkers(0.6, T) and V.trims_bunkers(0.3, T)
    assert V.trims_bunkers(0.16, dict(T, photo_res=0.0)) and not V.trims_bunkers(0.6, dict(T, photo_res=100.0))


def test_held_water_fills_a_bowl_to_its_spill_point_without_deprecated_calls():
    """held_water is a morphological fill (water poured into the basin rises to the lowest way out). It used
    skimage.morphology.reconstruction, which sets an array's shape - deprecated in NumPy 2.5, an error in a later
    NumPy a fresh install may get. The fill is scipy's now, with the same result."""
    import warnings
    from scipy import ndimage
    z, X, Y = _dem(lambda x, y: 0.01 * x + np.clip(((x - 25) ** 2 + (y - 25) ** 2) / 16 - 1, None, 0) * 0.5)
    z[100, 120:] = z[100, 120:] - 0.3                                    # a notch: the bowl spills through it
    inside = (X - 25) ** 2 + (Y - 25) ** 2 < 16
    basin = ndimage.binary_dilation(inside, iterations=10)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        w = V.held_water(z, basin)
    assert w.min() >= 0 and (w[~basin] == 0).all()
    assert w[100, 100] > 0.2, "the bowl holds water"
    from skimage.morphology import reconstruction
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        b = basin.copy(); b[[0, -1], :] = False; b[:, [0, -1]] = False
        ref = reconstruction(np.where(b, z.max(), z), z, method="erosion") - z
    assert np.array_equal(w, ref), "the same fill as before"


def test_drafted_bunkers_get_the_lidar_test_of_unmapped_ones():
    """Round-3 extra: a course OSM does not map has its bunkers drafted from the photo (draft_features: draft=yes). They
    counted as mapped, so bare soil drafted as sand (Brambles: the hole-7 barranca, the hole-1 road cut) skipped the
    LiDAR test. Drafted bunkers are training labels, not survey data: a photo bunker over one gets the unmapped test,
    and one the photo missed is added only if it passes it. OSM's and hand-drawn bunkers still spare it."""
    from shapely.geometry import Point, box
    H = V.BUNKER_HOLLOW_DEFAULT
    dem, T = _dem_raster(lambda x, y: 0.02 * (x - 1000) + np.where(np.abs(y - 2030) < 1.5, -0.6, 0.0)  # a ditch
                         - np.clip(0.5 * (1 - ((x - 1030) ** 2 + (y - 2010) ** 2) / 16), 0, None))      # a bowl
    ditch, bowl = box(1024, 2028.6, 1036, 2031.4), Point(1030, 2010).buffer(3.5)
    course = box(1000, 1990, 1060, 2060)
    G = [(1, {"golf": "bunker", "draft": "yes"}, ditch), (2, {"golf": "bunker", "draft": "yes"}, bowl),
         (3, {"golf": "bunker"}, box(1040, 2040, 1045, 2045))]
    survey = V.survey_bunkers(G)
    assert survey.contains(box(1040, 2040, 1045, 2045)) and survey.intersection(ditch.union(bowl)).is_empty
    ok = lambda p: V.bunker_ok(p, survey, course, lambda q: V.unmapped_hollow(dem, T, q, H))
    assert not ok(ditch) and ok(bowl) and ok(box(1040.5, 2040.5, 1044.5, 2044.5))
    assert [V.mapped_bunker_hollow(dem, T, g, t, course, H=H) for _, t, g in G[:2]] == [False, True]
    assert V.mapped_bunker_hollow(dem, T, ditch, {"golf": "bunker"}, course, H=H), "surveyed: a 5 cm hollow will do"


def test_a_fairway_split_survives_voronoi_cells_on_an_exact_lattice():
    """On integer synthetic coordinates the clipped lines of play give Voronoi sites on an exact lattice, and the union
    of a hole's cells raised a GEOS TopologyException (unable to assign free hole to a shell), stopping vectorize."""
    from shapely.geometry import LineString, box
    fw = box(-20, 0, 20, 300)
    lines = {4: LineString([(0, -20), (0, 320)]), 9: LineString([(-150, 150), (49, 150)])}
    out = V.split_shared_fairways([fw], lines, min_run=30.0)
    assert abs(sum(p.area for p, _ in out) - fw.area) < 1.0 and {h for _, h in out} <= {4, 9}
