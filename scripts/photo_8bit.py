"""An 8-bit copy of a 16-bit (or floating-point) photo, which the engine reads: every reader scales 0-255 to 0-1.

  .venv/bin/python scripts/photo_8bit.py <in.tif> <out.tif> --bands 1,2,3[,<NIR band>] [--max <value>]

The bands kept (R, G, B, then NIR if the photo has one) are scaled by one ratio, 255 / the largest value among them
(--max <value>: the sensor's range instead, e.g. 4095 for 12-bit data), so NDVI, a ratio of NIR and red, is kept.
Values above 255 are clipped, never wrapped; pixels without data become 0 (an empty pixel). One ratio for all bands
matters: NIR over vegetation is several times brighter than red, and a ratio from red's maximum alone pushed it past
255, where an unchecked cast wraps it to a small number.
"""
import argparse, sys

import numpy as np
import rasterio
from rasterio.windows import Window

ROWS = 512   # rows per block: a 12 500 px wide 4-band photo is about 50 MB of 16-bit values per block


def blocks(ds):
    for r0 in range(0, ds.height, ROWS):
        yield Window(0, r0, ds.width, min(ROWS, ds.height - r0))


def convert(src, dst, bands, vmax=None):
    """Write the `bands` (1-based) of the GeoTIFF `src` as 8-bit `dst`, scaled by 255 / `vmax` (default: the largest
    value of those bands, pixels without data left out). Returns the `vmax` used."""
    from pathlib import Path
    if Path(src).resolve() == Path(dst).resolve():
        sys.exit(f"photo_8bit: {dst} is the photo it reads: move the original elsewhere and write the 8-bit copy in "
                 "its place")
    with rasterio.open(src) as ds:
        missing =[b for b in bands if not 1 <= b <= ds.count]
        if missing:
            sys.exit(f"photo_8bit: {src} has {ds.count} band(s), no band {', '.join(map(str, missing))}: --bands lists "
                     "the photo's R, G, B (and NIR) band numbers, 1 to its band count")
        if vmax is None:
            vmax = 0.0
            for w in blocks(ds):
                a = ds.read(bands, window=w, masked=True)
                if a.count():
                    vmax = max(vmax, float(a.max()))
        if not vmax > 0:
            sys.exit(f"photo_8bit: bands {', '.join(map(str, bands))} of {src} hold no value above 0: nothing to scale")
        prof = dict(driver="GTiff", width=ds.width, height=ds.height, count=len(bands), dtype="uint8", crs=ds.crs,
                    transform=ds.transform, compress="deflate", BIGTIFF="IF_SAFER")
        with rasterio.open(dst, "w", **prof) as out:
            for w in blocks(ds):
                a = ds.read(bands, window=w, masked=True).astype(np.float64)
                q = np.clip(np.round(a.filled(0) * (255.0 / vmax)), 0, 255).astype(np.uint8)
                out.write(q, window=w)
        print(f"photo_8bit: bands {', '.join(map(str, bands))} of {src} ({ds.dtypes[0]}) x 255 / {vmax:g} -> {dst} "
              "(uint8)", flush=True)
    return vmax


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src", help="the photo as delivered (16-bit or floating point)")
    ap.add_argument("dst", help="the 8-bit photo to write")
    ap.add_argument("--bands", required=True,
                    help="band numbers to keep, in the order R,G,B[,NIR] (e.g. 1,2,3,4); see the photo's metadata")
    ap.add_argument("--max", type=float, default=None,
                    help="the value that becomes 255 (default: the largest value of the bands kept)")
    a = ap.parse_args(argv)
    try:
        bands = [int(b) for b in a.bands.split(",")]
    except ValueError:
        sys.exit(f"photo_8bit: --bands {a.bands!r}: band numbers separated by commas, e.g. --bands 1,2,3,4")
    if len(bands) not in (3, 4):
        sys.exit(f"photo_8bit: --bands {a.bands}: the engine reads R, G, B or R, G, B, NIR (3 or 4 bands)")
    convert(a.src, a.dst, bands, a.max)


if __name__ == "__main__":
    main()
