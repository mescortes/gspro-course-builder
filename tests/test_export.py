"""Unit tests for glTF export colour helpers (synthetic data)."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import export_course as E  # noqa: E402


def test_season_grade_moves_the_median_and_keeps_variation():
    rng = np.random.default_rng(0)
    tint = rng.uniform(0.04, 0.2, (40, 40, 3)).astype(np.float32)        # pale, low-chroma spring turf (linear)
    stats = np.percentile(tint.reshape(-1, 3), [50, 95], axis=0)
    out, st = E.season_grade(tint, stats, (86, 128, 54))
    med = E.lin_to_srgb(np.median(out.reshape(-1, 3), 0)) * 255
    assert np.abs(med - (86, 128, 54)).max() < 1.0
    ratio = out / tint
    assert ratio.reshape(-1, 3).std(0).max() < 1e-4                     # one gain per channel: relative detail kept
    assert np.allclose(st[0], np.median(out.reshape(-1, 3), 0), rtol=1e-4)


def test_turf_patches_vary_slowly_and_gently():
    """Course turf read as one flat colour (brightness std ~4 % across a fairway): moisture and wear patches add a
    slow brightness / hue variation, a few percent, coherent over metres (not per-vertex noise), mean neutral."""
    import export_course as X
    x = np.arange(0, 400, 1.0)
    P = np.c_[537000 + x, np.full_like(x, 4810800.0), np.zeros_like(x)]
    f = X.turf_patches(P)
    assert f.shape == (len(x), 3)
    lum = f.mean(1)
    assert abs(lum.mean() - 1) < 0.02 and 0.03 < lum.std() < 0.09
    assert np.corrcoef(lum[:-1], lum[1:])[0, 1] > 0.95                 # 1 m apart: nearly the same
    assert abs(np.corrcoef(lum[:-60], lum[60:])[0, 1]) < 0.6           # 60 m apart: different patches
    assert np.all((f[:, 2] - f[:, 1]) * np.sign(lum - 1) <= 1e-9)      # brighter patches are yellower (less blue)
