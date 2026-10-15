"""Course features beyond OSM (plan PR 5): hand-digitised golf features, OSM exclusions, clipping to the course outline."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import surface_classify as S  # noqa: E402


def _way(i, tags, lonlat):
    return {"type": "way", "id": i, "tags": tags, "geometry": [{"lon": x, "lat": y} for x, y in lonlat]}


def _square(lon, lat, d):
    return [(lon, lat), (lon + d, lat), (lon + d, lat + d), (lon, lat + d), (lon, lat)]


def _setup(tmp_path, monkeypatch, osm=None, golf=None):
    for k in ("RESEARCH", "BUILD", "SOURCES"):
        (tmp_path / k).mkdir()
        monkeypatch.setattr(S.C, k, tmp_path / k)
    monkeypatch.setattr(S.C, "OSM_EXCLUDE", set())
    monkeypatch.setattr(S.C, "OSM_OUTLINE", ())
    monkeypatch.setattr(S, "_OSM_CACHE", {})
    els = [
        _way(1, {"leisure": "golf_course", "name": "Ours"}, _square(-80.400, 43.360, 0.010)),
        _way(2, {"golf": "hole", "ref": "1", "par": "4"}, [(-80.398, 43.362), (-80.393, 43.366)]),
        _way(3, {"leisure": "golf_course", "name": "Neighbour"}, _square(-80.400, 43.350, 0.006)),
        _way(4, {"golf": "hole", "ref": "1", "par": "5"}, [(-80.398, 43.352), (-80.396, 43.355)]),
        _way(5, {"aeroway": "runway"}, [(-80.399, 43.361), (-80.391, 43.369)]),
        _way(6, {"building": "yes"}, _square(-80.397, 43.353, 0.0003)),
    ]
    json.dump({"elements": osm or els}, open(tmp_path / "RESEARCH/osm_all.json", "w"))
    if golf is not None:
        json.dump({"type": "FeatureCollection", "features": golf}, open(tmp_path / "SOURCES/golf.geojson", "w"))
    return S.osm_geoms


def test_without_course_settings_the_osm_stream_is_unchanged(tmp_path, monkeypatch):
    G = _setup(tmp_path, monkeypatch)()
    assert sorted(oid for oid, _, _ in G) == [1, 2, 3, 4, 5, 6]


def test_excluded_osm_elements_are_dropped(tmp_path, monkeypatch):
    """Brambles: the old gliderport runway and track cross holes 2, 17 and 18."""
    osm_geoms = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(S.C, "OSM_EXCLUDE", {("way", 5)})
    assert 5 not in [oid for oid, _, _ in osm_geoms()]


def test_golf_features_outside_the_course_outline_are_dropped(tmp_path, monkeypatch):
    """Whistle Bear: Grand Valley's own holes 1-18 start 500 m south; hole refs are keyed with no spatial filter, so
    its hole 1 would replace ours. Other courses' outlines go too; buildings and roads stay."""
    osm_geoms = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(S.C, "OSM_OUTLINE", (("way", 1),))
    ids = [oid for oid, _, _ in osm_geoms()]
    assert 2 in ids and 1 in ids and 4 not in ids and 3 not in ids and 6 in ids


def test_hand_digitised_golf_features_join_the_osm_stream(tmp_path, monkeypatch):
    """Brambles is not in OSM: its holes, greens and tees are drawn in courses/<slug>/features/golf.geojson with OSM
    tags (UTM geometry), and every step reads them as if OSM had them."""
    golf = [{"type": "Feature", "properties": {"golf": "hole", "ref": "7", "par": "5"},
             "geometry": {"type": "LineString", "coordinates": [[536600.0, 4291300.0], [536900.0, 4291500.0]]}},
            {"type": "Feature", "properties": {"golf": "green"},
             "geometry": {"type": "Polygon", "coordinates": [[[536890.0, 4291490.0], [536910.0, 4291490.0],
                                                              [536910.0, 4291510.0], [536890.0, 4291510.0], [536890.0, 4291490.0]]]}}]
    G = _setup(tmp_path, monkeypatch, golf=golf)()
    mine = [(oid, t, g) for oid, t, g in G if t.get("source") == "course"]
    assert [t["golf"] for _, t, _ in mine] == ["hole", "green"]
    assert mine[0][1]["ref"] == "7" and mine[0][2].length > 300 and abs(mine[1][2].area - 400.0) < 1e-6
    assert len({oid for oid, _, _ in G}) == len(G)                      # ids stay unique
    import hole_data  # noqa: F401  (hole lines are read from osm_geoms by ref)


def test_config_reads_the_osm_table(tmp_path):
    import os, shutil, subprocess
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/config.py", tmp_path / "scripts/config.py")
    (tmp_path / "courses/alpha").mkdir(parents=True)
    (tmp_path / "courses/alpha/course.toml").write_text("""
[course]
name = "Alpha"
[frame]
crs = "EPSG:2958"
origin = [500000.0, 4800000.0]
base_h = 300.0
core = { xmin = 499000.0, ymin = 4799000.0, xmax = 501000.0, ymax = 4801000.0 }
terrain = { xmin = 498976.0, ymin = 4798976.0, xmax = 501024.0, ymax = 4801024.0 }
[osm]
outline = ["way/152133739", "way/382278772"]
exclude = ["way/371961043", "node/7"]
""")
    env = {k: v for k, v in os.environ.items() if k not in ("COURSE", "MG_PROFILE")}
    r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); import config as C; "
                        "print(C.OSM_OUTLINE, sorted(C.OSM_EXCLUDE))"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert r.stdout.strip() == "(('way', 152133739), ('way', 382278772)) [('node', 7), ('way', 371961043)]", r.stderr
