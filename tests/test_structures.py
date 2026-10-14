"""Unit tests for curated structures (features/structures.geojson) and their roofs (add_structures.roof_mesh)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import box, shape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config as C  # noqa: E402


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
    path = C.SOURCES / "structures.geojson"
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
    path = C.SOURCES / "patios.geojson"
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


def test_roof_shading_normals_ignore_lidar_noise():
    """Per-vertex normals of the noisy LiDAR roof made the clubhouse look like rock. Shading normals come from the
    roof smoothed over a few metres: a flat roof with +/- 15 cm noise shades as flat (within 6 degrees)."""
    from add_structures import roof_mesh, roof_normals
    rng = np.random.default_rng(0)
    noisy = lambda e, n, order=1: 344.0 + rng.normal(0, 0.15, np.atleast_1d(e).shape)
    V2, F, z, ground = roof_mesh(box(0, 0, 20, 12), _flat(340.0), _flat(340.0), 0, bdsm=noisy)
    N = roof_normals(V2, F, z)
    inner = (V2[:, 0] > 3) & (V2[:, 0] < 17) & (V2[:, 1] > 3) & (V2[:, 1] < 9)
    assert np.degrees(np.arccos(np.clip(N[inner, 2], -1, 1))).max() < 6.0


def test_roof_is_planar_hips_from_the_eaves():
    """The smoothed LiDAR surface still read as a lumpy blob. Roofs are rebuilt as planes: eave height + a fitted pitch
    times the distance to the wall line, capped at the LiDAR plateau. On an L-shaped hipped building with 10 cm LiDAR
    noise and rooftop units, the result matches the true hip faces closely and its faces are exactly planar."""
    import shapely
    from shapely.geometry import Polygon
    from add_structures import roof_mesh
    poly = Polygon([(0, 0), (30, 0), (30, 12), (12, 12), (12, 30), (0, 30)])
    rng = np.random.default_rng(1)
    def true_z(e, n):
        d = shapely.distance(shapely.points(np.c_[e, n]), poly.exterior)
        return 344.0 + np.minimum(0.7 * d, 4.2)                      # eaves 344, pitch 0.7, plateau 348.2
    def lidar(e, n, order=1):
        e = np.atleast_1d(e); n = np.atleast_1d(n)
        z = true_z(e, n) + rng.normal(0, 0.1, e.shape)
        unit = (np.abs(e - 6) < 1.2) & (np.abs(n - 20) < 1.2)        # a 2 m rooftop unit
        return np.where(unit, z + 1.5, z)
    V2, F, z, ground = roof_mesh(poly, _flat(355.0), _flat(340.0), 0, bdsm=lidar)
    err = z - true_z(V2[:, 0], V2[:, 1])
    assert np.sqrt(np.mean(err ** 2)) < 0.15 and np.abs(err).max() < 0.6
    edge = np.array([poly.exterior.distance(shapely.geometry.Point(p)) < 1e-6 for p in V2])
    assert np.abs(z[edge] - 344.0).max() < 0.15                      # one clean eave line


def test_large_roof_has_one_flat_top_over_a_lumpy_plateau():
    """On the clubhouse's patio wing a local cap followed rooftop units and tree-filled cells: the top of a big hipped
    roof must be one level plane even when the LiDAR plateau is lumpy."""
    import shapely
    from add_structures import roof_mesh
    poly = box(0, 0, 40, 30)
    rng = np.random.default_rng(2)
    bumps = rng.uniform(0, 40, (12, 2))
    def lidar(e, n, order=1):
        e = np.atleast_1d(e); n = np.atleast_1d(n)
        d = shapely.distance(shapely.points(np.c_[e, n]), poly.exterior)
        z = 344.0 + np.minimum(0.6 * d, 3.0)
        for bx, by in bumps:
            z = np.where(np.hypot(e - bx, n - by * 0.75) < 2.0, z + 1.2 * (d > 6), z)
        return z + rng.normal(0, 0.05, e.shape)
    V2, F, z, ground = roof_mesh(poly, _flat(355.0), _flat(340.0), 0, bdsm=lidar)
    d = shapely.distance(shapely.points(V2), poly.exterior)
    assert np.ptp(z[d > 7]) < 0.05


def test_gable_roof_keeps_its_gable_ends():
    """Houses with gable roofs came out hipped. A rectangular footprint whose LiDAR fits a gable better than a hip
    gets a ridge along its full length and triangular gable-end walls (wall-line vertices rise to the ridge)."""
    import shapely
    from add_structures import roof_mesh
    poly = box(0, 0, 20, 10).segmentize(1.0)
    rng = np.random.default_rng(4)
    gable = lambda e, n, order=1: 344.0 + 0.8 * (5 - np.abs(np.atleast_1d(n) - 5)) + rng.normal(0, 0.05, np.shape(e))
    V2, F, z, ground = roof_mesh(poly, _flat(355.0), _flat(340.0), 0, bdsm=gable)
    ridge = np.abs(V2[:, 1] - 5) < 0.3
    assert np.median(z[ridge]) > 347.6 and np.percentile(z[ridge & ((V2[:, 0] < 1) | (V2[:, 0] > 19))], 50) > 347.4
    end = (V2[:, 0] < 1e-6) & (np.abs(V2[:, 1] - 5) < 0.6)              # wall-line vertex at the gable apex
    assert end.any() and z[end].max() > 347.4


def test_hipped_rectangle_stays_hipped():
    from add_structures import roof_mesh
    import shapely
    poly = box(0, 0, 20, 10).segmentize(1.0)
    hip = lambda e, n, order=1: 344.0 + 0.8 * shapely.distance(shapely.points(np.c_[np.atleast_1d(e), np.atleast_1d(n)]), poly.exterior)
    V2, F, z, ground = roof_mesh(poly, _flat(355.0), _flat(340.0), 0, bdsm=hip)
    end = (V2[:, 0] < 1e-6) & (np.abs(V2[:, 1] - 5) < 0.6)
    assert z[end].max() < 344.6                                          # end walls stay at the eaves


def test_wall_colours_vary_between_houses():
    """Every house had the same white walls: a per-building wall colour (white, cream, beige siding, grey, brick)
    picked deterministically from the building id."""
    from add_structures import wall_colour
    cols = np.array([wall_colour(i) for i in range(40)])
    assert len({tuple(np.round(c, 3)) for c in cols}) >= 4
    assert np.all((cols > 0.2) & (cols <= 1.0))
    assert np.allclose(wall_colour(7), wall_colour(7))


def test_fountain_rises_from_the_water_level():
    """Hole 3's aerating fountain: a spray column from the water surface to about its height, and a foam ring on the
    water as wide as the disturbed ring in the 2025 photo (about 4 m; it must stay inside the pond)."""
    from add_structures import fountain_parts
    parts = fountain_parts((100.0, 200.0), 330.0, height=2.5)
    P = np.concatenate([p[0] for p in parts.values()])
    assert {"spray", "foam"} <= set(parts)
    assert abs(P[:, 2].min() - 330.0) < 0.05 and 2.2 <= P[:, 2].max() - 330.0 <= 2.8
    r = np.hypot(P[:, 0] - 100, P[:, 1] - 200)
    assert r.max() <= 4.0
    foam = parts["foam"][0]
    assert np.allclose(foam[:, 2], foam[0, 2]) and 0 < foam[0, 2] - 330.0 <= 0.05


def test_fountain_level_comes_from_the_pond_it_sits_in():
    from add_structures import water_level_at
    planes = [{"hole": 3, "level": 331.2, "polygon_utm": [[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]},
              {"hole": 5, "level": 320.0, "polygon_utm": [[50, 0], [70, 0], [70, 20], [50, 20], [50, 0]]}]
    assert water_level_at((10, 10), planes) == 331.2
    assert water_level_at((60, 5), planes) == 320.0
    assert water_level_at((40, 40), planes) is None


def test_parking_slots_fill_the_lot_in_rows_without_overlap():
    """Stalls of 2.6 x 5.5 m in back-to-back rows along the lot's long side, with 6.5 m aisles: inside the lot, apart,
    and aligned with the long axis."""
    import shapely
    from shapely.affinity import rotate
    from add_structures import parking_slots, SLOT_W, SLOT_L
    lot = rotate(box(0, 0, 60, 30), 20, origin=(0, 0))
    S = parking_slots(lot)
    assert len(S) >= 0.6 * lot.area / (SLOT_W * SLOT_L * 2.2)
    rects = [shapely.affinity.rotate(box(x - SLOT_W / 2, y - SLOT_L / 2, x + SLOT_W / 2, y + SLOT_L / 2),
                                     np.degrees(yaw), origin=(x, y)) for x, y, yaw in S]
    assert all(lot.buffer(0.01).contains(r) for r in rects)
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            assert rects[i].intersection(rects[j]).area < 0.05
    # a car's length runs across the rows, i.e. perpendicular to the long side (20 degrees)
    ang = np.degrees(S[:, 2]) % 180
    assert np.all(np.minimum(abs(ang - 20), 180 - abs(ang - 20)) < 1) or np.all(np.minimum(abs(ang - 110), 180 - abs(ang - 110)) < 1)


def test_cars_are_car_sized_and_parked_on_the_ground():
    from add_structures import car_parts
    parts = car_parts(10.0, 20.0, 300.0, 0.3, seed=4)
    P = np.concatenate([p[0] for p in parts])
    assert abs(P[:, 2].min() - 300.0) < 0.05
    assert 1.35 <= P[:, 2].max() - 300.0 <= 1.9
    # footprint in the car's own frame
    c, s = np.cos(-0.3), np.sin(-0.3)
    u = c * (P[:, 0] - 10) - s * (P[:, 1] - 20); v = s * (P[:, 0] - 10) + c * (P[:, 1] - 20)
    w, l = np.ptp(u), np.ptp(v)
    assert 1.6 <= w <= 2.0 and 4.2 <= l <= 5.2


def test_clubhouse_mulch_beds_are_valid_and_clear_of_the_buildings_and_patio():
    from shapely.ops import unary_union
    feats = [f for n in ("clubhouse_mulch", "grounds_mulch") for f in json.load(open(C.SOURCES / f"overrides/{n}.geojson"))["features"]]
    beds = [shape(f["geometry"]) for f in feats]
    props = [f["properties"] for f in feats]
    assert beds and all(g.is_valid and 5 < g.area < 300 for g in beds)
    assert all(p["surface"] == "native" and p["hole"] == 99 for p in props)
    patio = unary_union([shape(f["geometry"]) for f in json.load(open(C.SOURCES / "patios.geojson"))["features"]])
    assert all(g.intersection(patio).area < 0.15 * g.area for g in beds)


def test_curated_fountains_sit_well_inside_a_pond():
    from surface_classify import osm_geoms
    from shapely.geometry import Point
    ponds = [g for oid, t, g in osm_geoms() if ("water" in str(t)) and g.geom_type == "Polygon"]
    for f in json.load(open(C.SOURCES / "fountains.geojson"))["features"]:
        pt = Point(f["geometry"]["coordinates"])
        inside = [g for g in ponds if g.contains(pt)]
        assert inside and inside[0].exterior.distance(pt) > 4.0


def test_parking_slots_keep_clear_of_buildings_in_the_lot():
    """The clubhouse lot polygon overlaps a building: cars were parked through its walls. Stalls touching an
    excluded footprint (buffered 1 m) are dropped."""
    from add_structures import parking_slots, SLOT_W, SLOT_L
    lot = box(0, 0, 60, 30)
    bld = box(20, 5, 35, 20)
    S = parking_slots(lot, exclude=bld)
    rects = [box(x - SLOT_W / 2, y - SLOT_L / 2, x + SLOT_W / 2, y + SLOT_L / 2) for x, y, _ in S]
    assert len(S) > 20 and all(r.distance(bld) >= 0.99 for r in rects)


def test_fountain_spray_is_separate_jets_not_a_dome():
    """A closed spray umbrella read as a glass dome: the spray is thin arcing jets, so at mid height the spray
    covers only a small part of its circle."""
    from add_structures import fountain_parts
    P, N, UV, I = fountain_parts((0.0, 0.0), 0.0, height=2.5)["spray"]
    w = np.random.default_rng(0).dirichlet((1, 1, 1), 40)                  # points spread over each triangle
    pts = np.einsum("kj,tjc->tkc", w, P[I]).reshape(-1, 3)
    pts = pts[(np.abs(pts[:, 2] - 1.2) < 0.4) & (np.hypot(pts[:, 0], pts[:, 1]) > 0.6)]
    ang = np.degrees(np.arctan2(pts[:, 1], pts[:, 0]))
    covered = len(np.unique(np.floor((ang + 180) / 2))) / 180          # fraction of 2-degree sectors with spray
    assert 0.05 < covered < 0.6


def test_cars_have_rounded_bodies_and_lights():
    """Box cars looked like crates up close: the body has chamfered corners in plan and tucks in above the belt
    line, the cabin sits on it, and each car has head and tail lights at its ends."""
    from add_structures import car_parts
    parts = car_parts(0.0, 0.0, 0.0, 0.0, seed=2)
    kinds = [p[4] for p in parts]
    assert {"paint", "glass", "tyre", "headlight", "taillight"} <= set(kinds)
    body = next(p[0] for p in parts if p[4] == "paint")
    low = body[body[:, 2] < body[:, 2].min() + 0.01]
    assert len(np.unique(np.round(low[:, :2], 3), axis=0)) >= 8                 # chamfered plan, not 4 corners
    top = body[body[:, 2] > body[:, 2].max() - 0.01]
    assert np.abs(top[:, 0]).max() < np.abs(low[:, 0]).max() - 0.03            # tumblehome
    head = np.concatenate([p[0] for p in parts if p[4] == "headlight"])
    tail = np.concatenate([p[0] for p in parts if p[4] == "taillight"])
    assert head[:, 1].min() > 1.8 and tail[:, 1].max() < -1.8                  # front at +y, rear at -y
