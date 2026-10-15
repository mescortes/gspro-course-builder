"""surface_classify: the OSM geometry cache, the OSM training labels and the native colour rule (synthetic OSM and
features, no downloads)."""
import json, os, sys, time
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from shapely.geometry import LineString, box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import surface_classify as S  # noqa: E402
from surface_classify import CID  # noqa: E402

_LL = Transformer.from_crs("EPSG:2958", "EPSG:4326", always_xy=True)


def _way(oid, tags, pts):
    """An Overpass 'out geom' way from UTM (EPSG:2958, the unit tests' course frame) points."""
    return {"type": "way", "id": oid, "tags": tags,
            "geometry": [dict(zip(("lon", "lat"), _LL.transform(x, y))) for x, y in pts]}


def _square(x0, y0, s):
    return [(x0, y0), (x0 + s, y0), (x0 + s, y0 + s), (x0, y0 + s), (x0, y0)]


@pytest.fixture
def two_courses(tmp_path, monkeypatch):
    """An OSM box holding this course (outline 10, holes 1 and 3; hole 3 runs 20 m outside the outline) and its
    neighbour (outline 11, whose hole 2 also has ref 1)."""
    for k in ("RESEARCH", "BUILD", "SOURCES"):
        (tmp_path / k).mkdir(); monkeypatch.setattr(S.C, k, tmp_path / k)
    els = [_way(10, {"leisure": "golf_course"}, _square(537000, 4810500, 200)),
           _way(11, {"leisure": "golf_course"}, _square(537400, 4810500, 200)),
           _way(1, {"golf": "hole", "ref": "1"}, [(537050, 4810550), (537150, 4810650)]),
           _way(2, {"golf": "hole", "ref": "1"}, [(537450, 4810550), (537550, 4810650)]),
           _way(3, {"golf": "hole", "ref": "3"}, [(537220, 4810520), (537220, 4810680)])]
    json.dump({"elements": els}, open(tmp_path / "RESEARCH/osm_all.json", "w"))
    monkeypatch.setattr(S.C, "OSM_EXCLUDE", set()); monkeypatch.setattr(S.C, "OSM_OUTLINE", ())
    monkeypatch.setattr(S, "_OSM_CACHE", {})
    return tmp_path


def _ids(monkeypatch):
    """osm_geoms() ids as a new process sees them: the per-process cache is empty, build/<slug>/osm_geoms.pkl stays."""
    monkeypatch.setattr(S, "_OSM_CACHE", {})
    return sorted(oid for oid, _, _ in S.osm_geoms())


def test_the_osm_cache_follows_the_osm_choices_of_course_toml(two_courses, monkeypatch):
    """check_course reported the neighbour's duplicate hole 1; [osm] exclude or outline was added to course.toml, and
    check_course and the build kept reading the old geometry from osm_geoms.pkl (keyed on the source files only)."""
    assert _ids(monkeypatch) == [1, 2, 3, 10, 11]
    assert (two_courses / "BUILD/osm_geoms.pkl").exists()
    monkeypatch.setattr(S.C, "OSM_EXCLUDE", {("way", 2)})
    assert _ids(monkeypatch) == [1, 3, 10, 11]
    monkeypatch.setattr(S.C, "OSM_EXCLUDE", set()); monkeypatch.setattr(S.C, "OSM_OUTLINE", (("way", 10),))
    assert _ids(monkeypatch) == [1, 3, 10]
    tuning = S.C.tuning
    monkeypatch.setattr(S.C, "tuning", lambda k, d: 10.0 if k == "osm_outline_margin" else tuning(k, d))
    assert _ids(monkeypatch) == [1, 10]                     # hole 3 is 20 m outside: kept by 30 m, not by 10 m


def test_the_osm_cache_follows_the_course_crs(two_courses, monkeypatch):
    """A [frame] crs fix kept the geometry projected into the old frame."""
    x = lambda: next(g for oid, _, g in S.osm_geoms() if oid == 1).coords[0][0]
    assert abs(x() - 537050) < 0.01
    monkeypatch.setattr(S.C, "CRS", "EPSG:2959")            # the next UTM zone east
    monkeypatch.setattr(S, "_OSM_CACHE", {})
    assert abs(x() - 537050) > 1000


def test_the_osm_cache_sees_an_edit_within_the_same_second(two_courses, monkeypatch):
    """golf.geojson saved twice within one second (a script, a quick fix) kept the first version: the cache was keyed
    on whole-second modification times."""
    p = two_courses / "SOURCES/golf.geojson"
    def save(n, ns):
        json.dump({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"golf": "green"}, "geometry": {"type": "Point", "coordinates": [537100.0 + i, 4810600.0]}}
            for i in range(n)]}, open(p, "w"))
        os.utime(p, ns=(ns, ns))
    t = int(time.time()) * 10 ** 9
    save(1, t)
    assert sum(o >= 7_000_000_000 for o in _ids(monkeypatch)) == 1
    save(2, t + 400_000_000)
    assert sum(o >= 7_000_000_000 for o in _ids(monkeypatch)) == 2


_T = rasterio.transform.from_origin(0.0, 100.0, 0.25, 0.25)
_row = lambda y: int((100 - y) / 0.25)
_col = lambda x: int(x / 0.25)


def _labels(G, monkeypatch):
    monkeypatch.setattr(S, "osm_geoms", lambda: G)
    lab, _ = S.osm_label_raster(400, 400, _T, np.zeros((400, 400), np.float32))
    return lab


def test_a_lateral_water_hazard_is_water(monkeypatch):
    """A pond mapped golf=lateral_water_hazard only (no natural=water): check_course counted it as water, the build
    labelled it rough."""
    G = [(1, {"leisure": "golf_course"}, box(0, 0, 100, 100)),
         (2, {"golf": "lateral_water_hazard"}, box(20, 20, 40, 40)),
         (3, {"golf": "water_hazard"}, box(60, 60, 80, 80)),
         (4, {"natural": "water"}, box(60, 10, 80, 30))]
    lab = _labels(G, monkeypatch)
    assert [lab[_row(y), _col(x)] for x, y in ((30, 30), (70, 70), (70, 20))] == [CID["water"]] * 3
    assert S.is_water({"golf": "lateral_water_hazard"}) and not S.is_water({"golf": "bunker"})


def test_primary_trunk_link_roads_and_tracks_are_road_labels(monkeypatch):
    """highway=primary / trunk / *_link / living_street / track were not roads: inside the course they were rough
    training labels. A track's road label is no wider than the track."""
    G = [(1, {"leisure": "golf_course"}, box(0, 0, 100, 100)),
         (2, {"highway": "primary"}, LineString([(10, 15), (90, 15)])),
         (3, {"highway": "trunk_link"}, LineString([(10, 40), (90, 40)])),
         (4, {"highway": "living_street"}, LineString([(10, 60), (90, 60)])),
         (5, {"highway": "track"}, LineString([(10, 85), (90, 85)]))]
    lab = _labels(G, monkeypatch)
    assert [lab[_row(y), _col(50)] for y in (15, 40, 60, 85)] == [CID["road"]] * 4
    assert lab[_row(15 + 2.0), _col(50)] == CID["road"]     # 2.5 m each side of a street centre line
    assert lab[_row(85 + 2.0), _col(50)] != CID["road"]     # 1.5 m each side of a track
    assert S.ROAD_HALF_WIDTH["track"] == 1.5 and S.ROAD_HALF_WIDTH["motorway"] == 7.0


def test_road_widths_take_course_toml_tuning(monkeypatch):
    """[tuning.road_half_width] changes or adds a class; 0 leaves a class out (tracks that are woodland footpaths)."""
    monkeypatch.setattr(S.C, "tuning", lambda k, d: {"track": 0, "busway": 4} if k == "road_half_width" else d)
    w = S.road_half_widths()
    assert "track" not in w and w["busway"] == 4.0 and w["primary"] == S.ROAD_HALF_WIDTH["primary"]


def _native_features(cells):
    """A (30, 30) feature stack with one 10 x 10 block per (A4, B4, L4, chmmax) colour, side by side."""
    names = ["A4", "B4", "L4", "chmmax"]
    X = np.zeros((30, 30, 4), np.float32); X[..., 0] = -10; X[..., 2] = 70   # green turf around
    for i, v in enumerate(cells):
        X[10:20, i * 10:i * 10 + 10] = v
    return X, names


def test_native_seed_colours_are_the_old_rule_by_default_and_tunable(monkeypatch):
    """The reddish-brown mulch / dry native rule was literal constants tuned on one photo."""
    X, names = _native_features([(5, 13, 45, 0.5), (2, 13, 45, 0.5), (5, 13, 45, 2.0)])   # mulch; paler; under a shrub
    lab = np.full((30, 30), CID["rough"], np.uint8)
    out = S.add_native_seeds(lab.copy(), X, names)
    assert (out[12:18, 2:8] == CID["native"]).all() and not (out[:, 10:] == CID["native"]).any()
    monkeypatch.setattr(S.C, "tuning", lambda k, d: {"a_min": 1.5} if k == "native" else d)
    monkeypatch.setattr(S, "NATIVE", S.tuned("native", S.NATIVE))
    out = S.add_native_seeds(lab.copy(), X, names)
    assert (out[12:18, 12:18] == CID["native"]).all() and not (out[:, 20:] == CID["native"]).any()


def test_course_toml_tuning_tables_reach_the_rules(tmp_path):
    """The TOML shapes a newcomer writes ([tuning.sand] tables, a list of classes) arrive through config.tuning."""
    import shutil, subprocess
    (tmp_path / "scripts").mkdir()
    for f in ("config.py", "surface_classify.py", "vectorize.py", "detect_trees.py"):
        shutil.copy(ROOT / "scripts" / f, tmp_path / "scripts" / f)
    (tmp_path / "courses/alpha").mkdir(parents=True)
    (tmp_path / "courses/alpha/course.toml").write_text("""
[course]
name = "Alpha"
[frame]
crs = "EPSG:2958"
origin = [500000.0, 4800000.0]
base_h = 300.0
core = { xmin = 499000.0, ymin = 4799000.0, xmax = 501000.0, ymax = 4801000.0 }
terrain = { xmin = 499000.0, ymin = 4799000.0, xmax = 501000.0, ymax = 4801000.0 }
[tuning]
lidar_vegetation_classes = [0, 1, 3, 4, 5]
road_half_width = { track = 0, primary = 8 }
[tuning.sand]
b_min = 4
[tuning.turf]
a_max = -10.0
""")
    code = ("import sys; sys.path.insert(0, 'scripts'); import vectorize as V, surface_classify as S, detect_trees as D; "
            "print(V.SAND['b_min'], V.SAND['L_min'], V.TURF['a_max'], 'track' in S.ROAD_HALF_WIDTH, "
            "S.ROAD_HALF_WIDTH['primary'], D.VEG_CLASSES)")
    env = {k: v for k, v in os.environ.items() if k not in ("COURSE", "MG_PROFILE")}
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert r.stdout.split() == ["4.0", "66.0", "-10.0", "False", "8.0", "(0,", "1,", "3,", "4,", "5)"], r.stderr
    (tmp_path / "courses/alpha/course.toml").write_text(
        (tmp_path / "courses/alpha/course.toml").read_text().replace("b_min = 4", "bmin = 4"))
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "[tuning.sand] in courses/alpha/course.toml: unknown key bmin" in r.stderr


def test_a_tuned_rule_names_an_unknown_key(monkeypatch):
    monkeypatch.setattr(S.C, "tuning", lambda k, d: {"bmin": 4.0} if k == "sand" else d)
    with pytest.raises(SystemExit, match=r"\[tuning\.sand\].*bmin.*b_min"):
        S.tuned("sand", {"b_min": 8.5})
    monkeypatch.setattr(S.C, "tuning", lambda k, d: 4.0 if k == "sand" else d)
    with pytest.raises(SystemExit, match="table"):
        S.tuned("sand", {"b_min": 8.5})
