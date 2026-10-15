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


