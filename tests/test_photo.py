"""The course photo's format (surface_classify.has_nir and the photo readers): 8-bit, band 4 NIR or an alpha mask.
Synthetic GeoTIFFs only."""
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import surface_classify as S  # noqa: E402

T = from_origin(1000.0, 1100.0, 0.25, 0.25)   # the DEM grid the readers resample onto


def _photo(path, bands, dtype="uint8"):
    """A 100 m x 100 m photo at 0.5 m. A 4th band is flagged alpha, as GDAL flags it in any 4-band 8-bit GeoTIFF
    written without colour interpretations: the engine's own downloads (arcgis_imageserver) are written so."""
    from rasterio.enums import ColorInterp as CI
    with rasterio.open(path, "w", driver="GTiff", width=200, height=200, count=len(bands), dtype=dtype, crs="EPSG:2958",
                       transform=from_origin(1000.0, 1100.0, 0.5, 0.5)) as d:
        d.write(np.stack(bands).astype(dtype))
        if len(bands) == 4:
            d.colorinterp = [CI.red, CI.green, CI.blue, CI.alpha]
    return path


def _scene():
    rng = np.random.default_rng(0)
    rgb = [rng.integers(40, 200, (200, 200)) for _ in range(3)]
    return rgb, rng.integers(20, 230, (200, 200))


def test_a_4_band_photo_reads_its_nir_band(tmp_path, monkeypatch):
    """Westmount's SWOOP photo: R, G, B, NIR, the 4th band flagged alpha by GDAL. It is NIR (a full range of values)."""
    rgb, nir = _scene()
    monkeypatch.setattr(S.C, "IMAGERY", _photo(tmp_path / "p.tif", rgb + [nir]))
    assert S.has_nir() and S.read_nir_window(T, 0, 40, 0, 40).shape == (40, 40)


def test_an_rgba_photo_is_not_read_as_nir(tmp_path, monkeypatch, capsys):
    """A photo the user drops in themselves is often RGBA (a GDAL warp, a tile export): its alpha band (0 and 255 only)
    was taken as NIR, so NDVI = (255 - R) / (255 + R) everywhere and the classifier, the sand and grass rules and the
    path tracer ran on it."""
    rgb, _ = _scene()
    a = np.full((200, 200), 255); a[:, :20] = 0                                   # opaque, a transparent strip
    monkeypatch.setattr(S.C, "IMAGERY", _photo(tmp_path / "rgba.tif", rgb + [a]))
    assert not S.has_nir() and S.read_nir_window(T, 0, 40, 0, 40) is None
    assert S.feature_names() == S.NAMES_BASE
    assert "alpha" in capsys.readouterr().out
    monkeypatch.setattr(S.C, "IMAGERY", _photo(tmp_path / "rgb.tif", rgb))
    assert not S.has_nir() and S.read_imagery_window(T, 0, 40, 0, 40).shape == (3, 40, 40)


def test_crown_ndvi_is_not_taken_from_an_alpha_band(tmp_path, monkeypatch):
    """detect_trees read band 4 as NIR whenever there were 4 bands: on an RGBA photo every crown had NDVI ~0.5, which
    the leaf-off classifier reads as evergreen. Without NIR the crown NDVI is NaN (the classifiers cope)."""
    import detect_trees as D
    rgb, nir = _scene()
    monkeypatch.setattr(S.C, "CORE", dict(xmin=1000.0, ymin=1000.0, xmax=1100.0, ymax=1100.0))
    crowns = np.ones((40, 40), int)
    monkeypatch.setattr(S.C, "IMAGERY", _photo(tmp_path / "rgba.tif", rgb + [np.full((200, 200), 255)]))
    assert np.isnan(D.crown_colour(crowns, None, 1, 40, 40)[1]).all()
    monkeypatch.setattr(S.C, "IMAGERY", _photo(tmp_path / "rgbn.tif", rgb + [nir]))
    assert np.isfinite(D.crown_colour(crowns, None, 1, 40, 40)[1]).all()


def test_a_16_bit_photo_is_refused_with_the_conversion(tmp_path, monkeypatch):
    """Every reader divides by 255: a 16-bit photo gave Lab values far out of range and every colour rule failed
    silently."""
    rgb, nir = _scene()
    monkeypatch.setattr(S.C, "IMAGERY", _photo(tmp_path / "p16.tif", [b * 200 for b in rgb + [nir]], dtype="uint16"))
    with pytest.raises(SystemExit) as e:
        S.has_nir()
    # the conversion is the engine's own (the .venv has no GDAL command-line tools), on the photo the user put in
    msg = str(e.value)
    assert ".venv/bin/python scripts/photo_8bit.py" in msg and "--bands 1,2,3" in msg and "<NIR band>" in msg
    assert str(S._rel(S.C.IMAGERY_RAW)) in msg and "scripts/build_all.py register" in msg
    # `rio info --stats` gives band 1 (red) only: NIR scaled by red's maximum went past 255 and wrapped
    assert "rio info" not in msg and "--scale-ratio" not in msg
    with pytest.raises(SystemExit, match="uint16"):
        S.read_imagery_window(T, 0, 40, 0, 40)
    # a greyscale photo: no conversion helps, so none is offered
    monkeypatch.setattr(S.C, "IMAGERY", _photo(tmp_path / "grey.tif", rgb[:1]))
    with pytest.raises(SystemExit, match="1 band.*greyscale photo cannot be used") as e:
        S.has_nir()
    assert "photo_8bit" not in str(e.value) and "build_all.py register" in str(e.value)


def _photo16(path, bands, nodata=None):
    with rasterio.open(path, "w", driver="GTiff", width=200, height=200, count=len(bands), dtype="uint16",
                       crs="EPSG:2958", transform=from_origin(1000.0, 1100.0, 0.5, 0.5), nodata=nodata) as d:
        d.write(np.stack(bands).astype("uint16"))
    return path


def test_the_16_bit_conversion_scales_every_band_alike_and_never_wraps(tmp_path, monkeypatch):
    """The recipe the 16-bit stop gave scaled every band by 255 / the maximum `rio info --stats` prints, which is band
    1's (red): NIR over vegetation is brighter, went past 255 and wrapped (rio convert casts unchecked), and every
    NDVI rule then ran on it with no message. photo_8bit.py scales the bands it keeps by one ratio,
    from the largest of their values, so NDVI (a ratio of two bands) is kept, and clips what --max leaves above 255."""
    import photo_8bit as P8
    rng = np.random.default_rng(1)
    red, green, blue = (rng.integers(100, 2000, (200, 200)) for _ in range(3))
    nir = rng.integers(1000, 4000, (200, 200)); nir[50, 50] = 4000
    pan = rng.integers(0, 60000, (200, 200))                     # a 5th band that is not kept: not in the ratio
    red[:10, :10] = green[:10, :10] = blue[:10, :10] = nir[:10, :10] = pan[:10, :10] = 65535   # no data
    src = _photo16(tmp_path / "p16.tif", [red, green, blue, nir, pan], nodata=65535)
    out = tmp_path / "p8.tif"
    P8.main([str(src), str(out), "--bands", "1,2,3,4"])
    with rasterio.open(out) as d, rasterio.open(src) as s:
        a = d.read().astype(float)
        assert d.dtypes == ("uint8",) * 4 and d.crs == s.crs and d.transform == s.transform
    k = slice(10, None)
    assert np.abs(a[3][k, k] - nir[k, k] * 255 / 4000).max() <= 0.5 and a[3].max() == 255
    assert np.abs(a[0][k, k] - red[k, k] * 255 / 4000).max() <= 0.5      # the same ratio for red as for NIR
    assert (a[:, :10, :10] == 0).all()                                    # no data: 0, as an empty pixel
    ndvi = lambda n, r: (n - r) / (n + r)
    assert np.abs(ndvi(a[3][k, k], a[0][k, k]) - ndvi(nir[k, k], red[k, k])).max() < 0.02
    monkeypatch.setattr(S.C, "IMAGERY", out)
    assert S.has_nir()                                                    # the engine reads it, NIR included
    P8.main([str(src), str(out), "--bands", "1,2,3,4", "--max", "3000"])   # a sensor's range below the photo's
    with rasterio.open(out) as d:
        b = d.read(4).astype(float)
    hi = nir[k, k] > 3000
    assert (b[k, k][hi] == 255).all() and np.abs(b[k, k][~hi] - nir[k, k][~hi] * 255 / 3000).max() <= 0.5
    with pytest.raises(SystemExit, match="band 6"):                       # a band the photo does not have
        P8.main([str(src), str(out), "--bands", "1,2,3,6"])
