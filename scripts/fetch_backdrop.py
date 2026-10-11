"""Backdrop data: USGS 1 m DEM (COG range reads, 2 m overview) + Esri imagery for a 5 km square around the hole."""
import sys, numpy as np, rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from rasterio.transform import from_origin
sys.path.insert(0, 'scripts'); import config as C
import subprocess
B = dict(xmin=C.ORIGIN_E - 2500, ymin=C.ORIGIN_N - 2500, xmax=C.ORIGIN_E + 2500, ymax=C.ORIGIN_N + 2500)
URLS = ["https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/CA_2025LosAngelesPostWildfire_C25/TIFF/USGS_1M_11_x36y378_CA_2025LosAngelesPostWildfire_C25.tif",
        "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/CA_LosAngeles_B23/TIFF/USGS_1M_11_x36y378_CA_LosAngeles_B23.tif"]
RES = 2.0
W = int((B["xmax"] - B["xmin"]) / RES); H = int((B["ymax"] - B["ymin"]) / RES)
out = np.full((H, W), np.nan, np.float32)
with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif', GDAL_HTTP_MULTIRANGE='YES'):
    for url in URLS:
        with rasterio.open('/vsicurl/' + url) as ds:
            w = from_bounds(B["xmin"], B["ymin"], B["xmax"], B["ymax"], transform=ds.transform)
            a = ds.read(1, window=w, out_shape=(H, W), resampling=Resampling.average, boundless=True, fill_value=ds.nodata).astype(np.float32)
            a[a < -1000] = np.nan
            fill = np.isnan(out) & np.isfinite(a)
            out[fill] = a[fill]
            print(url.split('/')[-1], 'valid', np.isfinite(a).mean().round(3))
print('missing', np.isnan(out).mean())
with rasterio.open(C.DATA / 'dem/backdrop_dem.tif', 'w', driver='GTiff', width=W, height=H, count=1, dtype='float32', crs=C.CRS,
                   transform=from_origin(B["xmin"], B["ymax"], RES, RES), nodata=np.nan, compress='deflate', predictor=3) as d:
    d.write(out, 1)
