"""Unit tests for the backdrop (build_backdrop, fetch_backdrop): the photo grading, a photo without NIR, the square it
covers and the backdrop DEM's datum. Synthetic pixels and rasters only, no network."""
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from skimage.color import rgb2lab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_backdrop as B  # noqa: E402
import config as C  # noqa: E402
import export_gspro as X  # noqa: E402
import fetch_backdrop as FB  # noqa: E402
import sources  # noqa: E402


def _scene(rng):
    """Left half: a grey-brown dormant lawn / leaf-off wood (NDVI 0.25-0.4). Right half: road and roofs (NDVI ~0)."""
    a = np.zeros((40, 80, 3), np.uint8); ndvi = np.zeros((40, 80), np.float32)
    a[:, :40] = np.clip(np.array([128, 116, 92]) + rng.normal(0, 9, (40, 40, 3)), 0, 255).astype(np.uint8)
    ndvi[:, :40] = rng.uniform(0.25, 0.4, (40, 40))
    a[:, 40:] = np.clip(np.array([118, 116, 112]) + rng.normal(0, 6, (40, 40, 3)), 0, 255).astype(np.uint8)
    ndvi[:, 40:] = rng.uniform(-0.05, 0.03, (40, 40))
    return a, ndvi


def test_summer_grade_greens_vegetation_and_keeps_its_texture():
    """The spring photo drapes the backdrop in grey-brown dormant lawns and bare trees (a pale 'desert' horizon in the
    viewer and the GSPro outer plot). Vegetated pixels (by NDVI) move to a summer green; their texture stays."""
    a, ndvi = _scene(np.random.default_rng(0))
    out = B.summer_grade(a, ndvi)
    lab0, lab1 = rgb2lab(a[:, :40] / 255.0), rgb2lab(out[:, :40] / 255.0)
    assert np.median(lab0[..., 1]) > 0 and np.median(lab1[..., 1]) < -12          # brown -> green
    assert np.median(lab1[..., 2]) > 10                                              # yellow-green, not cyan
    ratio = lab1[..., 0].std() / lab0[..., 0].std()
    assert 0.7 < ratio < 1.3                                                         # brightness texture kept


def test_summer_grade_leaves_pavement_and_roofs_alone():
    a, ndvi = _scene(np.random.default_rng(1))
    out = B.summer_grade(a, ndvi)
    assert np.abs(out[:, 40:].astype(int) - a[:, 40:].astype(int)).max() <= 1


def test_summer_tif_sits_beside_the_backdrop_image():
    """export_gspro's outer overlay and build_backdrop.imagery both locate the graded photo through summer_tif."""
    p = B.NEAR_IMG
    assert B.summer_tif(p) == p.with_name(p.stem + "_summer.tif")


# ---- backdrop photos: a photo service without NIR, and the cached grade
class _Service:
    """An ImageServer stand-in: writes the asked service bands (R, G, B, NIR = 0, 1, 2, 3) of a synthetic scene, left
    half lawn (NIR bright), right half road (NIR dark). Asking for no band is what the real service turns into an
    'empty photo' error."""
    def __init__(self):
        self.asked = []

    def fetch(self, spec, xmin, ymin, xmax, ymax, res, out, bands):
        self.asked.append((Path(out).name, tuple(bands)))
        if not bands:
            raise SystemExit(f"imagery: the service returned an empty photo for {out}")
        W, H = int(round((xmax - xmin) / res)), int(round((ymax - ymin) / res))
        rng = np.random.default_rng(0)
        img = np.zeros((4, H, W), np.uint8)
        img[:3, :, :W // 2] = np.clip(np.array([128, 116, 92])[:, None, None] + rng.normal(0, 9, (3, H, W // 2)), 1, 255)
        img[:3, :, W // 2:] = np.clip(np.array([118, 116, 112])[:, None, None] + rng.normal(0, 6, (3, H, W - W // 2)), 1, 255)
        img[3, :, :W // 2], img[3, :, W // 2:] = 200, 110
        with rasterio.open(out, "w", driver="GTiff", width=W, height=H, count=len(bands), dtype="uint8", crs=C.CRS,
                           transform=from_origin(xmin, ymax, res, res)) as d:
            d.write(img[list(bands)])


EXT = dict(xmin=537000.0, ymin=4810000.0, xmax=537040.0, ymax=4810020.0)


def _rgb(p):
    with rasterio.open(p) as ds:
        return ds.read()


def test_a_photo_without_nir_still_gets_its_backdrop_photos(tmp_path, monkeypatch, capsys):
    """An RGB-only photo service ([sources.imagery] bands = [0, 1, 2]) made the backdrop step ask the service for zero
    bands and stop with 'the service returned an empty photo'. Without NIR there is no NDVI to grade by: the backdrop
    keeps the photo's own colours, and the build says so once."""
    svc = _Service()
    monkeypatch.setattr(sources, "provider", lambda kind: (svc, {"provider": "fake", "bands": [0, 1, 2]}))
    monkeypatch.setattr(B, "_NOTED", set(), raising=False)   # notes already printed in this process
    near, far = tmp_path / "backdrop_near_x.jpg", tmp_path / "backdrop_far_x.jpg"
    B.imagery(EXT, 0.5, near)
    B.imagery(EXT, 1.0, far)
    assert svc.asked == [("backdrop_near_x.tif", (0, 1, 2)), ("backdrop_far_x.tif", (0, 1, 2))]
    for p in (near, far):
        assert p.exists() and p.with_name(p.stem + "_raw.jpg").exists() and not p.with_name(p.stem + "_nir.tif").exists()
        assert np.array_equal(_rgb(B.summer_tif(p)), _rgb(p.with_suffix(".tif")))    # ungraded
    out = capsys.readouterr().out
    assert out.count("NIR") == 1 and "bands" in out


def test_the_backdrop_photos_are_regraded_when_the_grade_changes(tmp_path, monkeypatch):
    """The graded photos were reused whenever they were newer than the photo and build_backdrop.py: a new region or
    course [backdrop] grade (summer_grade, summer_green, ndvi) had no effect until the files were deleted by hand."""
    svc = _Service()
    monkeypatch.setattr(sources, "provider", lambda kind: (svc, {"provider": "fake", "bands": [0, 1, 2, 3]}))
    p = tmp_path / "backdrop_near_x.jpg"
    monkeypatch.setitem(B._GRADE, "summer_grade", True)
    B.imagery(EXT, 0.5, p)
    assert [b for _, b in svc.asked] == [(0, 1, 2), (3,)]
    graded, t0 = _rgb(B.summer_tif(p)), B.summer_tif(p).stat().st_mtime_ns
    assert not np.array_equal(graded, _rgb(p.with_suffix(".tif")))
    B.imagery(EXT, 0.5, p)                                                # nothing changed: reused, nothing refetched
    assert B.summer_tif(p).stat().st_mtime_ns == t0 and len(svc.asked) == 2
    monkeypatch.setitem(B._GRADE, "summer_grade", False)
    B.imagery(EXT, 0.5, p)
    assert np.array_equal(_rgb(B.summer_tif(p)), _rgb(p.with_suffix(".tif"))) and len(svc.asked) == 2


# ---- the backdrop square: it must reach past the GSPro outer plot (twice the terrain) and the near ring
def _inside(a, b, margin=0.0):
    return (b["xmin"] + margin <= a["xmin"] and a["xmax"] <= b["xmax"] - margin
            and b["ymin"] + margin <= a["ymin"] and a["ymax"] <= b["ymax"] - margin)


def test_westmount_keeps_its_5_km_backdrop_square():
    """The backdrop DEM, the far photo and the far ring stay ORIGIN +/- 2500 m: Westmount's 2048 m terrain fits."""
    five = dict(xmin=C.ORIGIN_E - 2500, ymin=C.ORIGIN_N - 2500, xmax=C.ORIGIN_E + 2500, ymax=C.ORIGIN_N + 2500)
    assert B.FAR == five and FB.B == five and B.far_extent() == five
    assert B.FAR_IMG.name == "backdrop_far_535000_4808350_540000_4813350.jpg"
    assert _inside(X.outer_extent(), B.FAR, 100.0) and _inside(B.NEAR, B.FAR, 100.0)


def test_a_wide_terrain_gets_a_backdrop_past_its_outer_plot(monkeypatch):
    """A 3072 m terrain (a course over 2 km wide) has a +/- 3072 m outer plot: the fixed 5 km backdrop left a ~570 m band
    of it as smeared edge heights under a black overlay, and a core over ~3.7 km put the near ring outside the far one."""
    core = dict(xmin=535800.0, ymin=4809300.0, xmax=539200.0, ymax=4812300.0)      # 3.4 km x 3 km
    te = dict(xmin=535964.0, ymin=4809264.0, xmax=539036.0, ymax=4812336.0)        # 3072 m
    for k, v in (("CORE", core), ("FETCH_CORE", core), ("TERRAIN", te), ("FETCH_TERRAIN", te)):
        monkeypatch.setattr(B.C, k, v)
    far = B.far_extent()
    assert _inside(X.outer_extent(te), far, 50.0) and _inside(B.near_extent(core), far, 50.0)
    assert far["xmax"] - C.ORIGIN_E == C.ORIGIN_E - far["xmin"] and far["xmax"] - C.ORIGIN_E == far["ymax"] - C.ORIGIN_N
    assert (far["xmax"] - far["xmin"]) % 200 == 0                                 # whole 100 m: tidy photo names
    # the test profile (a small core and terrain) reads the course profile's backdrop DEM (data/<slug>/ is shared)
    small = dict(xmin=537300.0, ymin=4810700.0, xmax=537940.0, ymax=4811340.0)
    monkeypatch.setattr(B.C, "CORE", small); monkeypatch.setattr(B.C, "TERRAIN", small)
    assert B.far_extent() == far


def _dem(path, x0, y1, res, z, crs=None):
    with rasterio.open(path, "w", driver="GTiff", width=z.shape[1], height=z.shape[0], count=1, dtype="float32",
                       crs=crs or C.CRS, transform=from_origin(x0, y1, res, res), nodata=np.nan) as d:
        d.write(z.astype(np.float32), 1)


def test_a_backdrop_dem_smaller_than_the_outer_plot_stops_the_export(tmp_path, monkeypatch):
    """sample() repeats the DEM's edge heights past its border: an outer plot wider than the backdrop DEM got flat
    smeared bands with no message. It now stops and says to refetch the backdrop."""
    te = dict(xmin=1000.0, ymin=1000.0, xmax=1200.0, ymax=1200.0)                  # outer plot 900..1300
    monkeypatch.setattr(X, "TE", te); monkeypatch.setattr(X, "SIZE", 200.0); monkeypatch.setattr(X, "OUT", tmp_path / "gspro")
    monkeypatch.setattr(X.C, "DATA", tmp_path); (tmp_path / "dem").mkdir(); (tmp_path / "gspro").mkdir()
    _dem(tmp_path / "dem/backdrop_dem.tif", 920.0, 1280.0, 2.0, np.full((180, 180), 50.0))   # 920..1280: too small
    with pytest.raises(SystemExit, match="fetch_backdrop"):
        X.outer_terrain(n=33, px=32)
    _dem(tmp_path / "dem/backdrop_dem.tif", 800.0, 1400.0, 2.0, np.full((300, 300), 50.0))
    meta = X.outer_terrain(n=33, px=32)
    assert meta["resolution"] == 33 and (tmp_path / "gspro/outer_heightmap_33.raw").exists()


def test_a_backdrop_dem_on_another_vertical_datum_is_reported(tmp_path, capsys):
    """A backdrop DEM on another vertical datum (ellipsoidal vs orthometric heights, an old national datum, feet) made a
    wall or a berm all round the course, and nothing said why. The two DEMs are compared just inside the build extent."""
    core = dict(xmin=1000.0, ymin=2000.0, xmax=1200.0, ymax=2200.0)
    x = 1000.0 + (np.arange(800) + 0.5) * 0.25
    _dem(tmp_path / "dem_final.tif", 1000.0, 2200.0, 0.25, np.tile(300.0 + 0.05 * (x - 1000.0), (800, 1)))
    xb = 900.0 + (np.arange(200) + 0.5) * 2.0
    for dz in (0.0, 1.0, 31.4):
        _dem(tmp_path / f"bd{dz}.tif", 900.0, 2300.0, 2.0, np.tile(300.0 + 0.05 * (xb - 1000.0) + dz, (200, 1)))
    med, mad, n = B.datum_offset(tmp_path / "dem_final.tif", tmp_path / "bd0.0.tif", core)
    assert abs(med) < 0.02 and mad < 0.02 and n > 1000
    B.check_datum(tmp_path / "dem_final.tif", tmp_path / "bd0.0.tif", core)
    assert "!!" not in capsys.readouterr().out
    B.check_datum(tmp_path / "dem_final.tif", tmp_path / "bd1.0.tif", core)       # warned, not stopped
    assert "!!" in capsys.readouterr().out
    with pytest.raises(SystemExit, match=r"\[sources.backdrop\] z_offset"):
        B.check_datum(tmp_path / "dem_final.tif", tmp_path / "bd31.4.tif", core)


def test_z_offset_moves_the_backdrop_dems_onto_the_lidar_datum(tmp_path, monkeypatch):
    """[sources.backdrop] z_offset (m) is added to the downloaded DTM and DSM; without it they are written as fetched."""
    got = []

    class Dem:
        @staticmethod
        def fetch(spec, kind, ext, res, out):
            got.append((kind, dict(ext), res))
            z = np.full((4, 4), 100.0); z[0, 0] = np.nan
            _dem(out, ext["xmin"], ext["ymax"], res, z)
            return True
    monkeypatch.setattr(FB.C, "DATA", tmp_path); (tmp_path / "dem").mkdir()
    for spec, want in (({"provider": "fake"}, 100.0), ({"provider": "fake", "z_offset": -30.5}, 69.5)):
        monkeypatch.setattr(FB.sources, "provider", lambda kind, s=spec: (Dem, s))
        FB.main()
        for name in ("backdrop_dem.tif", "backdrop_dsm.tif"):
            with rasterio.open(tmp_path / "dem" / name) as ds:
                z = ds.read(1)
            assert np.isnan(z[0, 0]) and np.all(z.ravel()[1:] == want), (spec, name)
    assert got[0] == ("dtm", B.FAR, FB.RES) and got[1][0] == "dsm"
