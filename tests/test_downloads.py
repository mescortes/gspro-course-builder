"""Downloads (scripts/fetch_*.py, scripts/sources): written atomically, resumed, retried only when a retry can help,
recorded with the request they were made from, and checked against course.toml on a rerun. Synthetic data, no network."""
import json, sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
import requests
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config as C  # noqa: E402
import fetch_data  # noqa: E402


class Resp:
    """A requests.Response stand-in: a JSON payload, a body, or a stream of chunks (a callable giving an iterator)."""
    def __init__(self, status=200, body=b"", headers=None, payload=None, chunks=None):
        self.status_code, self.headers, self._payload, self._chunks = status, headers or {}, payload, chunks
        self.content = body if isinstance(body, bytes) else body.encode()
        self.text = body if isinstance(body, str) else body.decode("latin-1")

    def json(self):
        return self._payload if self._payload is not None else json.loads(self.text)

    def iter_content(self, n):
        return self._chunks() if self._chunks else iter([self.content])

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _no_sleep(monkeypatch):
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)


def _tiff(a):
    """GeoTIFF bytes of a (bands, h, w) uint8 array, as an ImageServer exportImage answers."""
    with rasterio.MemoryFile() as mf:
        with mf.open(driver="GTiff", width=a.shape[2], height=a.shape[1], count=a.shape[0], dtype="uint8",
                     transform=from_origin(0, a.shape[1], 1, 1)) as d:
            d.write(a)
        return mf.read()


def _image(a):
    return Resp(200, headers={"content-type": "image/tiff"}, body=_tiff(a))


def _photo(path, box, res=1.0, count=4, value=90, zero_east_half=False):
    W = int(round((box[2] - box[0]) / res)); H = int(round((box[3] - box[1]) / res))
    a = np.full((count, H, W), value, np.uint8)
    if zero_east_half:
        a[:, :, W // 2:] = 0
    with rasterio.open(path, "w", driver="GTiff", width=W, height=H, count=count, dtype="uint8", crs=C.CRS,
                       transform=from_origin(box[0], box[3], res, res)) as d:
        d.write(a)


# ---- sources/http.py

def test_a_download_resumes_its_part_file(tmp_path, monkeypatch):
    """Every retry reopened the .part file from zero and sent no Range header ('resumable' said the docstring), so a
    proxy that drops long transfers never let a 300-900 MB tile through. A reply shorter than its Content-Length was
    renamed into place as if complete."""
    from sources import http
    data = bytes(range(10))
    sent = []

    def get(url, headers=None, **kw):
        sent.append(dict(headers or {}))
        rng = (headers or {}).get("Range")
        if rng is None:   # the first try: the connection drops after 6 bytes
            def chunks():
                yield data[:6]
                raise requests.exceptions.ChunkedEncodingError("connection dropped")
            return Resp(200, headers={"Content-Length": "10"}, chunks=chunks)
        start = int(rng.split("=")[1].rstrip("-"))
        return Resp(206, headers={"Content-Length": str(10 - start), "Content-Range": f"bytes {start}-9/10"},
                    body=data[start:])
    monkeypatch.setattr(http.requests, "get", get); _no_sleep(monkeypatch)
    http.download("https://x/t.laz", tmp_path / "t.laz", 10)
    assert (tmp_path / "t.laz").read_bytes() == data and not (tmp_path / "t.laz.part").exists()
    assert sent[1]["Range"] == "bytes=6-"

    sent.clear()
    def short(url, headers=None, **kw):   # 6 bytes and a clean end, then the rest on request
        sent.append(dict(headers or {}))
        if "Range" not in (headers or {}):
            return Resp(200, headers={"Content-Length": "10"}, body=data[:6])
        return Resp(206, headers={"Content-Range": "bytes 6-9/10"}, body=data[6:])
    monkeypatch.setattr(http.requests, "get", short)
    http.download("https://x/u.laz", tmp_path / "u.laz")
    assert (tmp_path / "u.laz").read_bytes() == data and len(sent) == 2


def test_a_whole_part_file_of_unknown_size_is_renamed_not_fetched_again(tmp_path, monkeypatch):
    """With no size given (every 3DEP tile, every Poly Haven file), a whole .part left by a crash before the rename was
    asked for its remaining bytes, the server answered 416, and the .part was deleted and fetched again: a 300-900 MB
    tile downloaded twice."""
    from sources import http
    data = bytes(range(10))
    sent = []

    def get(url, headers=None, **kw):
        rng = (headers or {}).get("Range")
        sent.append(rng)
        if rng and int(rng.split("=")[1].rstrip("-")) >= len(data):
            return Resp(416, headers={"Content-Range": f"bytes */{len(data)}"})
        return Resp(200, headers={"Content-Length": str(len(data))}, body=data)
    monkeypatch.setattr(http.requests, "get", get); _no_sleep(monkeypatch)
    (tmp_path / "t.laz.part").write_bytes(data)
    http.download("https://x/t.laz", tmp_path / "t.laz")
    assert (tmp_path / "t.laz").read_bytes() == data and sent == ["bytes=10-"]
    sent.clear()
    (tmp_path / "u.laz.part").write_bytes(data + b"xy")   # longer than the file: stale, fetched again
    http.download("https://x/u.laz", tmp_path / "u.laz")
    assert (tmp_path / "u.laz").read_bytes() == data and sent == ["bytes=12-", None]
    assert not (tmp_path / "t.laz.part").exists() and not (tmp_path / "u.laz.part").exists()


def test_a_permanent_http_error_is_not_retried_and_says_its_status(tmp_path, monkeypatch):
    """A 404 (a stale TNM link) or a proxy 403 was retried 5 times over 5 minutes, logged as 'HTTPError' only."""
    from sources import http
    calls = []
    monkeypatch.setattr(http.requests, "get", lambda url, **kw: calls.append(url) or Resp(404)); _no_sleep(monkeypatch)
    with pytest.raises(RuntimeError, match="404"):
        http.download("https://x/gone.laz", tmp_path / "gone.laz")
    assert len(calls) == 1 and not (tmp_path / "gone.laz").exists()


# ---- LiDAR: tiles.json

def test_a_lidar_fetch_lists_its_tiles_and_moves_other_tiles_out(tmp_path, monkeypatch):
    """Switching [sources.lidar] project (or the NRCan folder order) left the old project's tiles next to the new ones
    (other file names), and the rasters and trees were built from both flights."""
    from sources import nrcan_copc
    (tmp_path / "1km17546048050OLD.copc.laz").write_bytes(b"old")
    monkeypatch.setattr(nrcan_copc.http, "size", lambda u: 3)
    monkeypatch.setattr(nrcan_copc.http, "download", lambda url, dst, size=None: dst.write_bytes(b"new"))
    spec = {"provider": "nrcan_copc", "zone": 17, "projects": [{"folder": "ON/A", "suffix": "NEW"}]}
    ext = dict(xmin=546100.0, ymin=4805100.0, xmax=546900.0, ymax=4805900.0)
    assert nrcan_copc.fetch(spec, ext, tmp_path) == 1
    m = json.loads((tmp_path / "tiles.json").read_text())
    assert m["tiles"] == ["1km17546048050NEW.copc.laz"] and m["spec"] == spec and m["extent"] == ext
    assert [p.name for p in tmp_path.glob("*.laz")] == ["1km17546048050NEW.copc.laz"]
    assert (tmp_path / "unused/1km17546048050OLD.copc.laz").read_bytes() == b"old"


def test_the_build_reads_only_the_tiles_the_last_lidar_fetch_listed(tmp_path, monkeypatch):
    folder = tmp_path / "lidar"; folder.mkdir()
    for n in ("a.laz", "old.laz"):
        (folder / n).write_bytes(b"")
    monkeypatch.setattr(C, "DATA", tmp_path)
    monkeypatch.setattr(C, "LIDAR_TILES", sorted(folder.glob("*.laz")))
    assert C.lidar_tiles() == C.LIDAR_TILES   # no tiles.json (fetched before it existed): the folder as it is
    manifest = dict(spec=C.DATA_SOURCES["lidar"], extent=C.FETCH_CORE, tiles=["a.laz"])
    (folder / "tiles.json").write_text(json.dumps(manifest))
    with pytest.raises(SystemExit, match="old.laz"):
        C.lidar_tiles()
    (folder / "old.laz").unlink(); monkeypatch.setattr(C, "LIDAR_TILES", [folder / "a.laz"])
    assert C.lidar_tiles() == [folder / "a.laz"]
    (folder / "tiles.json").write_text(json.dumps(dict(manifest, tiles=["a.laz", "b.laz"])))
    with pytest.raises(SystemExit, match="b.laz"):
        C.lidar_tiles()
    (folder / "tiles.json").write_text(json.dumps(manifest))
    other = dict(C.DATA_SOURCES["lidar"], projects=[{"folder": "ON/B", "suffix": "2017X"}])
    monkeypatch.setattr(C, "DATA_SOURCES", dict(C.DATA_SOURCES, lidar=other))
    with pytest.raises(SystemExit, match=r"\[sources.lidar\].*fetch_data.py lidar"):
        C.lidar_tiles()


def test_a_lidar_setting_change_names_the_key_and_a_threshold_change_needs_no_refetch(tmp_path, monkeypatch):
    """Any edit of [sources.lidar] blocked the build with 'fetched for another [sources.lidar] or [frame] core', even
    max_uncovered or missing_ok, which only accept or refuse a fetch (the tiles are the same), and the message did not
    say which key or which side of the core had changed. Rerunning fetch_data.py lidar needs the network."""
    folder = tmp_path / "lidar"; folder.mkdir(); (folder / "a.laz").write_bytes(b"")
    monkeypatch.setattr(C, "DATA", tmp_path)
    spec = {"provider": "usgs_3dep", "project": "CA_NorthCoastRanges_B23"}
    (folder / "tiles.json").write_text(json.dumps(dict(spec=spec, extent=C.FETCH_CORE, tiles=["a.laz"])))
    monkeypatch.setattr(C, "DATA_SOURCES", dict(C.DATA_SOURCES, lidar=dict(spec, max_uncovered=0.05)))
    assert C.lidar_problems() == []
    nrcan = {"provider": "nrcan_copc", "zone": 17, "projects": [{"folder": "ON/A", "suffix": "X"}]}
    (folder / "tiles.json").write_text(json.dumps(dict(spec=nrcan, extent=C.FETCH_CORE, tiles=["a.laz"])))
    monkeypatch.setattr(C, "DATA_SOURCES", dict(C.DATA_SOURCES, lidar=dict(nrcan, missing_ok=[[5460, 48050]])))
    assert C.lidar_problems() == []
    monkeypatch.setattr(C, "DATA_SOURCES", dict(C.DATA_SOURCES, lidar=dict(nrcan, zone=18)))
    [msg] = C.lidar_problems()
    assert "zone = 17" in msg and "18" in msg and "fetch_data.py lidar" in msg and "core" not in msg
    monkeypatch.setattr(C, "DATA_SOURCES", dict(C.DATA_SOURCES, lidar=nrcan))
    monkeypatch.setattr(C, "FETCH_CORE", dict(C.FETCH_CORE, xmax=C.FETCH_CORE["xmax"] + 256))
    [msg] = C.lidar_problems()
    assert "[frame] core" in msg and "xmax" in msg and "[sources.lidar]" not in msg


# ---- LiDAR: USGS 3DEP

EXT_3DEP = dict(xmin=536600.0, ymin=4291500.0, xmax=537000.0, ymax=4291900.0)   # EPSG:6339, inside the box below


def _tnm_items(n, project="CA_NorthCoastRanges_B23"):
    box = {"minX": -122.5815, "maxX": -122.5700, "minY": 38.7700, "maxY": 38.7791}
    return [{"title": f"USGS Lidar Point Cloud {project} {i}", "downloadURL": f"https://x/USGS_LPC_{project}_{i}.laz",
             "boundingBox": box} for i in range(n)]


def test_an_error_page_in_the_tnm_listing_is_retried_not_taken_for_its_end(monkeypatch):
    """Page 2 of a listing answered an error body: the listing stopped after page 1, the fetch downloaded half the
    tiles and exited 0. An HTML 502 page crashed on a bare JSONDecodeError."""
    from sources import usgs_3dep
    its = _tnm_items(16)
    seq = [Resp(200, payload={"total": 16, "items": its[:8]}), Resp(200, payload={"errorMessage": "Internal error"}),
           Resp(502, body="<html>Bad Gateway</html>"), Resp(200, payload={"total": 16, "items": its[8:]})]
    monkeypatch.setattr(usgs_3dep.http.requests, "get", lambda url, params=None, **kw: seq.pop(0)); _no_sleep(monkeypatch)
    assert len(usgs_3dep.items({"project": "CA_NorthCoastRanges_B23"}, EXT_3DEP, "EPSG:6339")) == 16
    seq[:] = [Resp(200, payload={"total": 16, "items": its[:8]})] + [Resp(200, payload={"errorMessage": "Internal error"})] * 9
    with pytest.raises(RuntimeError, match="Internal error"):
        usgs_3dep.items({"project": "CA_NorthCoastRanges_B23"}, EXT_3DEP, "EPSG:6339")


def test_a_3dep_fetch_with_no_tile_of_its_project_stops_naming_the_projects_there(tmp_path, monkeypatch):
    """A mistyped project printed 'no tile reaches the extent' and exited 0; the build then said 'run fetch_data.py
    lidar', which had just run."""
    from sources import usgs_3dep
    page = {"total": 2, "items": _tnm_items(2, "CA_LakeCounty_2015")}
    monkeypatch.setattr(usgs_3dep.http.requests, "get", lambda *a, **k: Resp(200, payload=page))
    with pytest.raises(SystemExit, match="CA_LakeCounty_2015"):
        usgs_3dep.fetch({"provider": "usgs_3dep", "project": "CA_NorthCoastRange_B23"}, EXT_3DEP, tmp_path, crs="EPSG:6339")


def test_a_hole_in_the_3dep_tiles_stops_the_fetch(tmp_path, monkeypatch):
    """Unlike the NRCan fetch, nothing checked that the listed tiles cover the extent: a tile missing from the listing
    left a hole inside the course that build_rasters filled with flat terraces."""
    from sources import usgs_3dep
    from pyproj import Transformer
    to_ll = Transformer.from_crs("EPSG:6339", "EPSG:4326", always_xy=True)

    def item(x0):
        ll = [to_ll.transform(x, y) for x in (x0, x0 + 1000.0) for y in (4291000.0, 4292000.0)]
        return {"title": f"USGS Lidar Point Cloud B23 {x0:.0f}", "downloadURL": f"https://x/USGS_LPC_B23_{x0:.0f}.laz",
                "boundingBox": dict(minX=min(p[0] for p in ll), maxX=max(p[0] for p in ll),
                                    minY=min(p[1] for p in ll), maxY=max(p[1] for p in ll))}
    ext = dict(xmin=538100.0, ymin=4291100.0, xmax=539900.0, ymax=4291900.0)
    page = {"total": 1, "items": [item(538000.0)]}
    got = []
    monkeypatch.setattr(usgs_3dep.http.requests, "get", lambda *a, **k: Resp(200, payload=page))
    monkeypatch.setattr(usgs_3dep.http, "download", lambda url, dst, size=None: got.append(dst.name))
    with pytest.raises(SystemExit, match="max_uncovered"):
        usgs_3dep.fetch({"provider": "usgs_3dep", "project": "B23"}, ext, tmp_path, crs="EPSG:6339")
    assert got == []
    usgs_3dep.fetch({"provider": "usgs_3dep", "project": "B23", "max_uncovered": 0.6}, ext, tmp_path, crs="EPSG:6339")
    assert got == ["USGS_LPC_B23_538000.laz"]
    page.update(total=2, items=[item(538000.0), item(539000.0)]); got.clear()
    usgs_3dep.fetch({"provider": "usgs_3dep", "project": "B23"}, ext, tmp_path, crs="EPSG:6339")
    assert got == ["USGS_LPC_B23_538000.laz", "USGS_LPC_B23_539000.laz"]
    assert json.loads((tmp_path / "tiles.json").read_text())["tiles"] == got


def test_the_3dep_coverage_error_gives_a_small_share_and_says_where_the_gap_is(tmp_path, monkeypatch):
    """One uncovered column of 10 m samples over 2 km read 'leave 0% of the extent uncovered ... max_uncovered = 0.01',
    and the box of every uncovered sample spanned the whole extent for a ring of margin or for two gaps."""
    from sources import usgs_3dep
    ext = dict(xmin=0.0, ymin=0.0, xmax=1970.0, ymax=1970.0)   # + 15 m margin: -15 .. 1985, 201 x 201 samples

    def stop(*boxes):
        tiles = [(f"t{i}", f"https://x/t{i}.laz", b) for i, b in enumerate(boxes)]
        monkeypatch.setattr(usgs_3dep, "listing", lambda *a, **k: [])
        monkeypatch.setattr(usgs_3dep, "keep", lambda *a, **k: tiles)
        with pytest.raises(SystemExit) as ex:
            usgs_3dep.fetch({"provider": "usgs_3dep", "project": "B23"}, ext, tmp_path, crs="EPSG:6339")
        return str(ex.value)
    msg = stop((-15.0, -15.0, 1980.0, 1985.0))   # the east column x = 1985 uncovered: 201 / 201^2
    assert "0.5% of the extent" in msg and "east edge" in msg and "max_uncovered = 0.01" in msg
    msg = stop((-10.0, -10.0, 1980.0, 1980.0))   # a ring of margin
    assert "north, south, east and west edges" in msg
    msg = stop((-15.0, -15.0, 900.0, 1985.0), (1000.0, -15.0, 1700.0, 1985.0), (1750.0, -15.0, 1985.0, 1985.0))
    assert "2 gaps, the largest E 900-1000 N -15-1985" in msg   # not the box of both: E 900-1750

def test_an_overpass_reply_with_a_runtime_error_is_not_a_snapshot(tmp_path, monkeypatch):
    """Overpass answers HTTP 200 with a 'remark' and empty or partial elements when the query times out or runs out of
    memory: that reply was saved as osm_all.json and kept for good."""
    bad = json.dumps({"remark": 'runtime error: Query timed out in "query" at line 1 after 181 seconds.', "elements": []})
    good = json.dumps({"elements": [{"type": "node", "id": 1, "lat": 0.0, "lon": 0.0}]})
    seq = [Resp(200, body=bad), Resp(200, body=good)]
    monkeypatch.setattr(fetch_data.requests, "post", lambda *a, **k: seq.pop(0)); _no_sleep(monkeypatch)
    assert fetch_data.overpass("q", tmp_path / "osm_all.json")
    assert json.loads((tmp_path / "osm_all.json").read_text())["elements"][0]["id"] == 1
    posts = []
    monkeypatch.setattr(fetch_data.requests, "post", lambda *a, **k: posts.append(a[0]) or Resp(200, body=bad))
    assert not fetch_data.overpass("q", tmp_path / "osm_golf.json") and not (tmp_path / "osm_golf.json").exists()
    assert len(posts) == len(fetch_data.OVERPASS)   # too big for Overpass: on to the OSM API, not two more rounds


def test_a_busy_overpass_mirror_is_retried_not_taken_for_a_query_too_big(tmp_path, monkeypatch):
    """Any remark with 'error' ended the Overpass rounds, including a mirror's 'The server is probably too busy' (a
    transient load): one busy mirror and two 504s sent the box to the tiled OSM API, whose /map lacks the geometry of
    relation members outside the box, without trying Overpass again."""
    busy = json.dumps({"remark": "runtime error: open64: 0 Success /osm3s_osm_base Dispatcher_Client::request_read_and_idx"
                                 "::timeout. The server is probably too busy to handle your request.", "elements": []})
    too_big = json.dumps({"remark": "runtime error: Query run out of memory using about 2048 MB of RAM.", "elements": []})
    good = json.dumps({"elements": [{"type": "node", "id": 1, "lat": 0.0, "lon": 0.0}]})
    seq = [Resp(200, body=busy), Resp(504), Resp(504), Resp(200, body=good)]
    monkeypatch.setattr(fetch_data.requests, "post", lambda *a, **k: seq.pop(0)); _no_sleep(monkeypatch)
    assert fetch_data.overpass("q", tmp_path / "osm_all.json") and seq == []
    posts = []

    def post(ep, **kw):   # too big on the first mirror, no answer from the others: on to the OSM API at once
        posts.append(ep)
        if ep != fetch_data.OVERPASS[0]:
            raise requests.ConnectionError("no route")
        return Resp(200, body=too_big)
    monkeypatch.setattr(fetch_data.requests, "post", post)
    assert not fetch_data.overpass("q", tmp_path / "osm_golf.json") and posts == list(fetch_data.OVERPASS)


def test_an_osm_snapshot_that_no_longer_reaches_the_course_extent_stops_the_fetch(tmp_path, monkeypatch):
    """An existing snapshot is kept on purpose (the model and its overrides were built from it), but after [frame]
    core grew it lacked every OSM feature of the new strip, without a word."""
    from sources import store
    calls = []
    monkeypatch.setattr(C, "RESEARCH", tmp_path)
    monkeypatch.setattr(fetch_data, "overpass", lambda q, path: calls.append(path) or Path(path).write_text('{"elements": []}') or True)
    fetch_data.fetch_osm()
    assert store.read_record(tmp_path / "osm_all.json")["bbox"] == list(fetch_data.lonlat_bbox(C.FETCH_CORE, 400))
    calls.clear()
    fetch_data.fetch_osm()
    assert calls == []   # it covers the extent: kept
    monkeypatch.setattr(C, "FETCH_CORE", dict(C.FETCH_CORE, xmax=C.FETCH_CORE["xmax"] + 512))
    with pytest.raises(SystemExit, match="osm_all.json"):
        fetch_data.fetch_osm()
    assert calls == []


def test_the_osm_api_fallback_survives_a_dropped_connection_and_splits_a_tile_over_the_node_limit(monkeypatch):
    """One ConnectionError aborted the fallback with a traceback, and a tile over the API's 50,000-node limit (a
    permanent HTTP 400 for that box) was retried 5 times, then raised."""
    calls = []

    def get(url, params=None, **kw):
        calls.append(params["bbox"])
        if len(calls) == 1:
            raise requests.ConnectionError("connection reset")
        w, s, e, n = map(float, params["bbox"].split(","))
        if e - w > 0.006:
            return Resp(400, body="You requested too many nodes (limit is 50000). Either request a smaller area, or use planet.osm")
        return Resp(200, body=f'<osm version="0.6"><node id="{len(calls)}" lat="{s}" lon="{w}"><tag k="golf" v="pin"/></node></osm>')
    monkeypatch.setattr(fetch_data.requests, "get", get); _no_sleep(monkeypatch)
    els = fetch_data.osm_api_map((-80.01, 43.0, -80.0, 43.01))
    assert len(els) == 4 and len(calls) == 1 + 1 + 4   # the dropped try, the refused tile, its four quarters


# ---- imagery

def test_an_imageserver_fetch_resumes_from_its_chunks(tmp_path, monkeypatch):
    """One chunk failing 6 times in a row (~105 s on a flaky server) threw away every chunk already downloaded, and
    the rerun started again from chunk 1 (the 5 km backdrop photo took 84 min)."""
    from sources import arcgis_imageserver as A, store
    spec = {"url": "https://s", "chunk_px": 64, "max_chunk_m": 1000.0}
    asked, state = [], {"down": True}

    def get(url, params=None, **kw):
        x0 = params["bbox"].split(",")[0]   # "0.000": the west chunk, "64.000": the east one
        asked.append(x0)
        if x0 == "64.000" and state["down"]:
            return Resp(500)
        return _image(np.full((1, 64, 64), 7 if x0 == "0.000" else 9, np.uint8))
    monkeypatch.setattr(A.requests, "get", get); _no_sleep(monkeypatch)
    out = tmp_path / "photo.tif"
    with pytest.raises(SystemExit, match="rerun"):
        A.fetch(spec, 0.0, 0.0, 128.0, 64.0, 1.0, out, bands=(0,))
    assert not out.exists() and asked.count("0.000") == 1
    state["down"] = False
    A.fetch(spec, 0.0, 0.0, 128.0, 64.0, 1.0, out, bands=(0,))
    assert asked.count("0.000") == 1   # the west chunk came from the cache
    with rasterio.open(out) as d:
        a = d.read(1)
    assert (a[:, :64] == 7).all() and (a[:, 64:] == 9).all()
    assert not (tmp_path / "photo.tif.chunks").exists()
    rec = store.read_record(out)
    assert rec["url"] == "https://s" and rec["bands"] == [0] and rec["bbox"] == [0.0, 0.0, 128.0, 64.0] and rec["res"] == 1.0


def test_an_imageserver_error_in_a_200_reply_stops_at_once(tmp_path, monkeypatch):
    """ArcGIS reports a bad parameter (wrong bandIds, an invalid mosaic rule where clause) as HTTP 200 with a JSON error
    body. Only a 4xx status counted as permanent, so a config mistake was retried 10 times over 25 min of waits (one
    of them after the last try), then said 'rerun to resume'."""
    import time
    from sources import arcgis_imageserver as A
    sleeps, calls = [], []
    monkeypatch.setattr(time, "sleep", sleeps.append)

    def answer(code):
        body = json.dumps({"error": {"code": code, "message": "Unable to complete operation.",
                                     "details": ["Invalid bandIds: 4"] if code == 400 else []}})
        return lambda url, params=None, **kw: calls.append(url) or Resp(200, headers={"content-type": "text/plain"}, body=body)
    monkeypatch.setattr(A.requests, "get", answer(400))
    with pytest.raises(SystemExit, match=r"Invalid bandIds.*bands in course.toml") as ex:
        A.fetch({"url": "https://s"}, 0.0, 0.0, 64.0, 64.0, 1.0, tmp_path / "a.tif", bands=(0, 1, 2, 4))
    assert len(calls) == 1 and sleeps == [] and "rerun" not in str(ex.value)
    calls.clear()
    monkeypatch.setattr(A.requests, "get", answer(500))   # a server error: retried, no wait after the last try
    with pytest.raises(SystemExit, match="rerun"):
        A.fetch({"url": "https://s"}, 0.0, 0.0, 64.0, 64.0, 1.0, tmp_path / "a.tif", bands=(0,))
    assert len(calls) == A.ATTEMPTS and len(sleeps) == A.ATTEMPTS - 1


def test_an_interrupted_photo_write_leaves_no_photo(tmp_path, monkeypatch):
    """The ~0.5 GB GeoTIFF was written at its final path: a Ctrl-C (or sleep, or OOM) during the write left a truncated
    file that fetch_data.py and build_backdrop.py then trusted because it existed."""
    from sources import arcgis_imageserver as A
    monkeypatch.setattr(A.requests, "get", lambda url, params=None, **kw: _image(np.full((1, 64, 64), 5, np.uint8)))
    real = rasterio.open

    class Killed:
        def __init__(self, ds): self.ds = ds
        def __enter__(self): return self
        def write(self, *a, **k): raise KeyboardInterrupt
        def __exit__(self, *a): self.ds.close()
    monkeypatch.setattr(A.rasterio, "open", lambda p, mode="r", **kw: Killed(real(p, mode, **kw)) if mode == "w" else real(p, mode, **kw))
    out = tmp_path / "photo.tif"
    with pytest.raises(KeyboardInterrupt):
        A.fetch({"url": "https://s"}, 0.0, 0.0, 64.0, 64.0, 1.0, out, bands=(0,))
    assert not out.exists() and not (tmp_path / "photo.tif.part").exists()


def test_a_course_photo_with_a_black_strip_is_an_error(tmp_path, monkeypatch):
    """Only a fully empty photo failed: a mosaic rule covering half the course went through, and the classifier and
    the drape got a black strip."""
    from sources import arcgis_imageserver as A
    half = np.zeros((1, 64, 64), np.uint8); half[:, :, :32] = 80
    monkeypatch.setattr(A.requests, "get", lambda url, params=None, **kw: _image(half))
    with pytest.raises(SystemExit, match="max_empty"):
        A.fetch({"url": "https://s"}, 0.0, 0.0, 64.0, 64.0, 1.0, tmp_path / "a.tif", bands=(0,), max_empty=0.01)
    assert not (tmp_path / "a.tif").exists()
    A.fetch({"url": "https://s"}, 0.0, 0.0, 64.0, 64.0, 1.0, tmp_path / "b.tif", bands=(0,))   # no limit: as before
    assert (tmp_path / "b.tif").exists()


def test_an_existing_photo_must_be_the_one_course_toml_asks_for(tmp_path, monkeypatch):
    """fetch_data.py imagery returned at once when the photo existed: after [frame] core grew, [imagery] res or
    [sources.imagery] mosaic_rule changed, the old photo was kept without a word (a black strip where the core grew,
    the old year after a source change)."""
    from sources import arcgis_imageserver as A, store
    monkeypatch.setattr(C, "FETCH_CORE", dict(xmin=1000.0, ymin=2000.0, xmax=1100.0, ymax=2100.0))
    monkeypatch.setattr(C, "IMAGERY_RES", 1.0)
    dst = tmp_path / "photo.tif"; monkeypatch.setattr(C, "IMAGERY_RAW", dst)
    got = []
    monkeypatch.setattr(A, "fetch", lambda spec, *a, **k: got.append(k))
    _photo(dst, (980.0, 1980.0, 1060.0, 2120.0))   # fetched before the core grew east
    with pytest.raises(SystemExit, match=r"core"):
        fetch_data.fetch_imagery()
    _photo(dst, (980.0, 1980.0, 1120.0, 2120.0))
    fetch_data.fetch_imagery()   # no record (an older fetch): kept, and recorded
    assert got == [] and store.read_record(dst)["mosaic_rule"] == C.DATA_SOURCES["imagery"]["mosaic_rule"]
    fetch_data.fetch_imagery()
    assert got == []
    sources_now = C.DATA_SOURCES
    other = dict(C.DATA_SOURCES["imagery"], mosaic_rule={"mosaicMethod": "esriMosaicNorthwest", "where": "Project='X2020'"})
    monkeypatch.setattr(C, "DATA_SOURCES", dict(C.DATA_SOURCES, imagery=other))
    with pytest.raises(SystemExit, match="mosaic_rule"):
        fetch_data.fetch_imagery()
    monkeypatch.setattr(C, "DATA_SOURCES", sources_now); monkeypatch.setattr(C, "IMAGERY_RES", 0.5)
    with pytest.raises(SystemExit, match=r"\[imagery\] res"):
        fetch_data.fetch_imagery()
    dst.unlink()
    fetch_data.fetch_imagery()
    assert got and got[-1]["max_empty"] == 0.01


# ---- backdrop DEM

def _dem(path, x0, y0, w, h, z=300.0):
    with rasterio.open(path, "w", driver="GTiff", width=w, height=h, count=1, dtype="float32", crs="EPSG:6339",
                       transform=from_origin(x0, y0 + h, 1.0, 1.0)) as d:
        d.write(np.full((1, h, w), z, np.float32))
    return path


EXT_DEM = dict(xmin=537000.0, ymin=4291960.0, xmax=537040.0, ymax=4292000.0)


def test_a_backdrop_dem_that_cannot_be_read_stops_the_fetch(tmp_path, monkeypatch):
    """Any open error read as 'not available' (a mistyped URL, a proxy 403, a timeout), and an all-NaN
    backdrop_dem.tif was written: NaN vertices in the backdrop and a glTF the viewer cannot parse."""
    from sources import cog_dem, http
    monkeypatch.setattr(http.requests, "head", lambda url, **kw: Resp(403)); _no_sleep(monkeypatch)
    with pytest.raises(SystemExit, match="403"):
        cog_dem.fetch({"dtm": ["https://x/a-dtm.tif"]}, "dtm", EXT_DEM, 2.0, tmp_path / "out.tif", crs="EPSG:6339")
    assert not (tmp_path / "out.tif").exists()
    src = _dem(tmp_path / "dem.tif", 537000.0, 4291960.0, 40, 40)
    monkeypatch.setattr(http.requests, "head", lambda url, **kw: Resp(404))   # not published: the next source fills in
    assert cog_dem.fetch({"dtm": ["https://x/gone-dtm.tif", str(src)]}, "dtm", EXT_DEM, 2.0, tmp_path / "out.tif", crs="EPSG:6339")
    with rasterio.open(tmp_path / "out.tif") as d:
        assert np.isfinite(d.read(1)).all()


def test_a_gap_in_the_backdrop_dem_stops_the_fetch_or_is_filled(tmp_path):
    """A DTM that covered half the backdrop square was written as it was (only 'missing 0.5' printed): NaN backdrop
    vertices, a NaN GSPro heightmap range."""
    from sources import cog_dem, store
    src = _dem(tmp_path / "west.tif", 537000.0, 4291960.0, 20, 40)   # the west half only
    with pytest.raises(SystemExit, match="max_missing"):
        cog_dem.fetch({"dtm": [str(src)]}, "dtm", EXT_DEM, 2.0, tmp_path / "out.tif", crs="EPSG:6339")
    assert not (tmp_path / "out.tif").exists()
    assert cog_dem.fetch({"dtm": [str(src)], "max_missing": 0.6}, "dtm", EXT_DEM, 2.0, tmp_path / "out.tif", crs="EPSG:6339")
    with rasterio.open(tmp_path / "out.tif") as d:
        a = d.read(1)
    assert np.isfinite(a).all() and abs(float(a.mean()) - 300.0) < 1e-3
    assert store.read_record(tmp_path / "out.tif")["urls"] == [str(src)]
    # the surface model is optional (backdrop trees and roofs): a gap stays a gap
    assert cog_dem.fetch({"dsm": [str(src)]}, "dsm", EXT_DEM, 2.0, tmp_path / "dsm.tif", crs="EPSG:6339")
    with rasterio.open(tmp_path / "dsm.tif") as d:
        assert 0.4 < float(np.isnan(d.read(1)).mean()) < 0.6


# ---- textures

def test_fetch_textures_needs_no_network_once_everything_is_there(tmp_path, monkeypatch):
    """Every run asked api.polyhaven.com about every asset before looking at the files, through urllib with no retry:
    a rerun offline or during an outage crashed with every texture present."""
    from sources import http
    monkeypatch.setattr(C, "DATA", tmp_path); _no_sleep(monkeypatch)
    import fetch_textures as T
    files = {"Diffuse": {"2k": {"jpg": {"url": "https://dl/sand_01_diff_2k.jpg", "size": 3}}},
             "nor_gl": {"2k": {"png": {"url": "https://dl/sand_01_nor_gl_2k.png", "size": 3}}}, "Rough": {"1k": {}}}
    asked, got = [], []
    monkeypatch.setattr(http.requests, "get", lambda url, params=None, **kw: asked.append(url) or Resp(200, payload=files))

    def download(url, dst, size=None):
        got.append(url); dst.parent.mkdir(parents=True, exist_ok=True); dst.write_bytes(b"img")
    monkeypatch.setattr(http, "download", download)
    T.main(["sand_01"])
    assert sorted(p.name for p in (tmp_path / "textures/sand_01").iterdir()) == ["diffuse.jpg", "nor_gl.png"]
    assert asked == ["https://api.polyhaven.com/files/sand_01"] and len(got) == 2

    def offline(*a, **k):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(http.requests, "get", offline)
    T.main(["sand_01"])   # every file there: no API call
    (tmp_path / "textures/sand_01/nor_gl.png").unlink()
    with pytest.raises(SystemExit, match="sand_01"):
        T.main(["sand_01"])


def test_an_asset_poly_haven_does_not_have_names_where_its_id_comes_from(tmp_path, monkeypatch):
    """A mistyped bark or material id (Poly Haven answers 404) exited with 'check the network and rerun', which sent a
    newcomer to the network instead of the id in the region file or course.toml."""
    from sources import http
    monkeypatch.setattr(C, "DATA", tmp_path); _no_sleep(monkeypatch)
    import fetch_textures as T
    monkeypatch.setattr(C, "REGION", dict(C.REGION, materials=dict(C.REGION["materials"], cart_path="asphalt_O2")))
    monkeypatch.setattr(http.requests, "get", lambda url, params=None, **kw: Resp(404, body='{"error": "not found"}'))
    with pytest.raises(SystemExit) as ex:
        T.main(["asphalt_O2"])
    msg = str(ex.value)
    assert "asphalt_O2" in msg and "[materials]" in msg and f"regions/{C.REGION_NAME}.toml" in msg and "network" not in msg
    with pytest.raises(SystemExit, match=r"typo_bark.*command line"):
        T.main(["typo_bark"])
    monkeypatch.setattr(http.requests, "get", lambda url, params=None, **kw: Resp(200, payload={}))   # no maps at all
    with pytest.raises(SystemExit, match=r"no 2k maps.*typo_bark"):
        T.main(["typo_bark"])


# ---- check_course.py

def test_check_course_reports_downloads_that_do_not_fit_course_toml(tmp_path, monkeypatch):
    """check_course printed '0.0% empty' for any uint8 photo and compared no bounds: a photo short of the core, a
    half-black photo, a backdrop DEM of another square and tiles of two flights over the same ground all passed."""
    import check_course as K, fetch_backdrop, laspy
    monkeypatch.setattr(C, "FETCH_CORE", dict(xmin=1000.0, ymin=2000.0, xmax=1100.0, ymax=2100.0))
    monkeypatch.setattr(C, "IMAGERY_RES", 1.0); monkeypatch.setattr(C, "DATA", tmp_path)
    (tmp_path / "lidar").mkdir(); (tmp_path / "dem").mkdir()
    tiles = []
    for name, x0 in (("a.laz", 900.0), ("b.laz", 905.0)):   # two flights over the same ground
        las = laspy.LasData(laspy.LasHeader(point_format=1, version="1.2"))
        las.x = np.array([x0, x0 + 300.0]); las.y = np.array([1900.0, 2200.0]); las.z = np.array([300.0, 301.0])
        las.write(tmp_path / "lidar" / name); tiles.append(tmp_path / "lidar" / name)
    monkeypatch.setattr(C, "LIDAR_TILES", tiles)
    dst = tmp_path / "photo.tif"; monkeypatch.setattr(C, "IMAGERY_RAW", dst)
    _photo(dst, (980.0, 1980.0, 1060.0, 2120.0), zero_east_half=True)
    with rasterio.open(tmp_path / "dem/backdrop_dem.tif", "w", driver="GTiff", width=50, height=50, count=1,
                       dtype="float32", crs=C.CRS, transform=from_origin(0.0, 100.0, 2.0, 2.0)) as d:
        d.write(np.full((1, 50, 50), 300.0, np.float32))
    monkeypatch.setattr(fetch_backdrop, "B", dict(xmin=0.0, ymin=0.0, xmax=200.0, ymax=200.0))
    r = K.data_report()
    flagged = [x for x in r if x.startswith("!!")]
    assert any("a.laz" in x and "b.laz" in x for x in flagged), r
    assert any("photo" in x and "empty" in x for x in flagged), r
    assert any("photo" in x and "core" in x for x in flagged), r
    assert any("backdrop DTM" in x and "square" in x for x in flagged), r
