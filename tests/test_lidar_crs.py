"""LiDAR tiles in another CRS than the course frame ([frame] crs): State Plane feet (US 3DEP projects such as
NAD83(2011) / California zone 2 (ftUS) + NAVD88 height (ftUS)), the neighbouring UTM zone, heights in feet. They are
reprojected as they are read; tiles already in the frame are read as before. Synthetic tiles written by laspy, no
network."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config as C  # noqa: E402

SAC = (630000.0, 4270000.0)      # EPSG:6339 (NAD83(2011) / UTM zone 10N), in California zone 2
ZONE_EDGE = (720000.0, 4900000.0)  # EPSG:2958 (NAD83(CSRS) / UTM zone 17N), 2 deg from the zone 18 edge


def _geokeys(projected=None, geographic=None, vertical_units=None):
    """A GeoTIFF key directory (LAS 1.2 tiles): model type, projected / geographic EPSG code, height unit (4099)."""
    from laspy.vlrs.known import GeoKeyDirectoryVlr, GeoKeyEntryStruct
    keys = [GeoKeyEntryStruct(1024, 0, 1, 1 if projected else 2)]
    keys += [GeoKeyEntryStruct(k, 0, 1, v)
             for k, v in ((2048, geographic), (3072, projected), (4099, vertical_units)) if v]
    d = GeoKeyDirectoryVlr()
    d.geo_keys_header.number_of_keys = len(keys)
    d.geo_keys = keys
    return d


def _tile(path, x, y, z, crs=None, frame="EPSG:6339", version="1.4", evlr=False, keys=None, cls=None, rn=None,
          scale=(0.001, 0.001, 0.001)):
    """A tile holding the points x, y, z (frame CRS, metres) stored in `crs`: coordinates projected, heights in its
    height unit. evlr: the WKT in an extended VLR at the end of the file (newer 3DEP tiles); keys: GeoTIFF keys
    instead of a WKT (LAS 1.2)."""
    import laspy
    from laspy.vlrs.known import WktCoordinateSystemVlr
    from laspy.vlrs.vlrlist import VLRList
    from pyproj import CRS, Transformer
    x, y, z = (np.asarray(v, float) for v in (x, y, z))
    if crs is not None:
        c = CRS(crs)
        hc = c.sub_crs_list[0] if c.is_compound else c
        if not hc.equals(CRS(frame), ignore_axis_order=True):
            x, y = Transformer.from_crs(frame, hc, always_xy=True).transform(x, y)
        z = z / (c.sub_crs_list[1].axis_info[0].unit_conversion_factor if c.is_compound else 1.0)
    h = laspy.LasHeader(point_format=6 if version == "1.4" else 1, version=version)
    h.offsets = [np.floor(x.min()), np.floor(y.min()), 0.0]; h.scales = list(scale)
    if keys is not None:
        h.vlrs.append(keys)
    elif crs is not None and not evlr:
        h.add_crs(CRS(crs))
    if evlr:
        h.global_encoding.wkt = True
    las = laspy.LasData(h)
    las.x, las.y, las.z = x, y, z
    las.classification = np.full(len(x), 2, np.uint8) if cls is None else np.asarray(cls, np.uint8)
    las.return_number = np.ones(len(x), np.uint8) if rn is None else np.asarray(rn, np.uint8)
    las.intensity = (np.arange(len(x)) % 200).astype(np.uint16)
    if evlr:
        las.evlrs = VLRList([WktCoordinateSystemVlr(CRS(crs).to_wkt())])
    las.write(path)
    return path


def _ground_and_trees(x0, y0):
    """Ground every 0.5 m over a 32 m square + the read margin, 0.125 m off every cell edge (so a millimetre of
    projection round trip moves no point to another cell), on a slope; first returns 6-14 m up over a quarter."""
    g = np.arange(-14.875, 47.0, 0.5)
    gx, gy = (a.ravel() for a in np.meshgrid(x0 + g, y0 + g))
    gz = 100.0 + 0.05 * (gx - x0) - 0.02 * (gy - y0)
    t = (gx > x0 + 8) & (gx < x0 + 24) & (gy > y0 + 8) & (gy < y0 + 24)
    x = np.r_[gx, gx[t]]; y = np.r_[gy, gy[t]]
    z = np.r_[gz, gz[t] + 6.0 + 8.0 * np.abs(np.sin(gx[t] * 3.1))]
    cls = np.r_[np.full(len(gx), 2), np.full(t.sum(), 1)]
    return x, y, z, cls, dict(xmin=x0, ymin=y0, xmax=x0 + 32.0, ymax=y0 + 32.0)


def _pass1(monkeypatch, tiles, frame, ext):
    import build_rasters as R
    monkeypatch.setattr(C, "CRS", frame); monkeypatch.setattr(C, "LIDAR_TILES", list(tiles))
    buckets, cnt, isum, dsm, bdsm = R.pass1(ext, 0.25)
    pts = np.concatenate([np.concatenate(v) for v in buckets.values() if v])
    key = np.round(pts[:, :2] * 10)   # the points sit 0.125 m off the 0.25 m grid: a 10 cm key survives the round trip
    return pts[np.lexsort((key[:, 1], key[:, 0]))], cnt, isum, dsm


CASES = {  # frame, the tiles' CRS, how the CRS is stored
    "state plane ftUS + NAVD88 ftUS, WKT in an EVLR": ("EPSG:6339", SAC, "EPSG:6418+6360", dict(evlr=True)),
    "state plane ftUS, GeoTIFF keys with the height unit": (
        "EPSG:6339", SAC, "EPSG:6418+6360", dict(version="1.2", keys=_geokeys(6418, vertical_units=9003))),
    "neighbouring UTM zone (GeoTIFF keys)": ("EPSG:2958", ZONE_EDGE, "EPSG:2959", dict(version="1.2")),
    "the frame with heights in ftUS": ("EPSG:6339", SAC, "EPSG:6339+6360", dict()),
}


@pytest.mark.parametrize("case", CASES, ids=list(CASES))
def test_tiles_in_another_crs_are_reprojected_into_the_frame(tmp_path, monkeypatch, capsys, case):
    """A course whose LiDAR project is in State Plane feet (Sacramento's only 3DEP project) or in the neighbouring UTM
    zone stopped at the rasters step: the rasters from the reprojected tile are those from the same points in the
    frame."""
    frame, (x0, y0), crs, how = CASES[case]
    monkeypatch.setattr(C, "VERTICAL_DATUM", None)
    x, y, z, cls, ext = _ground_and_trees(x0, y0)
    ref = _pass1(monkeypatch, [_tile(tmp_path / "frame.las", x, y, z, frame, frame=frame, cls=cls)], frame, ext)
    capsys.readouterr()
    got = _pass1(monkeypatch, [_tile(tmp_path / "other.las", x, y, z, crs, frame=frame, cls=cls, **how)], frame, ext)
    notes = [s for s in capsys.readouterr().out.splitlines() if s.startswith(("lidar:", "!! lidar:"))]
    assert np.array_equal(got[1], ref[1]) and np.array_equal(got[2], ref[2])       # ground count, intensity sum
    assert got[0].shape == ref[0].shape and np.abs(got[0] - ref[0]).max() < 0.003    # the TIN's ground points
    fin = np.isfinite(ref[3])
    assert np.array_equal(np.isfinite(got[3]), fin) and np.abs(got[3][fin] - ref[3][fin]).max() < 0.003   # DSM
    assert len(notes) == 1 and "other.las" in notes[0], notes                       # said once
    assert "reprojected" in notes[0] or "converted" in notes[0], notes


def test_tiles_in_the_frame_are_read_as_they_are(tmp_path, monkeypatch, capsys):
    """Westmount's, Brambles' and Whistle Bear's tiles name the frame (with metre heights): no transform, the header's
    box, nothing printed. Tiles naming no CRS are read as the frame, as before, and the build says so once."""
    monkeypatch.setattr(C, "CRS", "EPSG:2958"); monkeypatch.setattr(C, "VERTICAL_DATUM", "CGVD2013")
    x, y, z, cls, ext = _ground_and_trees(*ZONE_EDGE)
    ok = [_tile(tmp_path / f"{n}.las", x, y, z, c, frame="EPSG:2958", cls=cls)
          for n, c in (("plain", "EPSG:2958"), ("cgvd", "EPSG:2958+6647"))]
    for f, fr in zip(ok, C.lidar_tile_frames(ok)):
        import laspy
        with laspy.open(f) as r:
            box = (*r.header.mins[:2], *r.header.maxs[:2])
        assert fr["how"] == "frame" and fr["transform"] is None and fr["bounds"] == box
    assert C.lidar_crs_notes(C.lidar_tile_frames(ok)) == []
    bare = [_tile(tmp_path / f"bare{i}.las", x, y, z, frame="EPSG:2958", cls=cls) for i in (1, 2)]
    frames = C.lidar_tile_frames(bare)
    assert all(fr["how"] == "assumed" and fr["transform"] is None for fr in frames)
    _pass1(monkeypatch, ok, "EPSG:2958", ext)
    assert capsys.readouterr().out.count("lidar:") == 0
    _pass1(monkeypatch, bare, "EPSG:2958", ext)
    out = capsys.readouterr().out
    assert out.count("CRS not given") == 1 and "2 tiles (bare1.las, bare2.las)" in out and "[lidar] crs" in out, out


def test_tiles_are_kept_by_their_reprojected_box(tmp_path, monkeypatch):
    """The header box of a State Plane tile is in feet, millions away from the frame's numbers: the tile was dropped
    as outside the extent ('no LiDAR tile covers ...'). A tile far away stays out."""
    monkeypatch.setattr(C, "CRS", "EPSG:6339"); monkeypatch.setattr(C, "VERTICAL_DATUM", None)
    x, y, z, cls, ext = _ground_and_trees(*SAC)
    near = _tile(tmp_path / "near.las", x, y, z, "EPSG:6418+6360", cls=cls)
    far = _tile(tmp_path / "far.las", x + 5000.0, y, z, "EPSG:6418+6360", cls=cls)
    b = C.lidar_tile_frames([near])[0]["bounds"]   # the feet box turned (grid convergence): a little bigger
    assert x.min() - 3 < b[0] <= x.min() + 0.01 and y.max() - 0.01 <= b[3] < y.max() + 3
    pts, cnt, _, _ = _pass1(monkeypatch, [near, far], "EPSG:6339", ext)
    assert cnt.sum() > 0
    import build_rasters as R
    monkeypatch.setattr(C, "LIDAR_TILES", [far])
    with pytest.raises(SystemExit, match="no LiDAR tile covers"):
        R.pass1(ext, 0.25)


def test_the_crs_report_says_what_is_reprojected_and_what_is_not_checked(tmp_path, monkeypatch):
    """check_course said 'no tile names a CRS other than the frame's' for tiles whose CRS record it could not read (a
    broken WKT, GeoTIFF keys of a user-defined projection that laspy reads as lon/lat), and suggested --crs for feet
    tiles, which new_course refuses."""
    import check_course as K
    monkeypatch.setattr(C, "CRS", "EPSG:6339"); monkeypatch.setattr(C, "VERTICAL_DATUM", "NAVD88")
    x, y, z, cls, _ = _ground_and_trees(*SAC)
    from laspy.vlrs.known import WktCoordinateSystemVlr
    broken = _tile(tmp_path / "broken.las", x, y, z, cls=cls)
    import laspy
    las = laspy.read(broken); las.header.vlrs.append(WktCoordinateSystemVlr('PROJCS["x",NOPE]')); las.write(broken)
    tiles = [_tile(tmp_path / "ok.las", x, y, z, "EPSG:6339+5703", cls=cls),
             _tile(tmp_path / "feet.las", x, y, z, "EPSG:6418+6360", cls=cls, evlr=True),
             _tile(tmp_path / "bare.las", x, y, z, cls=cls), broken,
             _tile(tmp_path / "userdef.las", *_tile_xy_feet(x, y), z, version="1.2", cls=cls,
                   keys=_geokeys(32767, geographic=4269))]
    monkeypatch.setattr(C, "LIDAR_TILES", tiles)
    assert C.lidar_crs_problems(tiles) == []
    r = K.lidar_crs_report()
    line = lambda name: next(x for x in r if name in x)
    assert any("1 of 5 tiles in the course frame" in x and not x.startswith("!!") for x in r), r
    assert "California zone 2" in line("feet.las") and "reprojected" in line("feet.las") and \
        not line("feet.las").startswith("!!")
    assert "not given" in line("bare.las") and "not checked" in line("bare.las")
    for bad in ("broken.las", "userdef.las"):
        assert line(bad).startswith("!!") and "not readable" in line(bad) and "[lidar] crs" in line(bad), line(bad)
    assert not any("--crs" in x or "new_course" in x for x in r), r


def _tile_xy_feet(x, y):
    """Frame points in California zone 2 feet (a tile whose GeoTIFF keys define the projection by parameters)."""
    from pyproj import Transformer
    return Transformer.from_crs("EPSG:6339", "EPSG:6418", always_xy=True).transform(x, y)


def test_heights_on_another_datum_are_reported(tmp_path, monkeypatch):
    """The engine converts height units, not datums: NAVD88 heights for a course on CGVD2013, or ellipsoidal heights,
    are read as they are and said."""
    monkeypatch.setattr(C, "CRS", "EPSG:2958"); monkeypatch.setattr(C, "VERTICAL_DATUM", "CGVD2013")
    x, y, z, cls, _ = _ground_and_trees(*ZONE_EDGE)
    same = _tile(tmp_path / "cgvd.las", x, y, z, "EPSG:2958+6647", frame="EPSG:2958", cls=cls)
    navd = _tile(tmp_path / "navd.las", x, y, z, "EPSG:2958+5703", frame="EPSG:2958", cls=cls)
    ell = _tile(tmp_path / "ell.las", x, y, z, "EPSG:4979", frame="EPSG:2958", cls=cls, scale=(1e-7, 1e-7, 0.001))
    notes = C.lidar_crs_notes(C.lidar_tile_frames([same, navd, ell]))
    assert len(notes) == 3, notes   # navd: datum; ell: reprojected + ellipsoidal heights
    att = [t for a, t in notes if a]
    assert any("navd.las" in t and "NAVD88" in t and "CGVD2013" in t and "[scaffold] vertical" in t for t in att), att
    assert any("ell.las" in t and "ellipsoid" in t for t in att), att
    assert not any("cgvd.las" in t for _, t in notes)


def test_lidar_crs_in_course_toml_names_the_tiles_crs(tmp_path, monkeypatch):
    """Tiles whose headers name no CRS, or a wrong one: [lidar] crs gives it, and they are reprojected."""
    monkeypatch.setattr(C, "VERTICAL_DATUM", None)
    x, y, z, cls, ext = _ground_and_trees(*ZONE_EDGE)
    from pyproj import Transformer
    zx, zy = Transformer.from_crs("EPSG:2958", "EPSG:2959", always_xy=True).transform(x, y)
    bare = _tile(tmp_path / "zone18.las", zx, zy, z, frame="EPSG:2958", cls=cls)
    ref = _pass1(monkeypatch, [_tile(tmp_path / "frame.las", x, y, z, "EPSG:2958", frame="EPSG:2958", cls=cls)],
                 "EPSG:2958", ext)
    monkeypatch.setattr(C, "LIDAR_CRS", "EPSG:2959")
    assert C.lidar_tile_frames([bare])[0]["how"] == "reproject"
    got = _pass1(monkeypatch, [bare], "EPSG:2958", ext)
    assert np.array_equal(got[1], ref[1])
    monkeypatch.setattr(C, "LIDAR_CRS", "EPSG:99999999")
    with pytest.raises(SystemExit, match=r"\[lidar\] crs"):
        C.lidar_tile_frames([bare])


def test_a_tile_that_does_not_fit_its_crs_stops_the_build(tmp_path, monkeypatch):
    """Coordinates outside what the tile's CRS can project (a wrong CRS record) gave infinite boxes."""
    import build_rasters as R
    monkeypatch.setattr(C, "CRS", "EPSG:2958")
    t = _tile(tmp_path / "wrong.las", [1e9, 1e9 + 1], [1e9, 1e9 + 1], [300.0, 301.0], frame="EPSG:2958")
    import laspy
    from pyproj import CRS
    las = laspy.read(t); las.header.add_crs(CRS("EPSG:2959")); las.write(t)
    p = C.lidar_crs_problems([t])
    assert len(p) == 1 and "wrong.las" in p[0] and "[lidar] crs" in p[0] and "--crs" not in p[0], p
    monkeypatch.setattr(C, "LIDAR_TILES", [t])
    with pytest.raises(SystemExit, match="wrong.las"):
        R.pass1(dict(xmin=537000.0, ymin=4810000.0, xmax=537256.0, ymax=4810256.0), 1.0)


def test_check_course_measures_coverage_on_the_reprojected_boxes(tmp_path, monkeypatch):
    """data_report compared the header boxes (State Plane feet) with CORE (metres): 'does not cover CORE'."""
    import check_course as K
    monkeypatch.setattr(C, "CRS", "EPSG:6339"); monkeypatch.setattr(C, "VERTICAL_DATUM", None)
    monkeypatch.setattr(C, "DATA", tmp_path); (tmp_path / "lidar").mkdir()
    x, y, z, cls, ext = _ground_and_trees(*SAC)
    t = _tile(tmp_path / "lidar/feet.laz", x, y, z, "EPSG:6418+6360", cls=cls, evlr=True)
    monkeypatch.setattr(C, "LIDAR_TILES", [t]); monkeypatch.setattr(C, "FETCH_CORE", ext)
    line = next(s for s in K.data_report() if "LiDAR: 1 tile" in s)
    import re
    assert not line.startswith("!!") and abs(int(re.search(r"E (\d+)-", line).group(1)) - x.min()) < 3, line


def test_crown_statistics_read_reprojected_tiles(tmp_path, monkeypatch):
    """detect_trees reads the points for the crown bases and penetration: a tile in the neighbouring UTM zone gives
    the same crowns as the same points in the frame."""
    import detect_trees as D
    from rasterio.transform import from_origin
    import rasterio
    x0, y1 = ZONE_EDGE[0], ZONE_EDGE[1] + 40.0
    monkeypatch.setattr(C, "CRS", "EPSG:2958"); monkeypatch.setattr(C, "VERTICAL_DATUM", None)
    monkeypatch.setattr(C, "CORE", dict(xmin=x0, ymin=y1 - 40, xmax=x0 + 40, ymax=y1))
    monkeypatch.setattr(C, "BUILD", tmp_path)
    with rasterio.open(tmp_path / "dem.tif", "w", driver="GTiff", width=160, height=160, count=1, dtype="float32",
                       crs="EPSG:2958", transform=from_origin(x0, y1, 0.25, 0.25)) as d:
        d.write(np.zeros((1, 160, 160), np.float32))
    yy, xx = np.mgrid[:80, :80]
    lab = (np.hypot(yy - 40, xx - 40) * 0.5 < 4.0).astype(np.int32)
    rng = np.random.default_rng(3)
    gx, gy = (a.ravel() for a in np.meshgrid(np.arange(x0 + 0.1, x0 + 40, 0.5), np.arange(y1 - 39.9, y1, 0.5)))
    r, t = 3.0 * np.sqrt(rng.random(400)), rng.uniform(0, 2 * np.pi, 400)
    x = np.r_[gx, x0 + 20.25 + r * np.cos(t)]; y = np.r_[gy, y1 - 20.25 + r * np.sin(t)]
    z = np.r_[np.zeros(len(gx)), rng.uniform(3.0, 12.0, 400)]
    cls = np.r_[np.full(len(gx), 2), np.full(400, 1)]
    T = from_origin(x0, y1, 0.5, 0.5)
    out = []
    for name, crs in (("frame.las", "EPSG:2958"), ("zone18.las", "EPSG:2959")):
        monkeypatch.setattr(C, "LIDAR_TILES", [_tile(tmp_path / name, x, y, z, crs, frame="EPSG:2958", cls=cls)])
        out.append(D.crown_base(lab, T, 1))
    assert 3.4 < out[0][0][0] < 4.2
    assert out[1][0].tolist() == out[0][0].tolist() and out[1][1].tolist() == out[0][1].tolist()
