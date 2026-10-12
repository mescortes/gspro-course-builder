"""Unit tests for curated structures (features/structures.geojson) and their roofs (add_structures.roof_mesh)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import box, shape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _flat(z):
    return lambda e, n, order=1: np.full(np.atleast_1d(e).shape, float(z))


def test_hipped_roof_is_a_pyramid_from_the_eaves():
    """A shelter built after the 2018 LiDAR has only trees in the DSM: its roof is synthetic, eaves at height minus
    roof:height and the apex at height (OSM roof tags), not the canopy."""
    from add_structures import roof_mesh
    poly = box(0, 0, 7, 7)
    V2, F, z, ground = roof_mesh(poly, _flat(355.0), _flat(340.0), 4.5,
                                 tags={"roof:shape": "hipped", "roof:height": "2.0"})
    assert ground == 340.0
    edge = np.array([poly.exterior.distance(__import__("shapely").geometry.Point(p)) < 1e-6 for p in V2])
    assert np.allclose(z[edge], 342.5)
    assert z.max() <= 344.5 + 1e-9 and z.max() > 343.8
    assert np.all(z >= 342.5 - 1e-9)


def test_curated_structures_are_valid_buildings():
    path = ROOT / "features/structures.geojson"
    if not path.exists():
        pytest.skip("no curated structures")
    fc = json.load(open(path))
    assert fc["features"]
    for f in fc["features"]:
        g = shape(f["geometry"]); p = f["properties"]
        assert g.geom_type == "Polygon" and g.is_valid and 6 <= g.area < 400, p   # add_buildings skips < 6 m2
        assert "building" in p and float(p["height"]) > 2 and p.get("note")


def _gable(ground, eave, ridge, w, nodata_box=None):
    """Building-class DSM of a gable roof (ridge along x at y = w/2); NaN (no class 6 return) inside nodata_box."""
    def f(e, n, order=1):
        e = np.atleast_1d(e).astype(float); n = np.atleast_1d(n).astype(float)
        z = eave + (ridge - eave) * np.clip(1 - np.abs(n - w / 2) / (w / 2), 0, 1)
        if nodata_box is not None:
            x0, y0, x1, y1 = nodata_box
            z = np.where((e >= x0) & (e <= x1) & (n >= y0) & (n <= y1), np.nan, z)
        return z
    return f


def test_roof_follows_building_returns_ridge_and_ignores_overhanging_trees():
    """The first-return DSM puts tree crowns on the clubhouse roof, and the 2.5 m median + clamp flattened its ridges
    into a slab. With the building-class DSM (LiDAR class 6) the gable survives and a crown over a corner, where there
    are no building returns, takes the neighbouring roof height instead of the canopy."""
    from add_structures import roof_mesh
    poly = box(0, 0, 24, 12)
    trees = lambda e, n, order=1: np.where((np.atleast_1d(e) > 18) & (np.atleast_1d(n) > 6), 362.0,
                                           _gable(340, 344, 348, 12)(e, n))
    bd = _gable(340, 344, 348, 12, nodata_box=(18, 6, 24, 12))
    V2, F, z, ground = roof_mesh(poly, trees, _flat(340.0), 0, bdsm=bd)
    ridge = np.abs(V2[:, 1] - 6) < 0.6
    eave = (V2[:, 1] < 1.2) | (V2[:, 1] > 10.8)
    assert np.median(z[ridge]) > 347.0
    assert np.median(z[eave]) < 345.0
    assert z.max() < 349.0                                 # no canopy on the roof
    corner = (V2[:, 0] > 19) & (V2[:, 1] > 7)
    assert corner.any() and z[corner].max() < 349.0


def test_patio_tables_sit_inside_the_paving_and_apart():
    from add_structures import patio_tables
    from shapely.geometry import Point, Polygon
    poly = Polygon([(0, 0), (20, 0), (20, 9), (0, 9)])
    T = patio_tables(poly)
    assert 8 <= len(T) <= 20
    d = np.hypot(*(T[:, None, :] - T[None, :, :]).transpose(2, 0, 1)) + np.eye(len(T)) * 99
    assert d.min() >= 3.0 - 1e-6
    assert all(poly.exterior.distance(Point(p)) >= 1.4 - 1e-6 and poly.contains(Point(p)) for p in T)


def test_curated_patios_are_valid():
    path = ROOT / "features/patios.geojson"
    if not path.exists():
        pytest.skip("no curated patios")
    for f in json.load(open(path))["features"]:
        g = shape(f["geometry"]); p = f["properties"]
        assert g.geom_type == "Polygon" and g.is_valid and 20 < g.area < 1000 and p["kind"] == "patio" and p.get("note")


def test_roof_uv_is_not_stretched_on_steep_slopes():
    """Top-down UVs smeared the tile texture into streaks on the clubhouse's steep hips: UV distances must match the
    surface distance on a slope as on a flat roof (texture tile 3 m)."""
    from add_structures import roof_uv
    P = np.array([[0, 0, 10.0], [0, 3, 13.0], [3, 0, 10.0]])          # a 45 degree plane rising to +y
    N = np.tile(np.array([0, -1, 1.0]) / np.sqrt(2), (3, 1))
    uv = roof_uv(P, N)
    up = np.linalg.norm(uv[1] - uv[0]); across = np.linalg.norm(uv[2] - uv[0])
    assert abs(up - np.sqrt(18) / 3) < 1e-6 and abs(across - 1.0) < 1e-6
    flat = roof_uv(np.array([[0, 0, 5.0], [3, 0, 5.0]]), np.tile([0, 0, 1.0], (2, 1)))
    assert abs(np.linalg.norm(flat[1] - flat[0]) - 1.0) < 1e-6


def test_roof_tint_is_one_colour_per_building():
    """Per-vertex photo colour (rooftop units, shadows, crowns) mottled the clubhouse roof like rock: one robust
    colour per roof, from the photo's median."""
    from add_structures import roof_tint
    rng = np.random.default_rng(0)
    col = np.clip(0.3 + rng.normal(0, 0.15, (500, 3)), 0, 1)
    t = roof_tint(col)
    assert t.shape == (500, 3) and np.ptp(t, axis=0).max() < 1e-9
