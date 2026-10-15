"""Orthophotos from an ArcGIS ImageServer (exportImage), chunked to stay under the service's size / time limits, into a
GeoTIFF in config.CRS.

  [sources.imagery]
  provider = "arcgis_imageserver"
  url = "https://.../ImageServer"
  mosaic_rule = { mosaicMethod = "...", where = "..." }   # pins the project / year
  bands = [0, 1, 2, 3]       # band ids of R, G, B, NIR
  max_chunk_m = 800.0        # ground size of one request (the server resamples every source tile in it)

Ontario SWOOP (Geospatial Ontario, 16 cm RGB + NIR, Open Government Licence - Ontario) and USDA NAIP (60 cm or 30 cm
RGB + NIR, public domain) are both served this way.
"""
import json, sys, time
from pathlib import Path
import numpy as np, requests, rasterio
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parents[1])); import config as C
from sources.http import UA

MAX_CHUNK_M = 800.0


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


def chunk_size(res, chunk_px=2500, max_m=MAX_CHUNK_M):
    return max(64, min(chunk_px, int(max_m / res)))


def catalog_count(service, where, bbox, epsg):
    """Rasters of the service matching `where` over the box (None when the catalog does not answer)."""
    params = dict(where=where, geometry=",".join(f"{v:.3f}" for v in bbox), geometryType="esriGeometryEnvelope",
                  inSR=epsg, spatialRel="esriSpatialRelIntersects", returnCountOnly="true", f="json")
    try:
        r = requests.get(service + "/query", params=params, timeout=120, headers=UA)
        return int(r.json()["count"])
    except (requests.RequestException, ValueError, KeyError, TypeError):
        print("  catalog query failed: fetching anyway", flush=True)
        return None


def fetch(spec, xmin, ymin, xmax, ymax, res, out, bands):
    """Write the `bands` (service band ids) of the extent at `res` m to the GeoTIFF `out`."""
    service = spec["url"]
    W, H, wins = chunks(xmin, ymin, xmax, ymax, res, chunk_size(res, spec.get("chunk_px", 2500), spec.get("max_chunk_m", MAX_CHUNK_M)))
    epsg = int(C.CRS.split(":")[1])
    where = (spec.get("mosaic_rule") or {}).get("where")
    if where:
        n = catalog_count(service, where, (xmin, ymin, xmax, ymax), epsg)
        if n == 0:
            raise SystemExit(f"imagery: no raster of {service} matches {where!r} over the extent")
    img = np.zeros((len(bands), H, W), np.uint8)
    for k, (c0, r0, w, h, bb) in enumerate(wins):
        params = dict(bbox=",".join(f"{v:.3f}" for v in bb), bboxSR=epsg, imageSR=epsg, size=f"{w},{h}", format="tiff",
                      pixelType="U8", bandIds=",".join(map(str, bands)),
                      interpolation=spec.get("interpolation", "RSP_BilinearInterpolation"), noData=0, f="image")
        if spec.get("mosaic_rule"):
            params["mosaicRule"] = json.dumps(spec["mosaic_rule"])
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
                print("  bad", r.status_code, getattr(r, "text", "")[:200], flush=True)
            except (requests.RequestException, RuntimeError, rasterio.errors.RasterioIOError) as ex:
                print("  retry", attempt + 1, ex.__class__.__name__, str(ex)[:120], flush=True)
            time.sleep(5 * (attempt + 1))
        else:
            raise SystemExit(f"failed chunk {k} {bb}")
        print(f"chunk {k + 1}/{len(wins)}", flush=True)
    empty = float((img == 0).all(0).mean())
    if empty == 1.0:
        raise SystemExit(f"imagery: the service returned an empty photo for {out} (mosaic rule {spec.get('mosaic_rule')})")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", driver="GTiff", width=W, height=H, count=len(bands), dtype="uint8", crs=C.CRS,
                       transform=from_origin(xmin, ymax, res, res), compress="deflate", tiled=True, BIGTIFF="IF_SAFER") as d:
        d.write(img)
    print("wrote", out, img.shape, f"{empty:.1%} empty")
