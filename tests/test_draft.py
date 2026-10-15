"""Unit tests for draft_features.py (golf features drafted from the photo, the LiDAR and the GPS layout points) on
synthetic rasters."""
import json
import sys
from pathlib import Path

import numpy as np
from rasterio.transform import from_origin
from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import draft_features as D  # noqa: E402

RES = 0.6


def disc(n, cy, cx, r_px):
    yy, xx = np.mgrid[:n, :n]
    return np.hypot(yy - cy, xx - cx) <= r_px


def test_turf_rule_keeps_bright_smooth_high_nir_areas_and_drops_specks():
    """Zoysia at Brambles (NAIP, May): NIR high, bright and yellow, smooth. Meadow is darker in NIR; a 3 x 3 px speck of
    turf colour (a roof, a dry patch) is below the minimum area."""
    n = 200
    nir = np.full((n, n), 190.0); L = np.full((n, n), 55.0); b = np.full((n, n), 25.0)
    fair = disc(n, 100, 100, 40)
    nir[fair], L[fair], b[fair] = 230.0, 75.0, 30.0
    nir[10:13, 10:13], L[10:13, 10:13], b[10:13, 10:13] = 230.0, 75.0, 30.0
    m = D.turf_mask(nir, L, b, RES, dict(nir_min=205, L_min=60, b_min=18, tex_max=6.0, min_area=100.0))
    assert m[100, 100] and not m[11, 11] and not m[100, 160]
    assert abs(m.sum() - fair.sum()) < 0.05 * fair.sum()


def test_green_grow_stops_before_it_leaks_into_the_fairway():
    """A green (feature value 10) in a fairway of close colour (13), meadow beyond (30). A tight threshold keeps the
    green; looser ones spill along the fairway outside the green's GPS depth: the largest threshold that stays inside
    1.5 x the radius wins."""
    n = 160
    F = np.full((n, n, 1), 30.0)
    F[40:120, 20:140] = 13.0                     # fairway band
    g = disc(n, 80, 80, 20)
    F[g] = 10.0
    m, t = D.grow_green(F, (80, 80), 20.0, thresholds=(2, 3, 4, 5, 8), max_outside=0.04, max_area_ratio=1.6)
    assert t == 2 or t == 3
    assert abs(m.sum() - g.sum()) < 0.1 * g.sum()


def test_green_grow_takes_the_whole_green_when_it_stands_out():
    n = 160
    F = np.full((n, n, 1), 30.0)
    g = disc(n, 80, 80, 25)
    F[g, 0] = 10.0 + np.random.default_rng(0).normal(0, 0.8, g.sum())  # mowing stripes
    m, t = D.grow_green(F, (80, 80), 25.0, thresholds=(1, 2, 4, 8), max_outside=0.04, max_area_ratio=1.6)
    assert t == 8 and abs(m.sum() - g.sum()) < 0.05 * g.sum()


def test_green_grow_without_a_clean_threshold_falls_back_to_the_gps_disc():
    """Every threshold leaks (the seed sits in a big uniform area): use the GPS green (radius = half the depth)."""
    n = 160
    F = np.full((n, n, 1), 10.0)
    m, t = D.grow_green(F, (80, 80), 20.0, thresholds=(2, 4), max_outside=0.04, max_area_ratio=1.6)
    assert t is None
    assert abs(m.sum() - np.pi * 20 ** 2) < 0.05 * np.pi * 20 ** 2


def test_bunkers_are_compact_sand_blobs_not_paths():
    """Bare, bright sand: a 8 x 6 m bunker stays; a 3 m wide, 90 m long gravel path of the same colour goes."""
    n = 220
    m = np.zeros((n, n), bool)
    m[40:53, 40:50] = True                    # bunker
    m[150:155, 10:160] = True                 # path
    out = D.compact_blobs(m, RES, min_area=8.0, max_elong=6.0)
    assert out[45, 45] and not out[152, 80]


def test_hollow_test_keeps_sunken_sand_only():
    n = 120
    dem = np.zeros((n, n), np.float32)
    a = np.zeros((n, n), bool); a[20:30, 20:30] = True; dem[a] = -0.4      # bunker floor below its surround
    b = np.zeros((n, n), bool); b[80:90, 80:90] = True                     # flat bare patch
    assert D.is_hollow(dem, a, RES, ring_m=2.0, depth=0.15)
    assert not D.is_hollow(dem, b, RES, ring_m=2.0, depth=0.15)


def test_layout_points_group_tees_and_greens_by_hole(tmp_path):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"hole": 2, "kind": "tee", "tee": "back"}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
        {"type": "Feature", "properties": {"hole": 2, "kind": "tee", "tee": "front"}, "geometry": {"type": "Point", "coordinates": [0, 50]}},
        {"type": "Feature", "properties": {"hole": 2, "kind": "green_front"}, "geometry": {"type": "Point", "coordinates": [0, 300]}},
        {"type": "Feature", "properties": {"hole": 2, "kind": "green_center"}, "geometry": {"type": "Point", "coordinates": [0, 315]}},
        {"type": "Feature", "properties": {"hole": 2, "kind": "green_back"}, "geometry": {"type": "Point", "coordinates": [0, 330]}},
    ]}
    p = tmp_path / "layout.geojson"; p.write_text(json.dumps(fc))
    L = D.layout_points(p)
    assert L[2]["tees"] == {"back": (0.0, 0.0), "front": (0.0, 50.0)}
    assert L[2]["green"] == (0.0, 315.0) and L[2]["depth"] == 30.0


def test_polygons_round_trip_through_the_grid():
    T = from_origin(1000.0, 2000.0, RES, RES)
    m = disc(100, 50, 50, 20)
    ps = D.mask_polys(m, T, simplify=0.2)
    assert len(ps) == 1
    p = ps[0]
    assert abs(p.area - m.sum() * RES * RES) < 0.05 * p.area
    assert p.contains(Point(1000 + 50.5 * RES, 2000 - 50.5 * RES))


def test_merge_keeps_drawn_features_and_replaces_the_previous_draft():
    drawn = {"type": "Feature", "properties": {"golf": "hole", "ref": "1"},
             "geometry": {"type": "LineString", "coordinates": [[0, 0], [0, 100]]}}
    old = {"type": "Feature", "properties": {"golf": "green", "draft": "yes"},
           "geometry": {"type": "Point", "coordinates": [5, 5]}}
    fc = {"type": "FeatureCollection", "name": "x", "features": [drawn, old]}
    new = [{"type": "Feature", "properties": {"golf": "bunker", "draft": "yes"},
            "geometry": {"type": "Point", "coordinates": [1, 1]}}]
    out = D.merge(fc, new)
    assert out["name"] == "x"
    assert [f["properties"].get("golf") for f in out["features"]] == ["hole", "bunker"]


def test_outline_covers_the_corridors_and_the_turf():
    from shapely.geometry import LineString, box
    lines = [LineString([(0, 0), (0, 300)]), LineString([(100, 300), (100, 0)])]
    turf = [box(-20, 280, 120, 320)]
    o = D.outline(lines, turf, corridor=40.0, close=30.0)
    assert o.contains(Point(0, 150)) and o.contains(Point(100, 150)) and o.contains(Point(50, 300))
    assert o.contains(Point(50, 150))          # the gap between two parallel holes is course (closed)
    assert not o.contains(Point(0, -100))
