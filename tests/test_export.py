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
