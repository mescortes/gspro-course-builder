"""Register the aerial imagery to the LiDAR: a pure translation measured by measure_registration.py
(bunker sand in the photo vs LiDAR bunker hollows; uniform over the course, MAD 0.25-0.5 m).

Writes data/imagery/<name>_reg.tif: same pixels, geotransform shifted by config.IMAGERY_SHIFT (metres, +E/+N).
"""
import sys, shutil
import rasterio
from rasterio.transform import Affine
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C


def main():
    src = C.IMAGERY_RAW; dst = C.IMAGERY
    if dst.exists() and dst.stat().st_mtime > src.stat().st_mtime:
        with rasterio.open(dst) as d, rasterio.open(src) as s:
            if abs(d.transform.c - s.transform.c - C.IMAGERY_SHIFT[0]) < 1e-6 and abs(d.transform.f - s.transform.f - C.IMAGERY_SHIFT[1]) < 1e-6:
                print("imagery already registered"); return
    shutil.copyfile(src, dst)
    with rasterio.open(dst, "r+") as d:
        t = d.transform
        d.transform = Affine(t.a, t.b, t.c + C.IMAGERY_SHIFT[0], t.d, t.e, t.f + C.IMAGERY_SHIFT[1])
    print("registered imagery ->", dst, "shift", C.IMAGERY_SHIFT)


if __name__ == "__main__":
    main()
