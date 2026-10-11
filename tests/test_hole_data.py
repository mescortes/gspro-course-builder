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
