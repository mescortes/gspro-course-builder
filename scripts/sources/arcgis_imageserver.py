"""Orthophotos from an ArcGIS ImageServer (exportImage), chunked to stay under the service's size / time limits, into a
GeoTIFF in config.CRS.

  [sources.imagery]
  provider = "arcgis_imageserver"
  url = "https://.../ImageServer"
  mosaic_rule = { mosaicMethod = "...", where = "..." }   # pins the project / year
  bands = [0, 1, 2, 3]       # band ids of R, G, B, NIR
  max_chunk_m = 800.0        # ground size of one request (the server resamples every source tile in it)
  max_empty = 0.01           # optional: share of the course photo the service may leave empty (black) before it fails

Ontario SWOOP (Geospatial Ontario, 16 cm RGB + NIR, Open Government Licence - Ontario) and USDA NAIP (60 cm or 30 cm
RGB + NIR, public domain) are both served this way.

Each chunk is kept in <out>.chunks/ until the photo is written, so a rerun after a failure fetches only the chunks still
missing (these servers can be flaky: the 5 km backdrop photo once took 84 min). The photo is written to <out>.part and
renamed into place, then recorded in <out>.source.json (sources/store.py).
"""
import json, shutil, sys, time
from pathlib import Path
import numpy as np, requests, rasterio
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parents[1])); import config as C
from sources import store
from sources.http import UA, permanent

MAX_CHUNK_M = 800.0
ATTEMPTS = 10          # per chunk; the wait doubles from 5 s up to MAX_WAIT_S (about 25 min of retries in all)
MAX_WAIT_S = 300.0


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


def request(spec, xmin, ymin, xmax, ymax, res, bands):
    """What a photo is made from, recorded next to it: a rerun compares it with course.toml (fetch_data.py)."""
    return dict(provider="arcgis_imageserver", url=spec["url"], mosaic_rule=spec.get("mosaic_rule"),
                interpolation=spec.get("interpolation", "RSP_BilinearInterpolation"), bands=list(bands), crs=C.CRS,
                bbox=[xmin, ymin, xmax, ymax], res=res)


def _decode(content, h, w, n):
    """The first `n` bands of a chunk's GeoTIFF bytes; RuntimeError when it is not the (h, w) chunk asked for."""
    with rasterio.MemoryFile(content) as mf, mf.open() as ds:
        a = ds.read()
    if a.shape[1:] != (h, w) or a.shape[0] < n:
        raise RuntimeError(f"chunk shape {a.shape} != {(n, h, w)}")
    return a[:n]


def _chunk_cache(out, key):
    """<out>.chunks/, emptied when it holds the chunks of another request (or chunking)."""
    cache = Path(out).with_name(Path(out).name + ".chunks")
    key = json.dumps(store.normal(key), sort_keys=True)
    if cache.exists() and not ((cache / "request.json").exists() and (cache / "request.json").read_text() == key):
        shutil.rmtree(cache)
    if not cache.exists():
        cache.mkdir(parents=True)
        store.write_text(cache / "request.json", key)
    return cache


def fetch(spec, xmin, ymin, xmax, ymax, res, out, bands, max_empty=None):
    """Write the `bands` (service band ids) of the extent at `res` m to the GeoTIFF `out`, and record the request. The
    fetch fails when more than `max_empty` of the photo is empty (all bands 0); None fails only a fully empty photo."""
    service, out = spec["url"], Path(out)
    px = chunk_size(res, spec.get("chunk_px", 2500), spec.get("max_chunk_m", MAX_CHUNK_M))
    W, H, wins = chunks(xmin, ymin, xmax, ymax, res, px)
    epsg = int(C.CRS.split(":")[1])
    where = (spec.get("mosaic_rule") or {}).get("where")
    if where:
        n = catalog_count(service, where, (xmin, ymin, xmax, ymax), epsg)
        if n == 0:
            raise SystemExit(f"imagery: no raster of {service} matches {where!r} over the extent")
    req = request(spec, xmin, ymin, xmax, ymax, res, bands)
    cache = _chunk_cache(out, dict(req, chunk_px=px))
    img = np.zeros((len(bands), H, W), np.uint8)
    for k, (c0, r0, w, h, bb) in enumerate(wins):
        kept = cache / f"{k}.tif"
        try:
            img[:, r0:r0 + h, c0:c0 + w] = _decode(kept.read_bytes(), h, w, len(bands))
            continue   # fetched by an earlier run
        except (FileNotFoundError, RuntimeError, rasterio.errors.RasterioIOError):
            pass
        params = dict(bbox=",".join(f"{v:.3f}" for v in bb), bboxSR=epsg, imageSR=epsg, size=f"{w},{h}", format="tiff",
                      pixelType="U8", bandIds=",".join(map(str, bands)),
                      interpolation=spec.get("interpolation", "RSP_BilinearInterpolation"), noData=0, f="image")
        if spec.get("mosaic_rule"):
            params["mosaicRule"] = json.dumps(spec["mosaic_rule"])
        for attempt in range(ATTEMPTS):
            try:
                r = requests.get(service + "/exportImage", params=params, timeout=300, headers=UA)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                    img[:, r0:r0 + h, c0:c0 + w] = _decode(r.content, h, w, len(bands))
                    store.write_bytes(kept, r.content)
                    break
                if permanent(r.status_code):
                    raise SystemExit(f"imagery: {service} answers HTTP {r.status_code} ({getattr(r, 'text', '')[:200]}): "
                                     f"check [sources.imagery] url and mosaic_rule in course.toml")
                print("  bad", r.status_code, getattr(r, "text", "")[:200], flush=True)
            except (requests.RequestException, RuntimeError, rasterio.errors.RasterioIOError) as ex:
                print("  retry", attempt + 1, ex.__class__.__name__, str(ex)[:120], flush=True)
            time.sleep(min(5.0 * 2 ** attempt, MAX_WAIT_S))
        else:
            raise SystemExit(f"imagery: chunk {k + 1}/{len(wins)} {bb} failed {ATTEMPTS} times ({service}): rerun to "
                             f"resume (the {len(list(cache.glob('*.tif')))} chunks fetched so far are kept in {cache})")
        print(f"chunk {k + 1}/{len(wins)}", flush=True)
    empty = float((img == 0).all(0).mean())
    if empty == 1.0:
        raise SystemExit(f"imagery: the service returned an empty photo for {out} (mosaic rule {spec.get('mosaic_rule')})")
    if max_empty is not None and empty > max_empty:
        raise SystemExit(f"imagery: {empty:.1%} of {out.name} is empty (no data from {service} with mosaic rule "
                         f"{spec.get('mosaic_rule')}): set a [sources.imagery] mosaic_rule that covers the course in "
                         f"course.toml, or allow it with [sources.imagery] max_empty = {np.ceil(empty * 100) / 100:.2f} "
                         f"(the chunks are kept: the rerun is quick)")
    with store.atomic(out) as tmp:
        with rasterio.open(tmp, "w", driver="GTiff", width=W, height=H, count=len(bands), dtype="uint8", crs=C.CRS,
                           transform=from_origin(xmin, ymax, res, res), compress="deflate", tiled=True, BIGTIFF="IF_SAFER") as d:
            d.write(img)
    store.write_record(out, req)
    shutil.rmtree(cache, ignore_errors=True)
    print("wrote", out, img.shape, f"{empty:.1%} empty")
