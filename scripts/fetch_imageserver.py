"""Fetch orthoimagery from an ArcGIS ImageServer (exportImage), chunked to stay under the service's size / time limits,
into a GeoTIFF in config.CRS.

Default service: Ontario SWOOP 2025 (South Western Ontario Orthophotography Project; Geospatial Ontario, 16 cm, RGB + NIR,
captured March-May 2025, leaf-off, native EPSG:2958). Licence: Open Government Licence - Ontario ("Contains information
licensed under the Open Government Licence - Ontario"), so derived textures and overlays may be redistributed.

Usage: fetch_imageserver.py xmin ymin xmax ymax res out.tif [bands, e.g. 0,1,2,3]
"""
import io, json, sys, time
from pathlib import Path
import numpy as np, requests, rasterio
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).parent)); import config as C

SWOOP = "https://ws.geoservices.lrc.gov.on.ca/arcgis5/rest/services/AerialImagery/GEO_Imagery_Data_Service_2023to2027/ImageServer"
SWOOP_RULE = {"mosaicMethod": "esriMosaicNorthwest", "where": "Project='SWOOP2025'"}
UA = {"User-Agent": "westmount-course-builder/0.1 (personal research)"}


def chunks(xmin, ymin, xmax, ymax, res, chunk_px):
    """Output grid (W, H) and the request windows [(col0, row0, w, h, (x0, y0, x1, y1))] covering it exactly."""
    W = int(round((xmax - xmin) / res)); H = int(round((ymax - ymin) / res))
    out = []
    for r0 in range(0, H, chunk_px):
        for c0 in range(0, W, chunk_px):
            w = min(chunk_px, W - c0); h = min(chunk_px, H - r0)
            x0 = xmin + c0 * res; y1 = ymax - r0 * res
            out.append((c0, r0, w, h, (x0, y1 - h * res, x0 + w * res, y1)))
    return W, H, out


MAX_CHUNK_M = 800.0   # ground size of one request: the server resamples every source tile in it (coarse requests 504)


def chunk_size(res, chunk_px=2500, max_m=MAX_CHUNK_M):
    return max(64, min(chunk_px, int(max_m / res)))


def fetch(xmin, ymin, xmax, ymax, res, out, bands=(0, 1, 2), service=SWOOP, rule=SWOOP_RULE, chunk_px=2500):
    W, H, wins = chunks(xmin, ymin, xmax, ymax, res, chunk_size(res, chunk_px))
    epsg = int(C.CRS.split(":")[1])
    img = np.zeros((len(bands), H, W), np.uint8)
    for k, (c0, r0, w, h, bb) in enumerate(wins):
        params = dict(bbox=",".join(f"{v:.3f}" for v in bb), bboxSR=epsg, imageSR=epsg, size=f"{w},{h}", format="tiff",
                      pixelType="U8", bandIds=",".join(map(str, bands)), interpolation="RSP_BilinearInterpolation",
                      noData=0, f="image")
        if rule:
            params["mosaicRule"] = json.dumps(rule)
        for attempt in range(6):
            try:
                r = requests.get(service + "/exportImage", params=params, timeout=300, headers=UA)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                    with rasterio.MemoryFile(r.content) as mf, mf.open() as ds:
                        a = ds.read()
                    if a.shape[1:] != (h, w):
                        raise RuntimeError(f"chunk shape {a.shape} != {(h, w)}")
                    img[:, r0:r0 + h, c0:c0 + w] = a[:len(bands)]
                    break
                print("  bad", r.status_code, r.text[:200], flush=True)
            except (requests.RequestException, RuntimeError, rasterio.errors.RasterioIOError) as ex:
                print("  retry", attempt + 1, ex.__class__.__name__, str(ex)[:120], flush=True)
            time.sleep(5 * (attempt + 1))
        else:
            raise SystemExit(f"failed chunk {k} {bb}")
        print(f"chunk {k + 1}/{len(wins)}", flush=True)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", driver="GTiff", width=W, height=H, count=len(bands), dtype="uint8", crs=C.CRS,
                       transform=from_origin(xmin, ymax, res, res), compress="deflate", tiled=True, BIGTIFF="IF_SAFER") as d:
        d.write(img)
    print("wrote", out, img.shape)


if __name__ == "__main__":
    xmin, ymin, xmax, ymax, res = map(float, sys.argv[1:6]); dst = sys.argv[6]
    bands = tuple(int(b) for b in sys.argv[7].split(",")) if len(sys.argv) > 7 else (0, 1, 2)
    fetch(xmin, ymin, xmax, ymax, res, dst, bands)
