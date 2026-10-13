"""Unit tests for the backdrop trees and buildings (backdrop_objects): synthetic canopy and footprints."""
import sys
from pathlib import Path

import numpy as np
from rasterio.transform import from_origin
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import backdrop_objects as B  # noqa: E402


def _dome(n, res, cx, cy, r, h):
    y, x = np.mgrid[:n, :n]
    d = np.hypot((x + 0.5) * res - cx, (n - y - 0.5) * res - cy)
    return np.where(d < r, h * np.sqrt(np.clip(1 - (d / r) ** 2, 0, 1)), 0.0)


def test_tree_peaks_finds_each_crown_once():
    """Past the course the horizon was a flat photo drape: canopy peaks of the backdrop surface model (DSM - DTM)
    place one billboard tree per crown, with its height and a crown radius."""
    res, n = 2.0, 60
    T = from_origin(0, n * res, res, res)
    chm = np.maximum.reduce([_dome(n, res, 30, 30, 6, 18), _dome(n, res, 70, 40, 5, 12), _dome(n, res, 50, 90, 4, 3.0)])
    P = B.tree_peaks(chm.astype(np.float32), T)
    assert len(P) == 2                                                   # the 3 m bump is a shrub / hedge: skipped
    P = P[np.argsort(-P[:, 2])]
    assert np.hypot(P[0, 0] - 30, P[0, 1] - 30) < 2.5 and abs(P[0, 2] - 18) < 1.5
    assert np.hypot(P[1, 0] - 70, P[1, 1] - 40) < 2.5 and abs(P[1, 2] - 12) < 1.5
    assert np.all((P[:, 3] > 2) & (P[:, 3] < 9))


def test_backdrop_building_is_a_closed_hipped_box():
    """Backdrop houses: walls from the ground to the eaves, a hipped roof reaching the LiDAR roof top."""
    P, F = B.building_mesh(box(0, 0, 12, 9), ground=340.0, top=348.0)
    assert P[:, 2].min() <= 340.0 and abs(P[:, 2].max() - 348.0) < 0.05
    roof = P[F].mean(1)[:, 2] > 344.0
    assert roof.any() and (~roof).any()
    e = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), 1)
    assert len(F) < 400                                                 # light: thousands of these on the horizon


def test_building_top_ignores_trees_and_noise():
    top = B.building_top(np.array([347.9, 348.1, 348.0, 362.0, 348.2, 341.0]), ground=340.0)
    assert 347.5 < top < 348.6
    assert B.building_top(np.array([340.2, 340.4]), ground=340.0) == 340.0 + B.DEFAULT_HEIGHT
