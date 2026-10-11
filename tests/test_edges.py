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
