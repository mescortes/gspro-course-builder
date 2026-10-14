"""Backdrop DEM: a 5 km square around the course at 2 m from the course's [sources.backdrop] provider (cloud-optimised
GeoTIFFs read by HTTP range requests, reprojected to config.CRS). Output: data/<slug>/dem/backdrop_dem.tif and, when the
course lists one, the matching surface model (DSM: trees, roofs) data/<slug>/dem/backdrop_dsm.tif for the backdrop
trees and buildings (backdrop_objects.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); import config as C
import sources

B = dict(xmin=C.ORIGIN_E - 2500, ymin=C.ORIGIN_N - 2500, xmax=C.ORIGIN_E + 2500, ymax=C.ORIGIN_N + 2500)
RES = 2.0


def main():
    mod, spec = sources.provider("backdrop")
    mod.fetch(spec, "dtm", B, RES, C.DATA / "dem" / "backdrop_dem.tif")
    mod.fetch(spec, "dsm", B, RES, C.DATA / "dem" / "backdrop_dsm.tif")


if __name__ == "__main__":
    main()
