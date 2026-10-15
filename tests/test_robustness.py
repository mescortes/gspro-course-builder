"""Failures found by the PR 3 / PR 4 review: each was silent before (synthetic data, no network)."""
import json, sys, tomllib
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config as C  # noqa: E402

REGIONS = sorted((ROOT / "regions").glob("*.toml"))


@pytest.mark.parametrize("path", REGIONS, ids=[p.stem for p in REGIONS])
def test_every_region_has_what_the_scripts_read(path):
    """A missing table or key failed as a bare KeyError deep in a build (the classifier only after every LiDAR tile)."""
    import detect_trees
    r = tomllib.load(open(path, "rb"))
    tr = r["trees"]
    for k in ("archetypes", "bark", "backdrop", "shapes", "classifier"):
        assert k in tr, k
    assert tr["classifier"] in detect_trees.CLASSIFIERS and tr["classifier"] in tr
    arch = set(tr["archetypes"])
    assert arch <= set(tr["shapes"]) and arch <= set(r["foliage"]) and arch <= set(tr["bark"])
    assert set(tr[tr["classifier"]]["names"].values()) <= arch
    assert set(tr["backdrop"]["kinds"]) <= arch and len(tr["backdrop"]["kinds"]) == len(tr["backdrop"]["share"])
    for a in arch:
        assert r["foliage"][a]["src"] or tr.get("needles", {}).get(a) in ("pine", "spruce"), f"{a}: no sprite and no needle style"
    for k in ("wall_palette", "roof_palette", "parking_stall", "suv_share"):
        assert k in r["buildings"], k
    for k in ("summer_grade", "summer_green", "ndvi"):
        assert k in r["backdrop"], k
    assert {"deeprough", "native"} <= set(r["materials"]) and "3dg" in r["grass"] and "viewer" in r["grass"]


def test_needle_cards_follow_the_regions_needle_style(monkeypatch):
    """Needle cards were drawn only for archetypes literally named pine and spruce: a gray_pine got bare twigs."""
    import make_foliage as M
    assert M.NEEDLES == {"pine": "pine", "spruce": "spruce"}
    assert M.card_kind("pine", M.SPEC["pine"]) == "pine" and M.card_kind("maple", M.SPEC["maple"]) == "sprites"
    monkeypatch.setattr(M, "NEEDLES", {"gray_pine": "pine"})
    assert M.card_kind("gray_pine", dict(M.SPEC["pine"])) == "pine"
    with pytest.raises(SystemExit, match="cedar"):
        M.card_kind("cedar", dict(M.SPEC["pine"]))


def test_traced_paths_are_ignored_when_path_tracing_is_off(tmp_path, monkeypatch):
    import surface_classify as S
    for k in ("RESEARCH", "BUILD", "SOURCES"):
        (tmp_path / k).mkdir(); monkeypatch.setattr(S.C, k, tmp_path / k)
    json.dump({"elements": []}, open(tmp_path / "RESEARCH/osm_all.json", "w"))
    json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"golf": "cartpath"},
              "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}]}, open(tmp_path / "BUILD/paths_detected.geojson", "w"))
    monkeypatch.setattr(S, "_OSM_CACHE", {})
    assert len(S.osm_geoms()) == 1
    monkeypatch.setattr(S.C, "tuning", lambda k, d: False if k == "trace_paths" else d)
    monkeypatch.setattr(S, "_OSM_CACHE", {})
    assert S.osm_geoms() == []


def test_greenkeeper_tee_slots_are_valid_or_left_empty(monkeypatch):
    import check_course as K, export_gspro as X
    class Card:
        PLAYABLE = (1,); TEES = (("black", "Black", "#000"), ("gold", "Gold", "#d4a017"), ("blue", "Blue", "#00f"))
        TEE_KEYS = ("black", "gold", "blue"); TEE_GKD = {"black": "Black", "gold": "Gold", "blue": "Black"}
        SCORECARD = {1: (4, 1, 2, 3)}; HANDICAP = {1: 1}; HANDICAP_WOMEN = {1: 1}
        RATINGS = {"black": (1, 2, 3, 4, 5), "gold": (1, 2, 3, 4, 5), "blue": (1, 2, 3, 4, 5)}
        REGION_NAME = "x"; DATA_SOURCES = {"lidar": 1, "imagery": 1, "backdrop": 1}; OSM_OUTLINE = ()
    p = "\n".join(K.course_report(Card))
    assert "gold" in p and "'Gold'" in p and "Black" in p and "two tees" in p
    monkeypatch.setattr(X, "GKD_TEE_SLOT", {"black": "Black"})
    assert X.tee_type({"key": "black", "name": "Black"}) == "Black" and X.tee_type({"key": "gold", "name": "Gold"}) is None


def test_a_lidar_tile_is_missing_only_on_a_404(monkeypatch):
    """Any non-200 HEAD (a proxy 403, an S3 503) read as 'not in this folder' and the tile was dropped silently."""
    from sources import http
    seq = []
    class R:
        def __init__(self, code): self.status_code, self.headers = code, {"Content-Length": "7"}
    def head(url, **kw):
        return R(seq.pop(0))
    monkeypatch.setattr(http.requests, "head", head); monkeypatch.setattr(http.time, "sleep", lambda s: None)
    seq[:] = [404]; assert http.size("u") is None
    seq[:] = [503, 200]; assert http.size("u") == 7
    seq[:] = [403] * 5
    with pytest.raises(RuntimeError, match="403"):
        http.size("u")


def test_tiles_no_folder_has_stop_the_fetch(tmp_path, monkeypatch):
    from sources import nrcan_copc
    monkeypatch.setattr(nrcan_copc.http, "size", lambda u: None)
    spec = {"zone": 17, "projects": [{"folder": "ON/A", "suffix": "X"}]}
    ext = dict(xmin=546100.0, ymin=4805100.0, xmax=546900.0, ymax=4805900.0)
    with pytest.raises(SystemExit, match="5460 48050"):
        nrcan_copc.fetch(spec, ext, tmp_path)
    assert nrcan_copc.fetch(dict(spec, missing_ok=[[5460, 48050]]), ext, tmp_path) == 0


def test_3dep_boxes_are_shrunk_by_their_real_excess_only(monkeypatch, tmp_path):
    """The lon/lat boxes are ~5 m too big per side at Brambles (grid convergence): a 20 m shrink dropped the tile that
    only the 15 m read margin reaches."""
    from sources import usgs_3dep
    from pyproj import Transformer
    to_ll = Transformer.from_crs("EPSG:6339", "EPSG:4326", always_xy=True)
    ll = [to_ll.transform(x, y) for x in (538500.0, 539500.0) for y in (4291000.0, 4292000.0)]
    box = dict(minX=min(p[0] for p in ll), maxX=max(p[0] for p in ll), minY=min(p[1] for p in ll), maxY=max(p[1] for p in ll))
    page = {"total": 1, "items": [{"title": "B23 538291", "downloadURL": "https://x/USGS_LPC_B23_538291.laz", "boundingBox": box}]}
    class R:
        status_code = 200
        def json(self): return page
    monkeypatch.setattr(usgs_3dep.http.requests, "get", lambda *a, **k: R())
    ext = dict(xmin=537000.0, ymin=4291200.0, xmax=538495.0, ymax=4291800.0)   # 5 m short of the tile, inside the margin
    assert [u for _, u in usgs_3dep.items({"project": "B23"}, ext, "EPSG:6339")] == ["https://x/USGS_LPC_B23_538291.laz"]


def test_an_empty_photo_is_an_error(monkeypatch, tmp_path):
    """A NAIP pin that matches nothing returned all-zero chunks, and the fetch wrote a black photo."""
    from sources import arcgis_imageserver as A
    import rasterio
    from rasterio.transform import from_origin
    class R:
        status_code = 200; headers = {"content-type": "image/tiff"}
        def __init__(self, n=None): self._n = n
        def json(self): return {"count": self._n}
        @property
        def content(self):
            import io
            mem = io.BytesIO()
            with rasterio.MemoryFile() as mf:
                with mf.open(driver="GTiff", width=10, height=10, count=1, dtype="uint8", transform=from_origin(0, 10, 1, 1)) as d:
                    d.write(np.zeros((1, 10, 10), np.uint8))
                return mf.read()
    spec = {"url": "https://s", "mosaic_rule": {"mosaicMethod": "esriMosaicNorthwest", "where": "Name LIKE 'm%2022____'"}}
    monkeypatch.setattr(A.requests, "get", lambda url, params=None, **k: R(0) if url.endswith("/query") else R())
    with pytest.raises(SystemExit, match="2022"):
        A.fetch(spec, 0.0, 0.0, 10.0, 10.0, 1.0, tmp_path / "x.tif", bands=(0,))
    monkeypatch.setattr(A.requests, "get", lambda url, params=None, **k: R(3) if url.endswith("/query") else R())
    with pytest.raises(SystemExit, match="empty"):
        A.fetch(spec, 0.0, 0.0, 10.0, 10.0, 1.0, tmp_path / "x.tif", bands=(0,))


def test_a_backdrop_dem_can_name_its_real_datum(tmp_path):
    """3DEP 1 m DEMs are stamped NAD83 (EPSG:26910) but come from NAD83(2011) lidar: src_crs says so, so the warp to
    EPSG:6339 never applies a datum shift (0.7 m with PROJ grids installed)."""
    from sources import cog_dem
    import rasterio
    from rasterio.transform import from_origin
    src = tmp_path / "dem.tif"
    with rasterio.open(src, "w", driver="GTiff", width=40, height=40, count=1, dtype="float32", crs="EPSG:26910",
                       transform=from_origin(537000.0, 4292000.0, 1.0, 1.0)) as d:
        d.write(np.arange(1600, dtype=np.float32).reshape(1, 40, 40))
    ext = dict(xmin=537010.0, ymin=4291970.0, xmax=537030.0, ymax=4291990.0)
    assert cog_dem.open_path(str(src)) == str(src) and cog_dem.open_path("https://x/a.tif") == "/vsicurl/https://x/a.tif"
    assert cog_dem.fetch({"dtm": [str(src)], "src_crs": "EPSG:6339"}, "dtm", ext, 2.0, tmp_path / "out.tif", crs="EPSG:6339")
    with rasterio.open(tmp_path / "out.tif") as d:
        a = d.read(1)
    assert np.isfinite(a).all() and abs(float(a[0, 0]) - (10 * 40 + 10 + 0.5 + 0.5 * 40)) < 1e-3


def test_gkd_ratings_take_women_only_and_unrated_tees():
    """Brambles' Front tee is rated for women only (no men's rating): the GreenKeeper export crashed formatting the
    missing men's value. Each slot gets the strings it has; an unrated tee gets none."""
    import export_gspro as X
    ratings = {"back": (73.1, 141, None, None, 7190), "front": (None, None, 71.5, 127, 5318),
               "middle": (None, None, None, None, 6579)}
    slots = {"back": "Black", "middle": "White", "front": "Red"}
    assert X.gkd_ratings(ratings, slots) == {"BlackSR": "73.1/141", "RedSR_women": "71.5/127"}
def test_tee_labels_tell_black_from_blue():
    """Whistle Bear has Black and Blue tees: the hole summary and the QA images labelled both "B". Labels are the
    shortest prefixes that tell the tees apart."""
    assert C.tee_labels(("black", "gold", "blue", "white", "red")) == {
        "black": "Bla", "gold": "G", "blue": "Blu", "white": "W", "red": "R"}
    assert C.tee_labels(("blue", "white", "red", "gold")) == {"blue": "B", "white": "W", "red": "R", "gold": "G"}


def test_the_out_of_bounds_ring_stays_on_the_terrain():
    """GreenKeeper's pOOB ring is the course outline on the ground. An outline wider than the GSPro terrain (the test
    profile's small square, or a course wider than 2 km) put ring points off the terrain. It is clipped to the
    terrain square; an outline inside it is used as it is."""
    import export_gspro as X
    from shapely.geometry import box, Polygon
    te = dict(xmin=0.0, ymin=0.0, xmax=1000.0, ymax=1000.0)
    wide = box(-200, 100, 1300, 900)
    o = X.oob_outline(wide, te)
    assert box(0, 0, 1000, 1000).buffer(1e-6).contains(o) and abs(o.area - 1000 * 800) < 1
    inside = Polygon([(100, 100), (900, 120), (500, 800)])
    assert X.oob_outline(inside, te) is inside
    assert X.oob_outline(None, te) is None
