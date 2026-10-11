"""Fetch USGS NAIP Plus orthoimagery (public domain) for the AOI in UTM 11N, tiled to avoid gateway timeouts."""
import sys, os, time, io
import numpy as np, requests, rasterio
from rasterio.transform import from_origin
from PIL import Image

SERVICE = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer/exportImage"
def fetch(xmin, ymin, xmax, ymax, res, out, chunk_px=800):
    W = int(round((xmax - xmin) / res)); H = int(round((ymax - ymin) / res))
    img = np.zeros((H, W, 3), np.uint8)
    cm = chunk_px * res
    ny = int(np.ceil(H / chunk_px)); nx = int(np.ceil(W / chunk_px))
    for j in range(ny):
        for i in range(nx):
            x0 = xmin + i * cm; x1 = min(xmax, x0 + cm)
            y1 = ymax - j * cm; y0 = max(ymin, y1 - cm)
            w = int(round((x1 - x0) / res)); h = int(round((y1 - y0) / res))
            params = dict(bbox=f"{x0},{y0},{x1},{y1}", bboxSR=32611, imageSR=32611, size=f"{w},{h}",
                          format="png", pixelType="U8", interpolation="RSP_BilinearInterpolation", f="image", bandIds="0,1,2")
            for attempt in range(6):
                try:
                    r = requests.get(SERVICE, params=params, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
                    if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                        a = np.array(Image.open(io.BytesIO(r.content)).convert("RGB"))
                        img[j*chunk_px:j*chunk_px+a.shape[0], i*chunk_px:i*chunk_px+a.shape[1]] = a[:h, :w]
                        break
                    print("bad", r.status_code, r.text[:200]); time.sleep(3)
                except Exception as e:
                    print("err", e); time.sleep(3)
            else:
                raise SystemExit(f"failed chunk {i},{j}")
            print(f"chunk {j*nx+i+1}/{nx*ny}", flush=True)
    with rasterio.open(out, "w", driver="GTiff", width=W, height=H, count=3, dtype="uint8", crs="EPSG:32611",
                       transform=from_origin(xmin, ymax, res, res), compress="deflate") as dst:
        for b in range(3): dst.write(img[:, :, b], b + 1)
    print("wrote", out, img.shape)

if __name__ == "__main__":
    xmin, ymin, xmax, ymax, res = map(float, sys.argv[1:6]); out = sys.argv[6]
    fetch(xmin, ymin, xmax, ymax, res, out)
