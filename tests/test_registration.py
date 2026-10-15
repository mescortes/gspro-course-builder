"""measure_registration.py on a synthetic build (no photo needed when no bunker qualifies)."""
import json, sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import measure_registration as M  # noqa: E402


def _tif(path, a, res, x0=537000.0, y1=4810064.0):
    with rasterio.open(path, "w", driver="GTiff", width=a.shape[1], height=a.shape[0], count=1, dtype="float32",
                       crs="EPSG:2958", transform=from_origin(x0, y1, res, res)) as d:
        d.write(a.astype(np.float32), 1)


def test_no_sand_blob_is_a_message_not_a_crash(tmp_path, monkeypatch, capsys):
    """A course whose bunker sand fails the colour rule (white silica sand) gave no sand blob, and the statistics
    crashed with 'too many indices for array'. The message points at [tuning.sand]; the building check still runs."""
    monkeypatch.setattr(M.C, "CORE", dict(xmin=537000.0, ymin=4810000.0, xmax=537064.0, ymax=4810064.0))
    for k in ("BUILD", "FEATURES"):
        monkeypatch.setattr(M.C, k, tmp_path)
    dem = np.full((256, 256), 300.0)
    _tif(tmp_path / "dem_final.tif", dem, 0.25)
    dsm = np.full((128, 128), 300.0); dsm[40:60, 40:60] = 306.0             # a 10 m house
    _tif(tmp_path / "dsm.tif", dsm, 0.5)
    json.dump({"type": "FeatureCollection", "features": []}, open(tmp_path / "auto_core.geojson", "w"))
    monkeypatch.setattr(M, "osm_geoms", lambda: [(1, {"building": "house"}, box(537020.0, 4810034.0, 537030.0, 4810044.0))])
    M.main()
    out = capsys.readouterr().out
    assert "bunkers used: 0" in out and "[tuning.sand]" in out and "OSM buildings -> lidar shift: dx +0.00 m  dy +0.00 m" in out
