"""Unit tests for the OPCD edge features (bunker lips, water edge/bed/plane). Fast: synthetic data only."""
import sys
from pathlib import Path

import numpy as np
from rasterio.transform import from_origin
from shapely.geometry import box, Point

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import edges  # noqa: E402
from build_terrain_mesh import blended_dem  # noqa: E402


def test_derive_rings_splits_bunker_into_sand_and_lip():
    bunker = box(0, 0, 10, 6)
    feats = [(bunker, "bunker", 3), (box(20, 0, 30, 10), "fairway", 3)]
    out, rings = edges.derive_rings(feats, zone=box(-50, -50, 50, 50))
    sand = [g for g, s, h in out if s == "bunker"]
    lip = [g for g, s, h in out if s == "bunkerlip"]
    assert len(sand) == 1 and len(lip) == 1 and len(rings) == 1
    assert abs(sand[0].area + lip[0].area - bunker.area) < 1e-6          # still a partition
    assert abs(lip[0].area / bunker.length - edges.LIP_W) < 0.01          # band width = LIP_W
    assert [h for g, s, h in out if s == "bunkerlip"] == [3]             # lip keeps the bunker's hole
    assert any(s == "fairway" for _, s, _ in out)                        # other surfaces untouched


def test_derive_rings_only_inside_the_detail_zone_and_for_playable_holes():
    feats = [(box(0, 0, 10, 6), "bunker", 22), (box(100, 0, 110, 6), "bunker", 4)]
    out, rings = edges.derive_rings(feats, zone=box(-50, -50, 50, 50))
    assert not any(s == "bunkerlip" for _, s, _ in out)  # Lake-nine bunker (22) and the one outside the zone (4)


def test_derive_rings_water_edge():
    pond = Point(0, 0).buffer(20)
    out, rings = edges.derive_rings([(pond, "water", 99)], zone=box(-50, -50, 50, 50))
    edge = [g for g, s, h in out if s == "wateredge"]
    assert len(edge) == 1 and abs(edge[0].area / pond.length - edges.WATER_EDGE_W) < 0.01


def test_lip_drop_is_zero_on_the_edge_and_full_inside():
    """OPCD V4 add-on defaults: bunker lip depth 0.05 m with a 'concave' lip profile (drops quickly at the edge)."""
    assert edges.LIP_DEPTH == 0.05
    bunker = box(0, 0, 10, 6)
    _, rings = edges.derive_rings([(bunker, "bunker", 1)], zone=box(-50, -50, 50, 50))
    pts = np.array([[0.0, 3.0], [edges.LIP_W / 2, 3.0], [edges.LIP_W, 3.0], [5.0, 3.0], [-1.0, 3.0]])
    d = edges.lip_drop(pts, rings)
    assert np.allclose(d[[0, 2, 3, 4]], [0.0, edges.LIP_DEPTH, edges.LIP_DEPTH, 0.0], atol=1e-6)
    assert d[1] > 0.6 * edges.LIP_DEPTH            # concave: most of the drop happens right at the edge


def test_label_rings_relabels_triangles_inside_rings():
    bunker = box(0, 0, 10, 6)
    _, rings = edges.derive_rings([(bunker, "bunker", 5)], zone=box(-50, -50, 50, 50))
    cent = np.array([[0.04, 3.0], [5.0, 3.0], [-0.04, 3.0]])  # in the lip, in the sand, outside
    surf = np.array([1, 1, 0]); hole = np.array([5, 5, 99])
    names = ["rough", "bunker", "bunkerlip"]
    s2, h2 = edges.label_rings(cent, surf, hole, rings, {n: i for i, n in enumerate(names)})
    assert list(s2) == [2, 1, 0] and list(h2) == [5, 5, 99]


RES = 0.25


def _bowl(n=240):
    """A gentle bowl (lowest in the middle) on a RES grid; pond in the middle."""
    T = from_origin(0.0, n * RES, RES, RES)
    x = (np.arange(n) + 0.5) * RES; c = n * RES / 2
    X, Y = np.meshgrid(x, x[::-1])
    return 100.0 + 0.02 * ((X - c) ** 2 + (Y - c) ** 2) ** 0.5 * 3, T, c


def test_water_bed_is_below_the_plane_and_deepens_offshore():
    dem, T, c = _bowl()
    pond = Point(c, c).buffer(10.0)
    out = blended_dem(dem, T, [(pond, "water", 99)])
    lv = edges.water_levels([(pond, "water", 99)], dem, T)
    assert len(lv) == 1
    level = lv[0][1]
    n = dem.shape[0]
    yy, xx = np.mgrid[0:n, 0:n]
    r = np.hypot((xx + 0.5) * RES - c, (n - yy - 0.5) * RES - c)
    centre = out[r < 1.0].mean(); near_shore = out[(r > 9.0) & (r < 9.6)].mean()
    assert centre < level - 0.5                     # a real bed, well below the water surface
    assert near_shore > centre                      # shelving bed
    assert out[r < 9.8].max() < level               # nothing pokes through the water plane


def test_no_land_below_the_water_plane_within_the_outset():
    """The WaterPlane extends PLANE_OUTSET under the banks; land there must stay above it or the water spills."""
    dem, T, c = _bowl()
    # a pond whose polygon is off-centre: part of its outset ring lies in the low middle of the bowl
    pond = Point(c + 6, c).buffer(5.0)
    out = blended_dem(dem, T, [(pond, "water", 99)])
    level = edges.water_levels([(pond, "water", 99)], dem, T)[0][1]
    plane = edges.water_plane_polygon(pond, out, T, level)
    n = dem.shape[0]
    from rasterio.features import rasterize
    ring = rasterize([(plane.difference(pond.buffer(0.3)), 1)], out_shape=dem.shape, transform=T).astype(bool)
    assert ring.any()
    assert out[ring].min() >= level - 1e-6, f"land {level - out[ring].min():.3f} m below the water plane"
    assert plane.contains(pond.buffer(-0.01))


def test_grass_masks_clear_sand_and_paths_and_thin_under_canopy():
    """3DG vertex density (R): 0 at the edge of sand/paths, full away from them, thinned under canopy; 0 off grass."""
    import grass_spec
    from rasterio.transform import from_origin
    # a 20 x 10 m strip of 0.5 m cells: x < 5 is bunker, the rest rough
    xs, ys = np.meshgrid(np.arange(0, 20.01, 0.5), np.arange(0, 10.01, 0.5))
    V = np.c_[xs.ravel(), ys.ravel()]
    nx = xs.shape[1]
    F, S = [], []
    names = ["rough", "bunker"]
    for j in range(xs.shape[0] - 1):
        for i in range(nx - 1):
            a = j * nx + i
            s = 1 if xs[0, i] < 5 else 0
            F += [[a, a + 1, a + nx + 1], [a, a + nx + 1, a + nx]]; S += [s, s]
    F = np.array(F); S = np.array(S)
    chm = np.zeros((40, 80), np.float32); chm[:, 60:] = 10.0      # a tree canopy over x >= 15 m (0.25 m grid)
    chm_T = from_origin(0, 10, 0.25, 0.25)
    M = grass_spec.vertex_masks(V, F, S, names, chm=chm, chm_T=chm_T)
    at = lambda x, y: M[np.argmin(np.hypot(V[:, 0] - x, V[:, 1] - y))]
    assert at(5.0, 5.0)[0] == 0.0                 # on the bunker edge
    assert at(2.0, 5.0)[0] == 0.0                 # inside the bunker (not a grass vertex)
    assert at(10.0, 5.0)[0] == 1.0                # open rough
    assert abs(at(18.0, 5.0)[0] - grass_spec.CANOPY[1]) < 1e-6   # under the tree
    assert 0.0 < at(5.5, 5.0)[0] < 1.0            # ramp next to the sand


def _valley(length=600.0, fall=2.0, res=0.5, half=30.0):
    """A river 20 m wide along x (y in -10..10), its banks at the water's edge falling `fall` m over `length` m and
    rising 0.5 m per m away from it; the LiDAR over the water 5 cm below the edge (Deer Ridge's river: the DEM over it
    has the median of its shoreline)."""
    nx, ny = int(length / res), int(2 * half / res)
    T = from_origin(0.0, half, res, res)
    X, Y = np.meshgrid((np.arange(nx) + 0.5) * res, half - (np.arange(ny) + 0.5) * res)
    edge = 100.0 - fall * X / length
    dem = edge + 0.5 * np.maximum(0.0, np.abs(Y) - 10.0) - 0.05 * (np.abs(Y) < 10.0)
    return dem, T, box(0.0, -10.0, length, 10.0), lambda x: 100.0 - fall * x / length


def test_a_river_falls_in_reaches_each_flat_at_its_own_level():
    """Deer Ridge: the Grand River falls 1.4-2.2 m across the course (a Whistle Bear creek 1.65 m), and a water body had
    one flat level at its lowest 20 % shoreline: the water 1.9 m below the upper bank, a levee along the lower. A body
    whose local level (the 20th percentile of the shoreline within 60 m) falls more than WATER_STEP is cut across into
    reaches falling at most that much, each flat at the local level of its lower end; a pond keeps its one level."""
    from shapely.ops import unary_union
    dem, T, river, bank = _valley()
    reaches = edges.water_reaches(river, dem, T)
    assert len(reaches) >= 6
    assert abs(sum(r.area for r, _ in reaches) - river.area) < 1e-6 and abs(unary_union([r for r, _ in reaches]).area - river.area) < 1e-6
    by_x = sorted(reaches, key=lambda r: r[0].centroid.x)
    assert all(a[1] > b[1] for a, b in zip(by_x[:-1], by_x[1:])), "the levels fall downstream"
    for r, lv in reaches:
        x0, _, x1, _ = r.bounds
        assert lv <= bank(x1) + 0.01, "never above its banks"
        assert bank(x0) - lv < edges.WATER_STEP + 0.25, "no trench deeper than a step"
    bowl, Tb, c = _bowl()
    pond = Point(c, c).buffer(10.0)
    ((p, lv),) = edges.water_reaches(pond, bowl, Tb)
    assert p is pond and lv == edges.water_levels([(pond, "water", 99)], bowl, Tb)[0][1]


def test_a_pond_falling_at_a_cascade_is_cut_at_the_cascade():
    """Whistle Bear: a pond (OSM way 936553651) falls 1.65 m at a rock cascade, but the local level (the 20th
    percentile of the shoreline within 60 m) of the upper pond's shore near it is the lower pond's, so the cut fell
    20-45 m upstream in open water and 1,000 m2 of the upper pond took the lower plane, 1.4 m below its water. The
    cut falls where the shoreline's level changes, and each side keeps a level at or below its own banks."""
    from shapely.ops import unary_union
    res, half, fall, at = 0.5, 45.0, 1.65, 150.0
    nx, ny = int(300.0 / res), int(2 * half / res)
    T = from_origin(0.0, half, res, res)
    X, Y = np.meshgrid((np.arange(nx) + 0.5) * res, half - (np.arange(ny) + 0.5) * res)
    edge = np.where(X < at, 102.0, 102.0 - fall)
    dem = edge + 0.5 * np.maximum(0.0, np.abs(Y) - 15.0) - 0.05 * (np.abs(Y) < 15.0)
    pond = box(0.0, -15.0, 300.0, 15.0)
    reaches = edges.water_reaches(pond, dem, T)
    assert abs(unary_union([r for r, _ in reaches]).area - pond.area) < 1e-6
    level = lambda x: next(lv for r, lv in reaches if r.covers(Point(x, 0.0)))
    upper, lower = level(5.0), level(295.0)
    assert 102.0 - edges.WATER_STEP - 0.05 <= upper <= 102.0 and lower <= 102.0 - fall
    assert all(level(x) == upper for x in np.arange(5.0, at - 3.0, 2.0)), "upper pond on the lower plane"
    assert all(level(x) == lower for x in np.arange(at + 3.0, 296.0, 2.0)), "lower pond on the upper plane"


def test_a_river_is_carved_reach_by_reach_with_no_dam_and_no_spill():
    """The bed under each reach is below that reach's level (no ridge where reaches meet), each reach's WaterPlane
    covers no other reach's water, and the land under every plane's outset stays above it."""
    from rasterio.features import rasterize
    dem, T, river, _ = _valley()
    out = blended_dem(dem, T, [(river, "water", 99)])
    reaches = edges.water_reaches(river, dem, T)
    for r, lv in reaches:
        m = rasterize([(r.buffer(-0.3), 1)], out_shape=dem.shape, transform=T).astype(bool)
        assert m.any() and out[m].max() < lv
    planes = edges.water_planes(river, reaches, out, T)
    assert len(planes) >= len(reaches)
    for g, lv in planes:
        assert sum(g.intersection(r).area for r, l2 in reaches if l2 != lv) < 0.5
        bank = rasterize([(g.difference(river.buffer(0.3)), 1)], out_shape=dem.shape, transform=T).astype(bool)
        assert out[bank].min() >= lv - 1e-6, f"land {lv - out[bank].min():.3f} m below a water plane"
