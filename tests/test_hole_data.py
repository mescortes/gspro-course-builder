"""Unit tests for tee-marker placement (hole_data.place_tees) on synthetic pads."""
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import Point, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hole_data as HD  # noqa: E402

GREEN = np.array([0.0, 300.0])


def test_marker_reaches_the_far_end_of_an_l_shaped_pad():
    """QA round 1: composite / L-shaped tee complexes have their centroid outside the pad, so the single axis through it
    clipped only the short arm and the marker could not reach the card yardage. Every line of play across the pad is a
    candidate axis."""
    pad = unary_union([box(0, 0, 8, 30), box(8, 0, 40, 8)])     # long arm along the line of play + a cross arm
    assert not pad.contains(pad.centroid)
    yards = (GREEN[1] - 25.0) * HD.YD                          # a marker 25 m up the long arm
    (t,) = HD.place_tees([pad], [], GREEN, [yards])
    assert t["pad_err"] == 0.0
    assert abs(t["measured"] - yards) < 0.5
    assert pad.buffer(-1.0).contains(Point(t["pos"]))


def test_marker_on_a_rectangular_pad_stays_on_the_centre_line():
    pad = box(-5, 0, 5, 30)
    yards = (GREEN[1] - 12.0) * HD.YD
    (t,) = HD.place_tees([pad], [], GREEN, [yards])
    assert t["pad_err"] == 0.0 and abs(t["measured"] - yards) < 0.5
    assert abs(t["pos"][0]) < 1.0, "marker on the pad's centre line"


def test_pin_area_relaxes_on_a_steep_green():
    """QA round 1, hole 14: only 3.7 % of the green is <= 3 % slope, so the five pins sat within 2-3 m of each other.
    When the pinnable area is that small the slope limit is relaxed (in steps, up to 5 %) until enough green is
    available; a green with plenty of flat area keeps the 3 % rule."""
    n = 120
    inside = np.zeros((n, n), bool); inside[10:110, 10:110] = True
    from scipy import ndimage
    edge = ndimage.distance_transform_edt(inside) * 0.25
    slope = np.full((n, n), 4.6); slope[50:56, 50:56] = 2.0      # a steep Thompson green with one small flat
    ok, limit = HD.pin_candidates(inside, edge, slope)
    assert limit == 5.0 and ok.sum() / inside.sum() > 0.5
    slope2 = np.full((n, n), 2.5)
    ok2, limit2 = HD.pin_candidates(inside, edge, slope2)
    assert limit2 == 3.0 and ok2.sum() == (inside & (edge >= 3.0)).sum()


def test_green_includes_touching_override_fills():
    """QA round 2 (holes 8, 14, 18): a notch fill burned by an override is a separate green polygon, so the green record
    (centre, slope, pins, maps) used only the largest piece. Pieces that touch it are part of the green; a separate
    green (a practice green, another hole's) is not."""
    main = box(0, 0, 30, 25)
    notch = box(30, 10, 33, 14)                 # shares an edge with the main green
    sliver_gap = box(30.2, 0, 31, 2)            # 20 cm away: snapped override edge, still the same green
    other = box(80, 0, 100, 20)
    g = HD.hole_green([notch, main, other, sliver_gap])
    assert g.geom_type == "Polygon"
    assert abs(g.area - (main.area + notch.area + sliver_gap.area)) < 2.0
    assert g.intersection(other).is_empty


def _yd(m):
    return m * HD.YD


def test_two_tee_sets_never_share_one_marker_spot():
    """Brambles hole 7 (card 611 / 572 / 449; the Back deck measures 572): each set took the pad nearest its card, so
    the Middle marker went to the Back deck and, clamped to its back end, sat on the Back marker. A set whose marker
    would land on an earlier set's takes the next pad (its own deck) and the gap is reported."""
    back, middle, front = box(-5, 0, 5, 20), box(-5, 60, 5, 75), box(-5, 120, 5, 130)
    card = [_yd(330.0), _yd(320.0), _yd(175.0)]            # both cards beyond the Back deck (its back end: 298.5 m)
    t = HD.place_tees([front, back, middle], [], GREEN, card)
    assert [x["pad"] for x in t] == [back, middle, front]
    assert np.hypot(*(t[0]["pos"] - t[1]["pos"])) > 30
    assert t[1]["pad_err"] > 50, "the Middle gap is reported, not hidden on the Back marker"
    assert t[0]["pad_err"] > 30 and t[2]["pad_err"] == 0.0


def test_sets_share_a_pad_at_their_own_yardages():
    """Two sets on one long pad at different yardages are two marker spots: nothing moves."""
    pad, front = box(-5, 0, 5, 30), box(-5, 120, 5, 130)
    t = HD.place_tees([pad, front], [], GREEN, [_yd(295.0), _yd(285.0), _yd(175.0)])
    assert t[0]["pad"] is pad and t[1]["pad"] is pad and t[2]["pad"] is front
    assert t[0]["pad_err"] == 0.0 and t[1]["pad_err"] == 0.0
    assert abs(np.hypot(*(t[0]["pos"] - t[1]["pos"])) - 10.0) < 0.5


def test_sets_with_the_same_card_share_their_deck():
    """Round-3 review: scorecards often give two sets the same yardage on a hole (a forward and a combo set sharing a
    box). Both markers are exactly at their card on the deck, so they share its spot: the second set must not be sent
    to the forward pad (304.6 yd off) because its marker is within tee_marker_gap of the first's."""
    deck, front = box(-5, -95, 5, -65), box(-5, 20, 5, 30)           # the deck measures 366.5-393.5 m from the green
    for card in ([380.0, 380.0, 275.0], [380.0, 378.5, 275.0]):
        t = HD.place_tees([front, deck], [], GREEN, [_yd(m) for m in card])
        assert [x["pad"] for x in t] == [deck, deck, front], card
        assert [x["pad_err"] for x in t] == [0.0, 0.0, 0.0], card
        assert abs(np.hypot(*(t[0]["pos"] - t[1]["pos"])) - (card[0] - card[1])) < 0.1
        HD.fairway_markers(t, [], GREEN)
        assert [x["source"] for x in t] == ["pad"] * 3


def test_a_set_whose_card_is_the_clamped_spot_still_moves():
    """Brambles hole 7 exactly: the Back card is longer than the ground, so its marker clamps to the back of the Back
    deck - which is where the Middle card is. The Middle marker is at its card there, but on a marker that misses its
    own card by 31 m: it takes its own deck and its gap is reported (and no fairway marker lands on the Back marker)."""
    back, middle = box(-2, 0, 2, 20), box(-5, 60, 5, 75)              # one axis; the Back deck's back end: 298.5 m
    t = HD.place_tees([back, middle], [], GREEN, [_yd(330.0), _yd(298.5)])
    assert t[0]["pad"] is back and t[0]["pad_err"] > 30
    assert t[1]["pad"] is middle and t[1]["pad_err"] > 50
    HD.fairway_markers(t, [], GREEN)
    assert t[1]["source"] == "pad" and np.hypot(*(t[0]["pos"] - t[1]["pos"])) > 30


def test_one_pad_for_every_set_doubles_them_up():
    """With a single pad (Brambles hole 15 before QA: the shared back deck is another hole's) there is nowhere else:
    the sets share its back end and the gaps are reported."""
    pad = box(-5, 100, 5, 120)
    t = HD.place_tees([pad], [], GREEN, [_yd(250.0), _yd(240.0), _yd(185.0)])
    assert all(x["pad"] is pad for x in t)
    assert np.hypot(*(t[0]["pos"] - t[1]["pos"])) < 0.1 and t[0]["pad_err"] > 40 and t[1]["pad_err"] > 30


def test_fairway_marker_never_lands_on_another_marker():
    """No pad delivers Brambles hole 7's Middle card, and the card equals the Back deck's length: the fairway-marker
    fallback put Middle on the Back marker again. A fairway marker must be clear of the other sets' markers; otherwise
    the set stays on its pad and its gap is reported."""
    back, middle = box(-5, 0, 5, 20), box(-5, 60, 5, 75)
    tees = HD.place_tees([back, middle], [], GREEN, [_yd(330.0), _yd(320.0)])
    HD.fairway_markers(tees, [], GREEN)
    assert tees[1]["source"] == "pad" and tees[1]["pad"] is middle
    # a fairway marker that is clear of the others is still used
    tees = HD.place_tees([back, middle], [], GREEN, [_yd(298.5), _yd(260.0)])
    HD.fairway_markers(tees, [], GREEN)
    assert tees[1]["source"] == "fairway_marker" and abs(tees[1]["measured"] - _yd(260.0)) < 0.5


def test_a_deckless_forward_marker_goes_on_mown_ground_away_from_hazards():
    """Deer Ridge QA: deckless forward markers (Copper) went on the back tee's first leg at the card distance whatever
    lay there: a lake bank (hole 10), rough (12), beside bunkers (1-3), a pond (6). The marker keeps the card distance
    and takes the best ground within FAIRWAY_MARKER_OFFSET m of that leg: the hole's fairway, then its tee decks, then
    semirough, then rough; never a path or a green, nor within FAIRWAY_MARKER_CLEARANCE m of a bunker, water or a
    native area; the nearest the leg among equals. With no such spot the set stays on its pad, its gap reported."""
    from shapely.geometry import LineString
    back = box(-5, 0, 5, 20)                                          # 280-300 m from the green: no 200 m deck
    area = box(-150, -50, 150, 350)
    def course(*feats):
        rough = area.difference(unary_union([g for g, _, _ in feats]))
        return [(g, {"surface": s, "hole": h}) for g, s, h in feats] + [(rough, {"surface": "rough", "hole": 99})]
    def marker(feats, offset=None):
        tees = HD.place_tees([back], [], GREEN, [_yd(290.0), _yd(200.0)])
        HD.fairway_markers(tees, [], GREEN, ground=None if feats is None else HD.marker_ground(feats, 1),
                           offset=offset)
        return tees[1]
    on_line = np.array([0.0, 100.0])                                  # 200 m out on the leg
    fw = box(6, 60, 40, 200)                                          # the hole's fairway, right of the leg
    pond, bunker = box(-60, 70, -15, 130), box(-12, 94, -6, 106)      # the leg passes 6 m from the bunker
    t = marker(course((fw, "fairway", 1), (pond, "water", 99), (bunker, "bunker", 1)))
    p = Point(t["pos"])
    assert t["source"] == "fairway_marker" and abs(t["measured"] - _yd(200.0)) < 0.5
    assert fw.contains(p) and p.x < 8, "on the fairway, as near the leg as it can be"
    fw_bunker = box(6, 94, 12, 106)                                   # a bunker on the fairway's near edge
    t = marker(course((fw.difference(fw_bunker), "fairway", 1), (fw_bunker, "bunker", 1), (pond, "water", 99)))
    p = Point(t["pos"])
    assert fw.contains(p) and p.distance(fw_bunker) >= HD.FAIRWAY_MARKER_CLEARANCE - 1e-6
    path = LineString([(0, 0), (0, 300)]).buffer(1.2)                 # a cart path along the leg, no fairway
    t = marker(course((path, "cartpath", 98), (box(-30, 90, -2, 110), "semirough", 1)))
    assert t["source"] == "fairway_marker" and -30 < t["pos"][0] < -2, "semirough beats rough; never the path"
    t = marker(course())                                              # rough all round: the spot on the leg
    assert t["source"] == "fairway_marker" and np.allclose(t["pos"], on_line)
    t = marker(course((box(-40, 60, 40, 140), "water", 99)))          # a lake across the leg
    assert t["source"] == "pad" and t["pad"] is back
    t = marker(course((box(-40, 60, 40, 140), "water", 99)), offset=60.0)
    assert t["source"] == "fairway_marker" and abs(t["pos"][0]) > 45
    t = marker(None)                                                   # no surfaces: the old rule
    assert t["source"] == "fairway_marker" and np.allclose(t["pos"], on_line)


def test_a_wetland_hazard_stays_a_penalty_area_in_the_hole_data():
    """A golf water hazard mapped as a wetland has no water surface any more (it is not to be carved as a pond), but it
    is still a penalty area: the holes whose corridor it reaches list it among their hazards (GreenKeeper), lateral or
    not as OSM maps it, clipped to the build area."""
    from shapely.geometry import LineString
    G = [(1, {"golf": "lateral_water_hazard", "natural": "wetland", "wetland": "reedbed"}, box(20, 100, 120, 160)),
         (2, {"golf": "water_hazard", "natural": "wetland"}, box(-300, 0, -200, 50)),             # outside the build
         (3, {"golf": "water_hazard", "natural": "water"}, box(60, 200, 90, 230)),         # a pond: a water surface
         (4, {"natural": "wetland"}, box(-40, 100, -20, 140)),                             # no golf hazard
         (5, {"golf": "lateral_water_hazard", "natural": "wetland"}, box(390, 0, 500, 40))]
    areas = HD.penalty_areas(G, aoi=box(-150, -50, 450, 350))
    assert sorted((round(g.area), k) for g, k in areas) == [(2400, "lateral_water"), (6000, "lateral_water")]
    assert HD.penalty_areas([(2, {"golf": "water_hazard", "natural": "wetland"}, box(0, 0, 10, 10))])[0][1] == "water"
    play = LineString([(0, 0), (0, 300)])
    hz = HD.penalty_hazards(areas, play.buffer(40))
    assert [(z["type"], z["area_m2"]) for z in hz] == [("lateral_water", 6000.0)]
    assert hz[0]["polygon_utm"][0] == hz[0]["polygon_utm"][-1] and len(hz[0]["utm_centroid"]) == 2


def test_ground_inside_a_penalty_area_is_not_a_second_hazard():
    """The reedbed's own ground is native area and deep rough: the native polygons inside it were listed as native-area
    hazards inside the lateral hazard's ring (Deer Ridge holes 7, 8, 11, 12: 2-5 more each). Water and native surfaces
    over 50 m2 in the corridor are hazards, except those lying mostly inside a penalty area."""
    from shapely.geometry import LineString
    corridor = LineString([(0, 0), (0, 300)]).buffer(40)
    reed = box(10, 100, 60, 160)
    feats = [(box(15, 110, 30, 130), {"surface": "native", "hole": 99}),       # reeds' ground, inside the reedbed
             (box(-30, 10, -10, 30), {"surface": "native", "hole": 99}),       # a native area elsewhere
             (box(-20, 200, 10, 230), {"surface": "water", "hole": 99}),
             (box(0, 50, 5, 55), {"surface": "native", "hole": 99})]           # under 50 m2
    hz = HD.surface_hazards(feats, corridor, [(reed, "lateral_water")])
    assert sorted((z["type"], z["area_m2"]) for z in hz) == [("native_area", 400.0), ("water", 900.0)]
    assert len(HD.surface_hazards(feats, corridor)) == 3


def test_native_areas_off_the_course_are_not_hazards():
    """The classifier calls a ploughed field native: Whistle Bear's holes.json listed fields across Dickie Settlement
    Road (69,952 m2 on hole 3) and patches past the west edge as hazards, wholly outside the course outline
    (leisure=golf_course). A native-area hazard is the part of it inside the outline, over 50 m2. Water off the outline
    stays a hazard: Deer Ridge's Grand River runs outside its outline beside holes 8 and 14, and it is in play."""
    from shapely.geometry import LineString
    corridor = LineString([(0, 0), (0, 300)]).buffer(40)
    course = box(-30, -20, 30, 320)
    feats = [(box(35, 0, 200, 300), {"surface": "native", "hole": 99}),      # a field across the road
             (box(10, 100, 50, 120), {"surface": "native", "hole": 99}),     # crosses the outline: 400 m2 inside
             (box(-35, 200, -25, 210), {"surface": "native", "hole": 99}),   # 50 m2 inside (under the limit)
             (box(-20, 10, 0, 30), {"surface": "native", "hole": 99}),       # inside
             (box(-60, 50, -32, 90), {"surface": "water", "hole": 99})]      # a river off the outline
    hz = HD.surface_hazards(feats, corridor, course=course)
    assert sorted((z["type"], z["area_m2"]) for z in hz) == [("native_area", 400.0), ("native_area", 400.0),
                                                             ("water", 1120.0)]
    clipped = next(z for z in hz if z["utm_centroid"][1] == 110.0)
    assert max(x for x, _ in clipped["polygon_utm"]) == 30.0 and clipped["utm_centroid"][0] == 20.0
    inside = next(z for z in hz if z["utm_centroid"] == [-10.0, 20.0])
    assert inside["polygon_utm"] == [[round(x, 2), round(y, 2)] for x, y in feats[3][0].exterior.coords]
    assert len(HD.surface_hazards(feats, corridor)) == 5     # no outline: every native area is kept
