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
