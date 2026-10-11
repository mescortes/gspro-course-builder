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
