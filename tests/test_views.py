"""make_views.py: the viewer camera presets come from the first hole that has tees, a green and pins (synthetic
holes.json and DEM)."""
import json, sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config as C  # noqa: E402


def _hole(n, e0):
    """A playable 300 m hole running north from (e0, 4810100) on the synthetic DEM."""
    tee, green = [e0, 4810100.0], [e0, 4810400.0]
    return {"hole": n, "tees": [{"utm": tee + [300.0]}], "centerline_utm": [tee, [e0, 4810250.0], green],
            "green": {"centre_utm": green + [300.0]}, "hazards": [],
            "pins": [{"name": "middle", "utm": [e0, 4810402.0, 300.0]}]}


def _make_views(tmp_path, monkeypatch, holes):
    for k in ("BUILD", "OUTPUT"):
        (tmp_path / k).mkdir(); monkeypatch.setattr(C, k, tmp_path / k)
    with rasterio.open(tmp_path / "BUILD/dem_final.tif", "w", driver="GTiff", width=200, height=200, count=1,
                       dtype="float32", crs="EPSG:2958", transform=from_origin(536500.0, 4810600.0, 5.0, 5.0)) as d:
        d.write(np.full((1, 200, 200), 345.0, np.float32))
    json.dump({"holes": holes}, open(tmp_path / "OUTPUT/holes.json", "w"))
    monkeypatch.delitem(sys.modules, "make_views", raising=False)   # it reads the DEM when imported
    import make_views as M
    monkeypatch.setattr(M, "osm_geoms", lambda: [])
    M.main()
    p = tmp_path / "OUTPUT/views.json"
    return json.load(open(p)) if p.exists() else None


def test_views_come_from_the_first_hole_with_tees_a_green_and_pins(tmp_path, monkeypatch):
    """Hole 1 without a line of play, a green or a tee pad (an error record or no tees in holes.json) crashed the views
    step, the last of build_all, after the whole build."""
    holes = [{"hole": 1, "error": "no OSM line of play"}, dict(_hole(2, 537000.0), tees=[]),
             {"hole": 3, "error": "no green polygon assigned"}, _hole(4, 537200.0), _hole(5, 537400.0)]
    v = _make_views(tmp_path, monkeypatch, holes)
    assert v["tee"]["pos"][0] == round(537200.0 - C.ORIGIN_E, 2) and v["tee"]["pos"][1] == round(345.0 - C.BASE_H + 1.75, 2)


def test_no_usable_hole_skips_the_views(tmp_path, monkeypatch, capsys):
    v = _make_views(tmp_path, monkeypatch, [{"hole": 1, "error": "no OSM line of play"}, dict(_hole(2, 537000.0), pins=[])])
    assert v is None and "no hole" in capsys.readouterr().out
