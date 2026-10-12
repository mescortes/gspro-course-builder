"""Unit tests for the backdrop photo grading (build_backdrop.summer_grade). Synthetic pixels only."""
import sys
from pathlib import Path

import numpy as np
from skimage.color import rgb2lab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_backdrop as B  # noqa: E402


def _scene(rng):
    """Left half: a grey-brown dormant lawn / leaf-off wood (NDVI 0.25-0.4). Right half: road and roofs (NDVI ~0)."""
    a = np.zeros((40, 80, 3), np.uint8); ndvi = np.zeros((40, 80), np.float32)
    a[:, :40] = np.clip(np.array([128, 116, 92]) + rng.normal(0, 9, (40, 40, 3)), 0, 255).astype(np.uint8)
    ndvi[:, :40] = rng.uniform(0.25, 0.4, (40, 40))
    a[:, 40:] = np.clip(np.array([118, 116, 112]) + rng.normal(0, 6, (40, 40, 3)), 0, 255).astype(np.uint8)
    ndvi[:, 40:] = rng.uniform(-0.05, 0.03, (40, 40))
    return a, ndvi


def test_summer_grade_greens_vegetation_and_keeps_its_texture():
    """The spring photo drapes the backdrop in grey-brown dormant lawns and bare trees (a pale 'desert' horizon in the
    viewer and the GSPro outer plot). Vegetated pixels (by NDVI) move to a summer green; their texture stays."""
    a, ndvi = _scene(np.random.default_rng(0))
    out = B.summer_grade(a, ndvi)
    lab0, lab1 = rgb2lab(a[:, :40] / 255.0), rgb2lab(out[:, :40] / 255.0)
    assert np.median(lab0[..., 1]) > 0 and np.median(lab1[..., 1]) < -12          # brown -> green
    assert np.median(lab1[..., 2]) > 10                                              # yellow-green, not cyan
    ratio = lab1[..., 0].std() / lab0[..., 0].std()
    assert 0.7 < ratio < 1.3                                                         # brightness texture kept


def test_summer_grade_leaves_pavement_and_roofs_alone():
    a, ndvi = _scene(np.random.default_rng(1))
    out = B.summer_grade(a, ndvi)
    assert np.abs(out[:, 40:].astype(int) - a[:, 40:].astype(int)).max() <= 1
