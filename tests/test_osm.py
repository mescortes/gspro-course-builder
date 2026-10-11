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
