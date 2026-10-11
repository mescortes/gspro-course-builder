"""Backdrop DEM: a 5 km square around the course at 2 m, from NRCan CanElevation HRDEM (lidar) 1 m DTM COGs, read by
HTTP range requests and reprojected on the fly (the mosaics are in EPSG:3979, Canada Atlas Lambert) to config.CRS.

ON-Lake_Erie_2018 is the HRDEM built from the same OMAFRA 2018 point cloud as the course DEM; the City of Waterloo
2014 DTM fills any gaps. Licence: Open Government Licence - Canada. Output: data/dem/backdrop_dem.tif
"""
import sys
from pathlib import Path
import numpy as np, rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT

sys.path.insert(0, str(Path(__file__).parent)); import config as C

B = dict(xmin=C.ORIGIN_E - 2500, ymin=C.ORIGIN_N - 2500, xmax=C.ORIGIN_E + 2500, ymax=C.ORIGIN_N + 2500)
URLS = ["https://canelevation-dem.s3.ca-central-1.amazonaws.com/hrdem-lidar/ON-Lake_Erie_2018-1m-dtm.tif",
        "https://canelevation-dem.s3.ca-central-1.amazonaws.com/hrdem-lidar/VILLE_WATERLOO-VILLE_WATERLOO-1m-dtm.tif"]
RES = 2.0


def main():
    W = int((B["xmax"] - B["xmin"]) / RES); H = int((B["ymax"] - B["ymin"]) / RES)
    T = from_origin(B["xmin"], B["ymax"], RES, RES)
    out = np.full((H, W), np.nan, np.float32)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',
                      GDAL_HTTP_MULTIRANGE='YES', GDAL_HTTP_MERGE_CONSECUTIVE_RANGES='YES', VSI_CACHE='TRUE'):
        for url in URLS:
            if np.isfinite(out).all():
                break
            with rasterio.open('/vsicurl/' + url) as ds:
                # average onto the 2 m grid: read through an overview level close to 2 m, warped into the course CRS
                with WarpedVRT(ds, crs=C.CRS, transform=T, width=W, height=H, resampling=Resampling.average,
                               src_nodata=ds.nodata, nodata=np.nan, dtype="float32") as v:
                    a = v.read(1).astype(np.float32)
            a[(a < -1000) | (a > 9000)] = np.nan
            fill = np.isnan(out) & np.isfinite(a)
            out[fill] = a[fill]
            print(url.split('/')[-1], 'valid', np.isfinite(a).mean().round(3), flush=True)
    print('missing', np.isnan(out).mean())
    (C.DATA / 'dem').mkdir(parents=True, exist_ok=True)
    with rasterio.open(C.DATA / 'dem/backdrop_dem.tif', 'w', driver='GTiff', width=W, height=H, count=1, dtype='float32', crs=C.CRS,
                       transform=T, nodata=np.nan, compress='deflate', predictor=3) as d:
        d.write(out, 1)


if __name__ == "__main__":
    main()
