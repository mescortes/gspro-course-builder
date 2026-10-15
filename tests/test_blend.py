"""Unit tests for the surface-smoothing blend of the DEM (build_terrain_mesh.blended_dem). Fast: synthetic data only."""
import sys
from pathlib import Path

import numpy as np
from rasterio.transform import from_origin
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_terrain_mesh import blended_dem  # noqa: E402

RES = 0.125


def _plane(slope=0.3, n=480):
    """A tilted plane (slope rise/run along +x) on a RES grid, and its transform."""
    T = from_origin(0.0, n * RES, RES, RES)
    x = (np.arange(n) + 0.5) * RES
    return np.tile(slope * x, (n, 1)), T, n * RES / 2


def test_green_blend_has_no_step_outside_the_fringe():
    """QA round 2: a 6-8 cm step ~1.5 m outside every green on a bank, where the normalised convolution falls back
    to the raw DEM. The blend must be continuous: the correction (out - dem) may only change smoothly."""
    dem, T, c = _plane()
    feats = [(Point(c, c).buffer(10.0), "green", 1)]
    d = blended_dem(dem, T, feats) - dem
    jump = np.abs(np.diff(d, axis=1)).max()
    assert jump < 0.01, f"largest cell-to-cell jump in the smoothing correction is {jump * 100:.1f} cm"


def test_green_blend_keeps_a_plane_inside_the_green():
    """Smoothing a plane must not bend it inside the putting surface (away from the edge)."""
    dem, T, c = _plane()
    feats = [(Point(c, c).buffer(10.0), "green", 1)]
    out = blended_dem(dem, T, feats)
    n = dem.shape[0]
    yy, xx = np.mgrid[0:n, 0:n]
    inner = np.hypot((xx + 0.5) * RES - c, (yy + 0.5) * RES - c) < 8.0
    assert np.abs(out - dem)[inner].max() < 0.005


def test_blend_does_not_reach_far_outside():
    """Beyond ~3 m from the green the terrain is the raw DEM."""
    dem, T, c = _plane()
    feats = [(Point(c, c).buffer(10.0), "green", 1)]
    out = blended_dem(dem, T, feats)
    n = dem.shape[0]
    yy, xx = np.mgrid[0:n, 0:n]
    far = np.hypot((xx + 0.5) * RES - c, (yy + 0.5) * RES - c) > 13.5
    assert np.abs(out - dem)[far].max() < 0.005


def test_green_blend_removes_noise_and_stays_continuous():
    """The point of the blend: centimetre LiDAR noise on a green is smoothed away, without creating a ring outside."""
    dem, T, c = _plane()
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.02, dem.shape)
    feats = [(Point(c, c).buffer(10.0), "green", 1)]
    out = blended_dem(dem + noise, T, feats)
    n = dem.shape[0]
    yy, xx = np.mgrid[0:n, 0:n]
    rad = np.hypot((xx + 0.5) * RES - c, (yy + 0.5) * RES - c)
    assert np.std((out - dem)[rad < 9.0]) < 0.006            # noise std 2 cm -> < 6 mm on the green
    ring = (rad > 10.5) & (rad < 13.0)
    smooth_ring = np.abs(np.diff(out - dem - noise, axis=1))[ring[:, 1:]].max()
    assert smooth_ring < 0.012                               # correction outside changes by < 12 mm per cell


def test_tee_without_a_lidar_deck_is_levelled():
    """Tees built after the 2018 LiDAR (holes 5, 8 back tees) have no deck in the terrain: the DEM under a tee that is
    not already flat is replaced by a plane of at most 1 % slope at the tee's mean height, feathered into the ground."""
    from build_terrain_mesh import level_tees
    from rasterio.features import rasterize
    dem, T, c = _plane(slope=0.06)
    rng = np.random.default_rng(0)
    dem = dem + 0.05 * np.sin(np.arange(dem.shape[1]) * RES * 1.3)[None, :] + rng.normal(0, 0.01, dem.shape)
    tee = Point(c, c).buffer(5.0)
    out = level_tees(dem.copy(), T, [tee])
    m = rasterize([(tee.buffer(-0.3), 1)], out_shape=dem.shape, transform=T).astype(bool)
    rr, cc = np.nonzero(m)
    A = np.c_[cc, rr, np.ones(len(rr))] * [RES, RES, 1]
    coef, res, *_ = np.linalg.lstsq(A, out[m], rcond=None)
    assert np.std(out[m] - A @ coef) < 0.005, "levelled tee is a plane"
    assert np.hypot(coef[0], coef[1]) <= 0.0105, f"tee slope {np.hypot(coef[0], coef[1]):.3f}"
    assert abs(out[m].mean() - dem[m].mean()) < 0.02, "deck at the tee's mean height"
    far = ~rasterize([(tee.buffer(2.5), 1)], out_shape=dem.shape, transform=T).astype(bool)
    assert np.abs(out[far] - dem[far]).max() < 1e-9, "ground beyond the feather is untouched"


def test_existing_flat_tee_deck_is_left_alone():
    from build_terrain_mesh import level_tees
    dem, T, c = _plane(slope=0.005)
    tee = Point(c, c).buffer(5.0)
    out = level_tees(dem.copy(), T, [tee])
    assert np.abs(out - dem).max() < 1e-9


def test_real_deck_with_a_drainage_fall_is_left_alone():
    """Real 2018 decks fall 1.5-3 % for drainage (Westmount: 31 of 69 tees). They must not be re-levelled to 1 %."""
    from build_terrain_mesh import level_tees
    rng = np.random.default_rng(1)
    dem, T, c = _plane(slope=0.028)
    dem = dem + rng.normal(0, 0.02, dem.shape)
    tee = Point(c, c).buffer(6.0)
    out = level_tees(dem.copy(), T, [tee])
    assert np.abs(out - dem).max() < 1e-9


def test_oversized_tee_polygon_is_not_terraced():
    """A tee polygon of hundreds of m2 across a slope is a digitising error (hole 17: 830 m2), not a deck: flattening it
    would cut a terrace into the hillside. It is left for QA."""
    from build_terrain_mesh import level_tees
    dem, T, c = _plane(slope=0.08)
    tee = Point(c, c).buffer(17.0)                          # ~900 m2
    out = level_tees(dem.copy(), T, [tee])
    assert np.abs(out - dem).max() < 1e-9


def test_new_tee_on_a_hillside_gets_banks_not_a_cliff():
    """Hole 11's new back tee sits on a 19 % slope: the synthetic deck (1.1 m of cut / fill at its edges) is feathered
    over enough ground that its steepest bank is about 1:1.5, like a built tee bank. A fixed 1 m feather gave 1.8:1."""
    from build_terrain_mesh import level_tees
    dem, T, c = _plane(slope=0.19)
    tee = Point(c, c).buffer(6.0)
    out = level_tees(dem.copy(), T, [tee])
    gy, gx = np.gradient(out, RES)
    n = dem.shape[0]
    yy, xx = np.mgrid[0:n, 0:n]
    rad = np.hypot((xx + 0.5) * RES - c, (yy + 0.5) * RES - c)
    ring = (rad > 6.2) & (rad < 12)
    bank = np.hypot(gx, gy)[ring].max()
    assert bank < 0.65, f"steepest bank {bank:.2f}"


def test_two_real_decks_with_a_step_are_left_alone():
    """QA round 2 (hole 8): the White / Red pad is the union of two OSM tees, separate 2018 decks 0.3 m apart in height.
    The union fails the single-plane test but is not a deck-less new tee: its cells are locally flat."""
    from build_terrain_mesh import level_tees
    dem, T, c = _plane(slope=0.005)
    n = dem.shape[0]
    xx = (np.arange(n) + 0.5) * RES
    dem = dem + np.where(xx > c, 0.3, 0.0)[None, :]                   # the step between the two decks
    tee = Point(c, c).buffer(9.0)
    out = level_tees(dem.copy(), T, [tee])
    assert np.abs(out - dem).max() < 1e-9


def test_synthetic_deck_does_not_feather_into_a_cart_path():
    """QA round 2 (hole 8): the feather around the new Blue deck cut up to 1 m into the cart path beside it. Protected
    surfaces (paths, roads, buildings, greens, bunkers, water) keep their height; the bank ends at their edge."""
    from build_terrain_mesh import level_tees
    from rasterio.features import rasterize
    from shapely.geometry import box
    dem, T, c = _plane(slope=0.12)
    tee = Point(c, c).buffer(5.0)
    path = box(c + 5.6, 0, c + 8.0, dem.shape[0] * RES)               # a 2.4 m path 0.6 m beside the tee
    protect = rasterize([(path, 1)], out_shape=dem.shape, transform=T).astype(bool)
    out = level_tees(dem.copy(), T, [tee], protect=protect)
    assert np.abs(out - dem)[protect].max() < 1e-9
    inside = rasterize([(tee.buffer(-0.3), 1)], out_shape=dem.shape, transform=T).astype(bool)
    assert np.abs(out - dem)[inside].max() > 0.3, "the tee is still levelled"


def test_new_tee_is_built_up_to_its_neighbouring_deck():
    """Hole 8's 2025 Blue tee sat 1.7 m below the White deck 26 m away, in a hole cut into the slope (its deck was at
    the 2018 slope's mean height). A new tee next to a real deck of the same hole is built up to that deck's level."""
    from build_terrain_mesh import level_tees
    from rasterio.features import rasterize
    dem, T, c = _plane(slope=0.06)                                   # rises 6 % towards +x
    old = Point(c + 12, c).buffer(4.0)
    n = dem.shape[0]; xx = (np.arange(n) + 0.5) * RES
    deck = float(dem[:, int((c + 12) / RES)].mean())
    dem = np.where(rasterize([(old.buffer(1.0), 1)], out_shape=dem.shape, transform=T).astype(bool), deck, dem)  # flat real deck
    new = Point(c - 12, c).buffer(4.0)
    out = level_tees(dem.copy(), T, [old, new], holes=[8, 8])
    m = rasterize([(new.buffer(-0.3), 1)], out_shape=dem.shape, transform=T).astype(bool)
    assert abs(out[m].mean() - deck) < 0.1, f"new deck {out[m].mean():.2f} vs neighbour {deck:.2f}"
    mo = rasterize([(old, 1)], out_shape=dem.shape, transform=T).astype(bool)
    assert np.abs(out[mo] - dem[mo]).max() < 1e-9, "the real deck is untouched"
    # another hole's deck is no reference
    out2 = level_tees(dem.copy(), T, [old, new], holes=[7, 8])
    assert abs(out2[m].mean() - dem[m].mean()) < 0.02


def test_new_tee_is_never_dug_down_to_a_lower_neighbour():
    """Hole 11's new back tee is above its old deck: following the lower neighbour would sink it 2.2 m into the hill.
    Only a deck cut into the slope is built up, and never lowered."""
    from build_terrain_mesh import level_tees
    from rasterio.features import rasterize
    dem, T, c = _plane(slope=0.06)
    old = Point(c - 12, c).buffer(4.0)                              # the lower, real deck
    deck = float(dem[:, int((c - 12) / RES)].mean())
    dem = np.where(rasterize([(old.buffer(1.0), 1)], out_shape=dem.shape, transform=T).astype(bool), deck, dem)
    new = Point(c + 12, c).buffer(4.0)
    out = level_tees(dem.copy(), T, [old, new], holes=[11, 11])
    m = rasterize([(new.buffer(-0.3), 1)], out_shape=dem.shape, transform=T).astype(bool)
    assert abs(out[m].mean() - dem[m].mean()) < 0.02


def test_synthetic_decks_can_be_turned_off():
    """A course whose LiDAR was flown after every tee was built (Brambles, 2023) has no deck-less new tees; its drafted
    tee polygons take in the banks, and a synthetic deck would cut and fill them (up to 0.8 m by the 10th green).
    [tuning.level_tees] enabled = false leaves the DEM as it is."""
    from build_terrain_mesh import level_tees
    dem, T, c = _plane(slope=0.06)
    tee = Point(c, c).buffer(5.0)
    assert np.abs(level_tees(dem.copy(), T, [tee], enabled=False) - dem).max() == 0.0
    assert np.abs(level_tees(dem.copy(), T, [tee]) - dem).max() > 0.1
