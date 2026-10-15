"""Backdrop DEM from cloud-optimised GeoTIFFs read by HTTP range requests and averaged onto the backdrop grid in
config.CRS (NRCan HRDEM 1 m, in EPSG:3979; USGS 3DEP 1 m DEM, in UTM). Later URLs fill gaps the earlier ones leave.

  [sources.backdrop]
  provider = "cog_dem"
  dtm = ["https://.../ON-Lake_Erie_2018-1m-dtm.tif", ...]
  dsm = ["https://.../ON-Lake_Erie_2018-1m-dsm.tif", ...]   # optional: backdrop trees and buildings
  src_crs = "EPSG:6339"   # optional: the files' real CRS when their stamp is another datum (3DEP 1 m DEMs say NAD83
                          # but come from NAD83(2011) lidar; with PROJ grids installed the warp would shift ~0.7 m)
  max_missing = 0.01      # optional: share of the backdrop square the DTMs may leave without data (a lake shore ...)

A URL answering 404 is skipped (no DSM published for a gap-filling project ...); any other failure stops the fetch. The
DTM must cover the backdrop square but for `max_missing`, and its gaps are filled from the surrounding heights (a NaN
height became a NaN backdrop vertex). The DSM is optional: its gaps stay gaps (no backdrop trees or roofs there). The
file is written to <out>.part, renamed into place and recorded in <out>.source.json (sources/store.py).
"""
import math, sys
from pathlib import Path
import numpy as np, rasterio
from rasterio.enums import Resampling
from rasterio.fill import fillnodata
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT

sys.path.insert(0, str(Path(__file__).resolve().parents[1])); import config as C
from sources import http, store

MAX_MISSING = 0.01


def urls(spec, kind):
    return list(spec.get(kind, ()))


def open_path(url):
    """GDAL path: HTTP range requests for a URL, the file itself for a local path."""
    return "/vsicurl/" + url if url.startswith(("http://", "https://")) else url


def available(url):
    """True when the file is there, False when it is not (HTTP 404, or no such local file). Any other answer (a proxy
    403, a timeout) raises RuntimeError: it used to read as 'not available' and leave the backdrop without heights."""
    if not url.startswith(("http://", "https://")):
        return Path(url).exists()
    return http.exists(url)


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
        absent = []
        for url in us:
            if np.isfinite(a_out).all():
                break
            try:
                there = available(url)
            except RuntimeError as ex:
                sys.exit(f"backdrop: {url} cannot be read ({ex}): check [sources.backdrop] {kind} in course.toml and the "
                         "network, then rerun fetch_backdrop.py")
            if not there:      # e.g. no DSM published for a gap-filling project
                print(url.split('/')[-1], 'not available', flush=True)
                absent.append(url.split('/')[-1])
                continue
            try:
                with rasterio.open(open_path(url)) as ds:
                    # average onto the grid: read through an overview level close to `res`, warped into the course CRS
                    with WarpedVRT(ds, src_crs=spec.get("src_crs") or ds.crs, crs=crs, transform=T, width=W, height=H, resampling=Resampling.average,
                                   src_nodata=ds.nodata, nodata=np.nan, dtype="float32") as v:
                        a = v.read(1).astype(np.float32)
            except rasterio.errors.RasterioIOError as ex:
                sys.exit(f"backdrop: {url} is there but GDAL cannot read it ({ex}): check [sources.backdrop] {kind} in "
                         "course.toml, then rerun fetch_backdrop.py")
            a[(a < -1000) | (a > 9000)] = np.nan
            fill = np.isnan(a_out) & np.isfinite(a)
            a_out[fill] = a[fill]
            print(url.split('/')[-1], 'valid', np.isfinite(a).mean().round(3), flush=True)
    missing = float(np.isnan(a_out).mean())
    print('missing', missing)
    if kind == "dtm" and missing:
        if missing > spec.get("max_missing", MAX_MISSING):
            sys.exit(f"backdrop: {missing:.1%} of the backdrop square (E {ext['xmin']:.0f}-{ext['xmax']:.0f} N "
                     f"{ext['ymin']:.0f}-{ext['ymax']:.0f}) has no {kind} data"
                     + (f" ({', '.join(absent)} not available)" if absent else "")
                     + f": add a DEM that covers it to [sources.backdrop] {kind} in course.toml or, if that is expected "
                     f"(open water ...), allow it with [sources.backdrop] max_missing = {math.ceil(missing * 100) / 100}")
        a_out = fillnodata(a_out, mask=np.isfinite(a_out).astype(np.uint8), max_search_distance=float(max(W, H)),
                           smoothing_iterations=0)
        if not np.isfinite(a_out).all():
            sys.exit(f"backdrop: no {kind} data at all over the backdrop square: check [sources.backdrop] {kind} in course.toml")
        print(f"filled {missing:.2%} of the {kind} from the surrounding heights", flush=True)
    with store.atomic(out) as tmp:
        with rasterio.open(tmp, 'w', driver='GTiff', width=W, height=H, count=1, dtype='float32', crs=crs,
                           transform=T, nodata=np.nan, compress='deflate', predictor=3) as d:
            d.write(a_out, 1)
    store.write_record(out, dict(provider="cog_dem", kind=kind, urls=us, src_crs=spec.get("src_crs"), extent=ext,
                                 res=res, crs=crs))
    return True
