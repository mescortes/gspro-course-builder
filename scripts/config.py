"""Shared project configuration: coordinate frames, extents, resolutions.

World frame: NAD83(2011) / UTM zone 11N (EPSG:6340 ~ EPSG:26911/32611 at this accuracy), NAVD88 heights (m).
Model frame (glTF, Y-up, metres): x = E - ORIGIN_E, y = H - BASE_H, z = -(N - ORIGIN_N).
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BUILD = ROOT / "build"
FEATURES = ROOT / "features"
OUTPUT = ROOT / "output"

CRS = "EPSG:32611"
ORIGIN_E = 362650.0
ORIGIN_N = 3775300.0
BASE_H = 350.0  # metres NAVD88 subtracted from heights in the model frame

PROFILE = os.environ.get("MG_PROFILE", "course")
# Build extent: all 27 holes + ~100 m margin (UTM metres), 6 x 8 tiles of 256 m.
# (v1 was the 640 m square around North #1: xmin=362330, ymin=3774980, xmax=362970, ymax=3775620)
CORE = dict(xmin=362100.0, ymin=3774150.0, xmax=363636.0, ymax=3776198.0)
TILE = 256.0  # processing tile size (m); rasters are built tile by tile with overlap
# Unity/GSPro terrain square (2048 m, 4097^2 heightmap at 0.5 m) centred on CORE; cells outside CORE come from the backdrop DEM
TERRAIN = dict(xmin=361844.0, ymin=3774150.0, xmax=363892.0, ymax=3776198.0)
if PROFILE == "test":  # small regression build around North #1 (MG_PROFILE=test), written to build_test/
    CORE = dict(xmin=362330.0, ymin=3774980.0, xmax=362970.0, ymax=3775620.0)
    TERRAIN = dict(CORE)
    BUILD = ROOT / "build_test"
    FEATURES = BUILD / "features"
    OUTPUT = BUILD / "output"
    for _d in (BUILD, FEATURES, OUTPUT):
        _d.mkdir(parents=True, exist_ok=True)
DEM_RES = 0.25  # metres

LIDAR_TILES = sorted((DATA / "lidar").glob("*.laz"))

# Aerial imagery covering CORE (+20 m) at ~0.125 m, EPSG:32611 GeoTIFF. Esri World Imagery by default; point this at
# a NAIP mosaic (scripts/fetch_naip.py) for a fully public-domain build.
IMAGERY_RAW = DATA / "imagery" / "esri_z20_course.tif"
# Esri imagery sits 2.75 m west of the LiDAR (measure_registration.py: 123 bunkers, uniform, MAD 0.25-0.5 m);
# the pipeline reads the registered copy written by register_imagery.py
IMAGERY_SHIFT = (2.75, 0.0)
IMAGERY = DATA / "imagery" / "esri_z20_course_reg.tif"

YARDS_PER_M = 1.0 / 0.9144

# ---- course definition: GSPro course "North/South" = North nine (holes 1-9) + South nine (holes 10-18)
# OpenStreetMap numbers the 27 holes 1-9 North, 10-18 Lake, 19-27 South.
def course_hole(osm_ref):
    """OSM golf=hole ref -> course hole number (North 1-9, South 10-18, Lake 19-27 = scenery)."""
    r = int(osm_ref)
    if 1 <= r <= 9:
        return r
    if 19 <= r <= 27:
        return r - 9
    if 10 <= r <= 18:
        return r + 9
    return 99

PLAYABLE = tuple(range(1, 19))
NINE = {**{h: "North" for h in range(1, 10)}, **{h: "South" for h in range(10, 19)}, **{h: "Lake" for h in range(19, 28)}}
# Scorecard (golfingrecord.com Lake/North + South/Lake cards; Championship/Gold, Middle/Blue, Forward/White yards)
SCORECARD = {
    1: (4, 342, 323, 307),  2: (3, 189, 169, 153),  3: (4, 346, 323, 298),  4: (4, 299, 289, 266),
    5: (5, 516, 498, 467),  6: (4, 434, 408, 366),  7: (3, 172, 154, 131),  8: (4, 438, 420, 401),
    9: (5, 466, 453, 403), 10: (4, 417, 391, 366), 11: (4, 400, 387, 359), 12: (3, 174, 153, 97),
    13: (4, 365, 356, 224), 14: (5, 535, 513, 460), 15: (4, 412, 361, 326), 16: (3, 202, 190, 180),
    17: (4, 450, 430, 382), 18: (5, 562, 540, 481),
}
# Men's stroke index on the North/South card (golfingrecord N/S, offcourse.co, greenskeeper per-nine; verified 2026-10-10)
HANDICAP = dict(zip(range(1, 19), (16, 10, 6, 18, 8, 2, 14, 4, 12, 15, 1, 13, 9, 5, 11, 17, 7, 3)))
RATINGS = {  # tee: (men rating, men slope, women rating, women slope, total yards)
    "championship": (73.2, 134, 80.4, 143, 6719), "middle": (71.6, 132, 78.3, 139, 6358), "forward": (68.3, 123, 74.7, 129, 5667)}

def to_model(e, n, h):
    """UTM easting/northing/height -> glTF model coordinates (x, y, z)."""
    return (e - ORIGIN_E, h - BASE_H, -(n - ORIGIN_N))
