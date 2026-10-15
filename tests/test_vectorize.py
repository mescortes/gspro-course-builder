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
