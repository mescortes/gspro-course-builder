"""Unit tests for the OSM API fallback (Overpass 'out geom' JSON rebuilt from /api/0.6/map XML). Synthetic data only."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_data  # noqa: E402

XML_A = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
 <node id="1" lat="43.0" lon="-80.0"/>
 <node id="2" lat="43.0" lon="-80.001"/>
 <node id="3" lat="43.001" lon="-80.001"/>
 <node id="4" lat="43.001" lon="-80.0"><tag k="golf" v="pin"/></node>
 <way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="1"/><tag k="golf" v="green"/></way>
 <way id="11"><nd ref="1"/><nd ref="4"/><tag k="highway" v="footway"/></way>
 <way id="12"><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="2"/></way>
 <relation id="20"><member type="way" ref="12" role="outer"/><member type="way" ref="99" role="inner"/>
  <tag k="type" v="multipolygon"/><tag k="natural" v="water"/></relation>
</osm>"""
XML_B = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
 <node id="4" lat="43.001" lon="-80.0"><tag k="golf" v="pin"/></node>
 <node id="5" lat="43.002" lon="-80.0"/>
 <way id="11"><nd ref="1"/><nd ref="4"/><tag k="highway" v="footway"/></way>
 <way id="13"><nd ref="4"/><nd ref="5"/><tag k="golf" v="hole"/><tag k="ref" v="1"/></way>
</osm>"""


def test_osm_xml_to_overpass_geom_json():
    els = fetch_data.osm_xml_to_elements([XML_A, XML_B])
    by = {(e["type"], e["id"]): e for e in els}
    # merged across tiles without duplicates
    assert sum(1 for e in els if (e["type"], e["id"]) == ("way", 11)) == 1
    green = by[("way", 10)]
    assert green["tags"] == {"golf": "green"}
    assert green["nodes"] == [1, 2, 3, 1]
    assert green["geometry"][1] == {"lat": 43.0, "lon": -80.001}
    hole = by[("way", 13)]
    assert hole["geometry"] == [{"lat": 43.001, "lon": -80.0}, {"lat": 43.002, "lon": -80.0}]
    pin = by[("node", 4)]
    assert pin["lat"] == 43.001 and pin["tags"]["golf"] == "pin"
    rel = by[("relation", 20)]
    outer = [m for m in rel["members"] if m["role"] == "outer"][0]
    assert len(outer["geometry"]) == 4          # member way geometry filled in, like Overpass 'out geom'
    inner = [m for m in rel["members"] if m["role"] == "inner"][0]
    assert "geometry" not in inner              # member outside every fetched tile: no geometry (skipped downstream)
    # untagged ways are still emitted (relation members), untagged nodes are not
    assert ("way", 12) in by and ("node", 1) not in by


def test_golf_filter_keeps_golf_and_course_only():
    els = fetch_data.osm_xml_to_elements([XML_A, XML_B])
    golf = fetch_data.golf_only(els)
    assert {(e["type"], e["id"]) for e in golf} == {("way", 10), ("node", 4), ("way", 13)}


def test_split_bbox_tiles_cover_the_box():
    tiles = fetch_data.split_bbox((-80.6, 43.4, -80.5, 43.5), 0.03)
    assert len(tiles) == 16
    assert min(t[0] for t in tiles) == -80.6 and max(t[2] for t in tiles) == -80.5
    assert min(t[1] for t in tiles) == 43.4 and max(t[3] for t in tiles) == 43.5


def _fake_root(tmp_path, monkeypatch, calls):
    monkeypatch.setattr(fetch_data.C, "RESEARCH", tmp_path / "research")
    def fake_overpass(query, path):
        calls.append(path); Path(path).write_text('{"elements": []}'); return True
    monkeypatch.setattr(fetch_data, "overpass", fake_overpass)
    (tmp_path / "research").mkdir()


def test_fetch_osm_keeps_the_committed_snapshot(tmp_path, monkeypatch):
    """The model is built from the OSM snapshot in courses/<slug>/research/: `fetch_data.py osm` must not overwrite it (README:
    delete the files to refresh)."""
    calls = []
    _fake_root(tmp_path, monkeypatch, calls)
    for n in ("osm_all.json", "osm_golf.json"):
        (tmp_path / "research" / n).write_text('{"elements": [{"type": "node", "id": 1}]}')
    fetch_data.fetch_osm()
    assert calls == []
    assert (tmp_path / "research/osm_all.json").read_text() == '{"elements": [{"type": "node", "id": 1}]}'


def test_fetch_osm_downloads_when_the_snapshot_is_missing(tmp_path, monkeypatch):
    calls = []
    _fake_root(tmp_path, monkeypatch, calls)
    (tmp_path / "research/osm_golf.json").write_text('{"elements": []}')  # half a snapshot: refetch both
    fetch_data.fetch_osm()
    assert [Path(p).name for p in calls] == ["osm_all.json", "osm_golf.json"]


def test_downloads_use_the_course_extent_in_the_test_profile(tmp_path, monkeypatch):
    """The two profiles share data/<slug>/ and the OSM snapshot: fetching in the test profile (a small CORE) must
    still cover the whole course, or the course build silently reuses a test-extent photo and snapshot."""
    import sources
    from sources import arcgis_imageserver, nrcan_copc
    full = dict(fetch_data.C.FETCH_CORE)
    monkeypatch.setattr(fetch_data.C, "CORE", dict(xmin=full["xmin"] + 300, ymin=full["ymin"] + 300,
                                                    xmax=full["xmin"] + 600, ymax=full["ymin"] + 600))
    monkeypatch.setattr(fetch_data.C, "IMAGERY_RAW", tmp_path / "photo.tif")
    got = {}
    monkeypatch.setattr(arcgis_imageserver, "fetch", lambda spec, *a, **k: got.update(bbox=a[:4]))
    fetch_data.fetch_imagery()
    assert got["bbox"] == (full["xmin"] - 20, full["ymin"] - 20, full["xmax"] + 20, full["ymax"] + 20)
    monkeypatch.setattr(nrcan_copc, "fetch", lambda spec, ext, out, **k: got.update(lidar=dict(ext)) or 0)
    fetch_data.fetch_lidar()
    assert got["lidar"] == full
    calls = []
    _fake_root(tmp_path, monkeypatch, calls)
    queries = []
    monkeypatch.setattr(fetch_data, "overpass", lambda q, path: queries.append(q) or Path(path).write_text("{}") or True)
    fetch_data.fetch_osm()
    w, s, e, n = fetch_data.lonlat_bbox(full, 400)
    assert f"{s},{w},{n},{e}" in queries[0]
