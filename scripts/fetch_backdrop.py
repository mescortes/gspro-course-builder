"""Backdrop DEM: the backdrop square (build_backdrop.FAR: 5 km around the course, more when the GSPro outer plot of a
wide terrain needs it) at 2 m from the course's [sources.backdrop] provider (cloud-optimised GeoTIFFs read by HTTP range
requests, reprojected to config.CRS). Output: data/<slug>/dem/backdrop_dem.tif and, when the course lists one, the
matching surface model (DSM: trees, roofs) data/<slug>/dem/backdrop_dsm.tif for the backdrop trees and buildings
(backdrop_objects.py).

[sources.backdrop] z_offset = <m> (optional) is added to both: for a backdrop DEM on another vertical datum than the
point cloud, which build_backdrop.check_datum measures round the course. The offset added is recorded in each file
(GeoTIFF tag build_backdrop.Z_OFFSET_TAG), so that check_datum can tell a DEM fetched before z_offset changed.
"""
import sys
from pathlib import Path

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).parent)); import config as C
import sources
from build_backdrop import FAR as B, Z_OFFSET_TAG, applied_z_offset

RES = 2.0


def shift(path, dz):
    """Add `dz` m to every height of the GeoTIFF `path` (no-data stays no-data), and record the offset the file now
    carries in its Z_OFFSET_TAG (written after the heights: a file left without it reads as not moved, and
    check_datum then asks for a refetch)."""
    total = applied_z_offset(path) + dz
    with rasterio.open(path, "r+") as ds:
        z = ds.read(1)
        ds.write(np.where(np.isfinite(z), z + dz, z).astype(z.dtype), 1)
        ds.update_tags(**{Z_OFFSET_TAG: repr(total)})
    print(f"{Path(path).name}: z_offset {dz:+.2f} m added", flush=True)


def main():
    mod, spec = sources.provider("backdrop")
    for kind, name in (("dtm", "backdrop_dem.tif"), ("dsm", "backdrop_dsm.tif")):
        out = C.DATA / "dem" / name
        if mod.fetch(spec, kind, B, RES, out) and spec.get("z_offset"):
            shift(out, float(spec["z_offset"]))


if __name__ == "__main__":
    main()
