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
