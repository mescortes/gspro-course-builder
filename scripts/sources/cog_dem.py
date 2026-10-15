"""Backdrop DEM from cloud-optimised GeoTIFFs read by HTTP range requests and averaged onto the backdrop grid in
config.CRS (NRCan HRDEM 1 m, in EPSG:3979; USGS 3DEP 1 m DEM, in UTM). Later URLs fill gaps the earlier ones leave.

  [sources.backdrop]
  provider = "cog_dem"
  dtm = ["https://.../ON-Lake_Erie_2018-1m-dtm.tif", ...]
  dsm = ["https://.../ON-Lake_Erie_2018-1m-dsm.tif", ...]   # optional: backdrop trees and buildings
  src_crs = "EPSG:6339"   # optional: the files' real CRS when their stamp is another datum (3DEP 1 m DEMs say NAD83
                          # but come from NAD83(2011) lidar; with PROJ grids installed the warp would shift ~0.7 m)
"""
import sys
from pathlib import Path
import numpy as np, rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT

sys.path.insert(0, str(Path(__file__).resolve().parents[1])); import config as C


def urls(spec, kind):
    return list(spec.get(kind, ()))


def open_path(url):
    """GDAL path: HTTP range requests for a URL, the file itself for a local path."""
    return "/vsicurl/" + url if url.startswith(("http://", "https://")) else url


def fetch(spec, kind, ext, res, out, crs=None):
    """The `kind` ("dtm" or "dsm") surface over `ext` at `res` m into the GeoTIFF `out`; False when the course file
    lists no source for it."""
    us = urls(spec, kind)
    if not us:
        print(f"backdrop: no {kind} source", flush=True)
        return False
    W = int((ext["xmax"] - ext["xmin"]) / res); H = int((ext["ymax"] - ext["ymin"]) / res)
    T = from_origin(ext["xmin"], ext["ymax"], res, res)
    crs = crs or C.CRS
    a_out = np.full((H, W), np.nan, np.float32)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',
                      GDAL_HTTP_MULTIRANGE='YES', GDAL_HTTP_MERGE_CONSECUTIVE_RANGES='YES', VSI_CACHE='TRUE',
                      GDAL_HTTP_MAX_RETRY='5', GDAL_HTTP_RETRY_DELAY='1'):
        for url in us:
            if np.isfinite(a_out).all():
                break
            try:
                rasterio.open(open_path(url)).close()
            except rasterio.errors.RasterioIOError:      # e.g. no DSM published for a gap-filling project
                print(url.split('/')[-1], 'not available', flush=True)
                continue
            with rasterio.open(open_path(url)) as ds:
                # average onto the grid: read through an overview level close to `res`, warped into the course CRS
                with WarpedVRT(ds, src_crs=spec.get("src_crs") or ds.crs, crs=crs, transform=T, width=W, height=H, resampling=Resampling.average,
                               src_nodata=ds.nodata, nodata=np.nan, dtype="float32") as v:
                    a = v.read(1).astype(np.float32)
            a[(a < -1000) | (a > 9000)] = np.nan
            fill = np.isnan(a_out) & np.isfinite(a)
            a_out[fill] = a[fill]
            print(url.split('/')[-1], 'valid', np.isfinite(a).mean().round(3), flush=True)
    print('missing', np.isnan(a_out).mean())
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, 'w', driver='GTiff', width=W, height=H, count=1, dtype='float32', crs=crs,
                       transform=T, nodata=np.nan, compress='deflate', predictor=3) as d:
        d.write(a_out, 1)
    return True
