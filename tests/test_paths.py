"""Unit tests for cart-path tracing (trace_paths.py) on synthetic rasters."""
import sys
from pathlib import Path

import numpy as np
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import trace_paths as P  # noqa: E402

RES = 0.25
T = from_origin(1000.0, 2000.0, RES, RES)


def strip(mask, r0, r1, c0, c1):
    mask[r0:r1, c0:c1] = True


def test_centrelines_keep_long_path_wide_strips():
    m = np.zeros((400, 400), bool)
    strip(m, 100, 108, 20, 380)        # 2 m wide, 90 m long, east-west
    strip(m, 100, 300, 372, 380)       # 2 m wide, 50 m long, turning south (L shape)
    lines = P.centrelines(m, T)
    total = sum(g.length for g in lines)
    assert 125 < total < 145, total
    assert all(g.geom_type == "LineString" for g in lines)
    # the line runs down the middle of the strip (row 104 -> northing 2000 - 104.0 * 0.25)
    g = max(lines, key=lambda g: g.length)
    pts = [g.interpolate(t, normalized=True) for t in np.linspace(0, 1, 200)]
    ys = np.array([p.y for p in pts if 1020 < p.x < 1080])
    assert len(ys) and np.abs(ys - (2000 - 104 * RES)).max() < 0.4


def test_centrelines_reject_blobs_short_bits_and_hairlines():
    m = np.zeros((400, 400), bool)
    strip(m, 50, 110, 50, 110)          # 15 m x 15 m blob (a green / parking area)
    strip(m, 200, 208, 50, 90)          # 2 m wide but only 10 m long
    strip(m, 300, 301, 20, 380)         # 0.25 m hairline (a shadow streak)
    assert P.centrelines(m, T) == []


def test_bridge_joins_aligned_gaps_only():
    from shapely.geometry import LineString
    a = LineString([(0, 0), (40, 0)])
    b = LineString([(44, 0.5), (90, 1)])            # 4 m gap, aligned with both ends: bridged
    c = LineString([(40, 3), (40, 40)])             # 3 m from a's end but at 90 degrees to it: not bridged
    out = P.bridge([a, b, c], max_gap=6.0, max_angle=35)
    gap = LineString([(40, 0), (44, 0.5)]).length
    assert sorted(round(g.length, 1) for g in out) == [37.0, round(a.length + b.length + gap, 1)]


def test_candidates_rules():
    ridge = np.array([0.1, 0.1, 0.1, 0.01, 0.1], float)
    L = np.array([55, 55, 20, 55, 55], float)
    ndvi = np.array([0.05, 0.45, 0.05, 0.05, 0.05], float)
    excl = np.array([0, 0, 0, 0, 1], bool)
    # NDVI ridge on bare ground: yes; ridge in live turf (mowing seam): no; black (water / shaded roof): no;
    # bare but not a line (a green, a bunker floor): no; excluded (near a mapped green / bunker / building): no
    assert P.candidates(ridge, L, ndvi, excl).tolist() == [True, False, False, False, False]


def test_ndvi_ridges_find_a_bare_strip_in_turf():
    ndvi = np.full((200, 200), 0.45)
    ndvi[96:104, :] = 0.02                  # 2 m bare strip at 0.25 m
    r = P.ndvi_ridges(ndvi, 0.25)
    assert r[100, 100] > 5 * max(r[60, 100], 1e-6) and r[100, 100] > P.RIDGE_MIN


def test_long_bridges_need_facing_ends_and_a_clear_corridor():
    from shapely.geometry import LineString
    a = LineString([(0, 0), (60, 0)])
    b = LineString([(85, 1), (150, 2)])              # 25 m gap under a spruce: both ends face each other
    c = LineString([(60, 25), (60, 90)])             # 25 m from a's end but at 90 degrees: never bridged
    out = P.bridge([a, b, c], max_gap=35.0, max_angle=25)
    assert sorted(round(g.length) for g in out) == [65, 150]
    # the same gap is refused when the connector would cross an excluded area (a green, a bunker, a fairway ...)
    out = P.bridge([a, b, c], max_gap=35.0, max_angle=25, ok=lambda seg: False)
    assert sorted(round(g.length) for g in out) == [60, 65, 65]


def test_a_photo_without_nir_traces_no_paths_and_says_so(tmp_path, monkeypatch, capsys):
    """The paths are traced from NDVI. With a 3-band photo (most RGB-only orthophoto services) the step stopped the
    build ('needs a 4-band photo') although the classifier copes without NIR: it now traces nothing, says so once
    (naming the [tuning] key that skips the step), and leaves an empty file so a stale trace is not reused."""
    import json
    import surface_classify as S
    monkeypatch.setattr(S, "has_nir", lambda: False)
    monkeypatch.setattr(S, "grid", lambda: (400, 400, T))
    monkeypatch.setattr(S, "osm_geoms", lambda: [])
    monkeypatch.setattr(S, "read_imagery_window", lambda T, r0, r1, c0, c1: np.full((3, r1 - r0, c1 - c0), 0.4, np.float32))
    monkeypatch.setattr(S, "read_nir_window", lambda *a: None)
    out = tmp_path / "paths_detected.geojson"
    out.write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                                                                           "geometry": None}]}))   # an older trace
    monkeypatch.setattr(P, "OUT", out)
    P.main()
    assert json.load(open(out))["features"] == []
    said = capsys.readouterr().out
    assert said.count("NIR") == 1 and "trace_paths = false" in said


def test_centrelines_take_a_width_range():
    """Brambles' gravel tracks are 3-6 m wide (NAIP 0.6 m): a 5 m strip is no path at the default 0.6-4.5 m range,
    but is one with width=(1.5, 7.0)."""
    m = np.zeros((400, 400), bool)
    strip(m, 100, 120, 20, 380)        # 5 m wide, 90 m long
    assert P.centrelines(m, T) == []
    lines = P.centrelines(m, T, width=(1.5, 7.0))
    assert 80 < sum(g.length for g in lines) < 95


def test_the_bank_of_a_lateral_water_hazard_is_not_traced_as_a_path(tmp_path, monkeypatch):
    """The rims of water features are NDVI ridges, so the tracer leaves out the ground within 2 m of mapped water. It
    tested golf=water_hazard and natural=water only: the bare bank of a pond mapped golf=lateral_water_hazard alone was
    traced as a cart path (a concrete stripe along the shore), although the build treats that pond as water."""
    import json
    from shapely.geometry import box
    import surface_classify as S
    nir = np.full((400, 400), 0.4 * 1.45 / 0.55, np.float32)       # turf: NDVI 0.45 on a grey (0.4) photo
    nir[192:200, 80:320] = 0.4 * 1.02 / 0.98                        # a 2 m bare bank (NDVI 0.02) along the pond's north edge
    monkeypatch.setattr(S, "has_nir", lambda: True)
    monkeypatch.setattr(S, "grid", lambda: (400, 400, T))
    monkeypatch.setattr(S, "read_imagery_window", lambda T, r0, r1, c0, c1: np.full((3, r1 - r0, c1 - c0), 0.4, np.float32))
    monkeypatch.setattr(S, "read_nir_window", lambda T, r0, r1, c0, c1: nir[r0:r1, c0:c1])
    monkeypatch.setattr(P, "OUT", tmp_path / "paths_detected.geojson")
    traced = {}
    for name, tags in (("unmapped", {}), ("natural=water", {"natural": "water"}),
                       ("lateral_water_hazard", {"golf": "lateral_water_hazard"})):
        G = [(1, {"leisure": "golf_course"}, box(1000, 1900, 1100, 2000)), (2, tags, box(1020, 1930, 1080, 1950))]
        monkeypatch.setattr(S, "osm_geoms", lambda G=G: G)
        P.main()
        traced[name] = sum(f["properties"]["length_m"] for f in json.load(open(P.OUT))["features"])
    assert traced["unmapped"] > 50 and traced["natural=water"] == 0 and traced["lateral_water_hazard"] == 0, traced
