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


def test_no_lidar_is_an_error_not_an_empty_dem(tmp_path, monkeypatch):
    """With no tiles (an old checkout whose downloads are still in data/, not data/<slug>/), the rasters were built
    from zero points: all-NaN DEM, DSM and CHM, and no error."""
    import laspy, numpy as np, pytest
    import build_rasters as R
    ext = dict(xmin=537000.0, ymin=4810000.0, xmax=537256.0, ymax=4810256.0)
    monkeypatch.setattr(R.C, "LIDAR_TILES", [])
    with pytest.raises(SystemExit, match="lidar"):
        R.pass1(ext, 1.0)
    las = laspy.LasData(laspy.LasHeader(point_format=1, version="1.2"))   # a tile 5 km away
    las.x = np.array([532000.0, 532001.0]); las.y = np.array([4805000.0, 4805001.0]); las.z = np.array([300.0, 301.0])
    las.write(tmp_path / "far.las")
    monkeypatch.setattr(R.C, "LIDAR_TILES", [tmp_path / "far.las"])
    with pytest.raises(SystemExit, match="no LiDAR tile covers"):
        R.pass1(ext, 1.0)
