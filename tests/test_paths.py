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
