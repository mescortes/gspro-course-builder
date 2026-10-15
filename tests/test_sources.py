"""Data providers (scripts/sources): which files each one asks for, without network access."""
import json, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config as C  # noqa: E402
import sources  # noqa: E402
from sources import arcgis_imageserver as A, cog_dem, nrcan_copc, usgs_3dep  # noqa: E402


class _Resp:
    def __init__(self, status=200, headers=None, payload=None):
        self.status_code, self.headers, self._payload = status, headers or {}, payload

    def json(self):
        return self._payload


def test_westmount_asks_for_the_same_six_lidar_tiles_as_before():
    """fetch_data.py had the Lake Erie 2018 URL template hard-coded; the NRCan provider builds it from course.toml."""
    mod, spec = sources.provider("lidar")
    assert mod is nrcan_copc
    urls = [nrcan_copc.url(spec, spec["projects"][0], e, n) for e, n in nrcan_copc.tiles(C.FETCH_CORE)]
    old = ("https://canelevation-lidar-point-clouds.s3.ca-central-1.amazonaws.com/pointclouds_nuagespoints/ON/"
           "Lake_Erie_2018/1km17{e:04d}{n:05d}2018LLAKEERIE.copc.laz")
    assert urls == [old.format(e=e, n=n) for e, n in [(5360, 48100), (5360, 48110), (5370, 48100), (5370, 48110),
                                                      (5380, 48100), (5380, 48110)]]


def test_a_tile_comes_from_the_first_project_folder_that_has_it(tmp_path, monkeypatch):
    """Deer Ridge sits on the seam of two NRCan folders (Lake_Erie_2018 and Lake_Erie_Fall_2017)."""
    spec = {"provider": "nrcan_copc", "zone": 17, "projects": [{"folder": "ON/A", "suffix": "2018X"},
                                                                {"folder": "ON/B", "suffix": "2017X"}]}
    have = {"ON/A/1km17546048060": 10, "ON/B/1km17546048050": 20}   # 48050 is only in B, 48060 in A (and B)
    heads, got = [], []
    def head(url, **kw):
        heads.append(url)
        key = url.split("pointclouds_nuagespoints/")[1][:len("ON/A/1km17546048060")]
        size = have.get(key) or (30 if key == "ON/B/1km17546048060" else None)
        return _Resp(200, {"Content-Length": str(size)}) if size else _Resp(404)
    monkeypatch.setattr(nrcan_copc.http.requests, "head", head)
    monkeypatch.setattr(nrcan_copc.http, "download", lambda url, dst, size=None: got.append((url.split("/")[-2], dst.name, size)))
    ext = dict(xmin=546100.0, ymin=4805100.0, xmax=546900.0, ymax=4806900.0)
    n = nrcan_copc.fetch(spec, ext, tmp_path)
    assert got == [("B", "1km17546048050" + "2017X.copc.laz", 20), ("A", "1km17546048060" + "2018X.copc.laz", 10)] and n == 2
    assert not any("ON/B/1km17546048060" in u for u in heads)   # A had it: B is not asked


TNM = {"total": 3, "items": [
    {"title": "USGS Lidar Point Cloud CA_NorthCoastRanges_B23 536291", "downloadURL": "https://x/USGS_LPC_CA_NorthCoastRanges_B23_536291.laz",
     "boundingBox": {"minX": -122.5815, "maxX": -122.5700, "minY": 38.7700, "maxY": 38.7791}},
    {"title": "USGS Lidar Point Cloud CA_LakeCounty_2015 1234", "downloadURL": "https://x/USGS_LPC_CA_LakeCounty_2015_1234.laz",
     "boundingBox": {"minX": -122.5815, "maxX": -122.5700, "minY": 38.7700, "maxY": 38.7791}},
    {"title": "USGS Lidar Point Cloud CA_NorthCoastRanges_B23 540291", "downloadURL": "https://x/USGS_LPC_CA_NorthCoastRanges_B23_540291.laz",
     "boundingBox": {"minX": -122.5400, "maxX": -122.5285, "minY": 38.7700, "maxY": 38.7791}}]}


def test_3dep_tiles_are_the_projects_tiles_that_reach_the_extent(tmp_path, monkeypatch):
    """The National Map lists every project's tiles in a padded lon/lat box: keep the named project, and only the tiles
    that really overlap the extent in the course CRS."""
    spec = {"provider": "usgs_3dep", "project": "CA_NorthCoastRanges_B23"}
    calls, got = [], []
    def get(url, params=None, **kw):
        calls.append(params); return _Resp(200, payload=TNM)
    monkeypatch.setattr(usgs_3dep.http.requests, "get", get)
    monkeypatch.setattr(usgs_3dep.http, "download", lambda url, dst, size=None: got.append(dst.name))
    ext = dict(xmin=536600.0, ymin=4291100.0, xmax=537000.0, ymax=4291500.0)   # EPSG:6339, inside tile 536291
    usgs_3dep.fetch(spec, ext, tmp_path, crs="EPSG:6339")
    assert got == ["USGS_LPC_CA_NorthCoastRanges_B23_536291.laz"]
    assert calls[0]["datasets"] == "Lidar Point Cloud (LPC)" and len(calls[0]["bbox"].split(",")) == 4


def test_the_imageserver_request_is_the_one_westmount_has_always_sent(tmp_path, monkeypatch):
    """Same bbox, bands, mosaic rule and interpolation as fetch_imageserver.py with its SWOOP defaults, so a refetch
    returns the same pixels."""
    _, spec = sources.provider("imagery")
    sent = []
    def get(url, params=None, **kw):
        sent.append((url, params)); return _Resp(500)
    monkeypatch.setattr(A.requests, "get", get)
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    with pytest.raises(SystemExit):
        A.fetch(spec, 537000.0, 4810000.0, 537100.0, 4810100.0, 0.16, tmp_path / "x.tif", bands=tuple(spec["bands"]))
    url, p = next(s for s in sent if s[0].endswith("/exportImage"))
    assert url == "https://ws.geoservices.lrc.gov.on.ca/arcgis5/rest/services/AerialImagery/GEO_Imagery_Data_Service_2023to2027/ImageServer/exportImage"
    assert p == dict(bbox="537000.000,4810000.000,537100.000,4810100.000", bboxSR=2958, imageSR=2958, size="625,625",
                     format="tiff", pixelType="U8", bandIds="0,1,2,3", interpolation="RSP_BilinearInterpolation",
                     noData=0, f="image", mosaicRule=json.dumps({"mosaicMethod": "esriMosaicNorthwest", "where": "Project='SWOOP2025'"}))


def test_chunks_tile_the_grid_exactly():
    W, H, wins = A.chunks(1000.0, 2000.0, 1100.0, 2064.0, 0.16, 256)
    assert (W, H) == (625, 400)
    cover = [[0] * W for _ in range(H)]
    for c0, r0, w, h, (x0, y0, x1, y1) in wins:
        assert abs((x1 - x0) - w * 0.16) < 1e-9 and abs((y1 - y0) - h * 0.16) < 1e-9
        assert abs(x0 - (1000.0 + c0 * 0.16)) < 1e-9 and abs(y1 - (2064.0 - r0 * 0.16)) < 1e-9
        for r in range(r0, r0 + h):
            for c in range(c0, c0 + w):
                cover[r][c] += 1
    assert all(v == 1 for row in cover for v in row)


def test_chunk_ground_size_is_capped_for_coarse_requests():
    assert A.chunk_size(0.16) == 2500                 # 400 m at native resolution
    assert A.chunk_size(1.25) * 1.25 <= A.MAX_CHUNK_M  # the 5 km backdrop at 1.25 m: 640 px chunks, not 3 km ones
    assert A.chunk_size(1000.0) == 64
    assert A.chunk_size(0.6, max_m=2000.0) == 2500 and A.chunk_size(0.6, chunk_px=4000, max_m=2000.0) == 3333


def test_backdrop_dems_come_from_the_course_file():
    _, spec = sources.provider("backdrop")
    base = "https://canelevation-dem.s3.ca-central-1.amazonaws.com/hrdem-lidar/"
    assert spec["dtm"] == [base + "ON-Lake_Erie_2018-1m-dtm.tif", base + "VILLE_WATERLOO-VILLE_WATERLOO-1m-dtm.tif"]
    assert spec["dsm"] == [u.replace("-1m-dtm.tif", "-1m-dsm.tif") for u in spec["dtm"]]
    assert cog_dem.urls({"dtm": ["a"]}, "dsm") == []


def test_a_course_without_a_source_says_which_table_is_missing(monkeypatch):
    monkeypatch.setattr(C, "DATA_SOURCES", {})
    with pytest.raises(SystemExit, match=r"\[sources.lidar\]"):
        sources.provider("lidar")
