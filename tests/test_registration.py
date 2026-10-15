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


def test_the_new_shift_adds_the_measurement_to_the_shift_the_measured_photo_carries(tmp_path, monkeypatch, capsys):
    """The offset is measured on the registered photo on disk, but the printed line added it to course.toml's
    [imagery] shift: with the line pasted and the photo measured again before build_all.py register, the offset was
    counted twice. The shift the photo carries is read from the two photos' origins (as register_imagery.py writes it)."""
    raw, reg = tmp_path / "raw.tif", tmp_path / "reg.tif"
    _tif(raw, np.zeros((8, 8)), 0.16)
    _tif(reg, np.zeros((8, 8)), 0.16, x0=537000.0 + 0.5, y1=4810064.0 - 0.25)
    assert M.applied_shift(raw, reg, (9.0, 9.0)) == (0.5, -0.25)
    assert M.applied_shift(raw, tmp_path / "none.tif", (0.0, -0.25)) == (0.0, -0.25)      # not registered yet
    core = dict(xmin=0.0, ymin=0.0, xmax=100.0, ymax=100.0)
    A = np.array([[10.0, 10.0, 0.25, 0.0, 1.3], [80.0, 20.0, 0.25, 0.0, 1.2], [20.0, 80.0, 0.25, 0.0, 1.4]])
    lines, shift = M.bunker_shift(A, core, M.applied_shift(raw, reg, (0.75, -0.25)))
    assert shift == (0.75, -0.25) and any("registered photo" in l for l in lines)
    # course.toml already holds the pasted [0.75, -0.25], the photo still carries [0.50, -0.25]: main says so
    monkeypatch.setattr(M.C, "CORE", dict(xmin=537000.0, ymin=4810000.0, xmax=537064.0, ymax=4810064.0))
    for k in ("BUILD", "FEATURES"):
        monkeypatch.setattr(M.C, k, tmp_path)
    monkeypatch.setattr(M.C, "IMAGERY_RAW", raw); monkeypatch.setattr(M.C, "IMAGERY", reg)
    monkeypatch.setattr(M.C, "IMAGERY_SHIFT", (0.75, -0.25))
    _tif(tmp_path / "dem_final.tif", np.full((256, 256), 300.0), 0.25)
    _tif(tmp_path / "dsm.tif", np.full((128, 128), 300.0), 0.5)
    json.dump({"type": "FeatureCollection", "features": []}, open(tmp_path / "auto_core.geojson", "w"))
    monkeypatch.setattr(M, "osm_geoms", lambda: [])
    M.main()
    out = capsys.readouterr().out
    assert "[0.50, -0.25]" in out and "[0.75, -0.25]" in out and "build_all.py register" in out
