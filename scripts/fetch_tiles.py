"""Fetch XYZ web-mercator imagery tiles covering a bbox in config.CRS and reproject to a GeoTIFF in that CRS.
Usage: fetch_tiles.py SOURCE ZOOM xmin ymin xmax ymax res out.tif
SOURCE: esri (Esri World Imagery). Not used by the pipeline: the Esri licence does not allow exporting tiles for offline
or derived use, so the course is built from the open SWOOP 2025 imagery (fetch_imageserver.py). Kept as a quick-look tool."""
import sys, os, io, math, time, concurrent.futures as cf
import numpy as np, requests, rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin, from_bounds
from pyproj import Transformer
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

SOURCES = {
    "esri": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
}
CACHE = str(C.DATA / "imagery" / "tilecache")
R = 6378137.0
def merc_tile_bounds(x, y, z):
    n = 2 ** z; size = 2 * math.pi * R / n
    minx = -math.pi * R + x * size; maxy = math.pi * R - y * size
    return minx, maxy - size, minx + size, maxy

def get_tile(src, z, x, y):
    p = f"{CACHE}/{src}/{z}/{x}_{y}.jpg"
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return np.array(Image.open(p).convert("RGB"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    url = SOURCES[src].format(z=z, x=x, y=y)
    for a in range(5):
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0 (course-model research)"})
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                open(p, "wb").write(r.content)
                return np.array(Image.open(io.BytesIO(r.content)).convert("RGB"))
        except Exception as e:
            pass
        time.sleep(2 * (a + 1))
    raise RuntimeError(f"tile failed {z}/{x}/{y}")

def main():
    src = sys.argv[1]; z = int(sys.argv[2]); xmin, ymin, xmax, ymax, res = map(float, sys.argv[3:8]); out = sys.argv[8]
    t = Transformer.from_crs(C.CRS, "EPSG:3857", always_xy=True)
    cx, cy = t.transform([xmin, xmax, xmin, xmax], [ymin, ymin, ymax, ymax])
    mx0, mx1, my0, my1 = min(cx), max(cx), min(cy), max(cy)
    n = 2 ** z; size = 2 * math.pi * R / n
    tx0 = int((mx0 + math.pi * R) // size); tx1 = int((mx1 + math.pi * R) // size)
    ty0 = int((math.pi * R - my1) // size); ty1 = int((math.pi * R - my0) // size)
    nx, ny = tx1 - tx0 + 1, ty1 - ty0 + 1
    print(f"tiles {nx}x{ny}={nx*ny}", flush=True)
    mosaic = np.zeros((ny * 256, nx * 256, 3), np.uint8)
    jobs = {}
    with cf.ThreadPoolExecutor(8) as ex:
        for ty in range(ty0, ty1 + 1):
            for tx in range(tx0, tx1 + 1):
                jobs[ex.submit(get_tile, src, z, tx, ty)] = (tx, ty)
        done = 0
        for f in cf.as_completed(jobs):
            tx, ty = jobs[f]; a = f.result()
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = a
            done += 1
            if done % 50 == 0: print("got", done, flush=True)
    mb = merc_tile_bounds(tx0, ty0, z); me = merc_tile_bounds(tx1, ty1, z)
    src_transform = from_bounds(mb[0], me[1], me[2], mb[3], nx * 256, ny * 256)
    W = int(round((xmax - xmin) / res)); H = int(round((ymax - ymin) / res))
    dst = np.zeros((3, H, W), np.uint8)
    dst_transform = from_origin(xmin, ymax, res, res)
    for b in range(3):
        reproject(mosaic[:, :, b], dst[b], src_transform=src_transform, src_crs="EPSG:3857",
                  dst_transform=dst_transform, dst_crs=C.CRS, resampling=Resampling.lanczos)
    with rasterio.open(out, "w", driver="GTiff", width=W, height=H, count=3, dtype="uint8", crs=C.CRS,
                       transform=dst_transform, compress="deflate", tiled=True) as d:
        d.write(dst)
    print("wrote", out, dst.shape)

if __name__ == "__main__":
    main()
