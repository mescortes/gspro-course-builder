"""Data providers: the point cloud, the aerial photo and the backdrop DEM of a course, chosen in course.toml:

  [sources.lidar]     provider = "nrcan_copc" (NRCan CanElevation, Canada) | "usgs_3dep" (USGS 3DEP, United States)
  [sources.imagery]   provider = "arcgis_imageserver" (Ontario SWOOP, USDA NAIP, any ArcGIS ImageServer)
  [sources.backdrop]  provider = "cog_dem" (NRCan HRDEM, USGS 3DEP 1 m DEM: cloud-optimised GeoTIFFs)

Each provider module has a fetch() taking its course.toml table (`spec`).
"""
import importlib, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1])); import config as C


def provider(kind):
    """(module, spec) for "lidar", "imagery" or "backdrop"."""
    spec = C.DATA_SOURCES.get(kind)
    if not spec:
        sys.exit(f"courses/{C.SLUG}/course.toml: no [sources.{kind}] (see scripts/sources/__init__.py)")
    return importlib.import_module(f"sources.{spec['provider']}"), spec
