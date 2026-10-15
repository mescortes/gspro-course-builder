"""Aligned crops (imagery / intensity / hillshade / CHM) of a UTM window for visual inspection."""
import sys, numpy as np, rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from PIL import Image, ImageDraw
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent)); import config as C


def hillshade(z, res, az=315, alt=35):
    """Lambertian hillshade (0..1) of a DEM array with cell size `res` m; sun azimuth / altitude in degrees."""
    z = np.where(np.isfinite(z), z, np.nanmean(z))
    gy, gx = np.gradient(z, res)
    slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy)
    a, b = np.radians(az), np.radians(alt)
    return np.clip(np.sin(b) * np.cos(slope) + np.cos(b) * np.sin(slope) * np.cos(a - aspect), 0, 1)

def crop(path, b, res, bands=None):
    with rasterio.open(path) as ds:
        w = from_bounds(*b, transform=ds.transform)
        W = int(round((b[2]-b[0])/res)); H = int(round((b[3]-b[1])/res))
        a = ds.read(bands, window=w, out_shape=((len(bands),) if isinstance(bands, list) else ()) + (H, W), resampling=Resampling.bilinear)
    return a

def norm(a, lo, hi):
    return (np.clip((np.nan_to_num(a, nan=lo)-lo)/(hi-lo), 0, 1)*255).astype(np.uint8)

def grid(im, b, res, step=25):
    d = ImageDraw.Draw(im)
    for x in np.arange(np.ceil(b[0]/step)*step, b[2], step):
        px = (x-b[0])/res; d.line([(px,0),(px,im.height)], fill=(255,0,0) if x%100==0 else (255,120,120), width=1)
        d.text((px+2, 2), f"{int(x)%1000}", fill=(255,255,0))
    for y in np.arange(np.ceil(b[1]/step)*step, b[3], step):
        py = (b[3]-y)/res; d.line([(0,py),(im.width,py)], fill=(255,0,0) if y%100==0 else (255,120,120), width=1)
        d.text((2, py+2), f"{int(y)%1000}", fill=(255,255,0))
    return im

if __name__ == '__main__':
    b = tuple(map(float, sys.argv[1:5])); res = float(sys.argv[5]); tag = sys.argv[6]
    img = crop(C.IMAGERY, b, res, [1,2,3])
    grid(Image.fromarray(np.moveaxis(img,0,-1)), b, res).save(C.BUILD / f'crop_{tag}_img.png')
    it = crop(C.BUILD/'intensity.tif', b, res, 1)
    grid(Image.fromarray(norm(it, *np.nanpercentile(it,[2,98]))).convert('RGB'), b, res).save(C.BUILD / f'crop_{tag}_int.png')
    dem = crop(C.BUILD/'dem.tif', b, res, 1)
    grid(Image.fromarray(norm(hillshade(dem, res, 315, 35), 0.2, 1)).convert('RGB'), b, res).save(C.BUILD / f'crop_{tag}_hs.png')
    print(tag, img.shape)
