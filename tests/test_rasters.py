"""Unit tests for build_rasters helpers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_building_returns_are_class_6_any_return():
    """bdsm.tif (roofs without overhanging crowns) keeps every class 6 return; dsm.tif keeps non-noise first returns."""
    import numpy as np
    import build_rasters as R
    cls = np.array([1, 2, 6, 6, 7, 18, 5])
    rn = np.array([1, 1, 1, 2, 1, 1, 1])
    first, bld = R.surface_returns(cls, rn)
    assert first.tolist() == [True, True, True, False, False, False, True]
    assert bld.tolist() == [False, False, True, True, False, False, False]
