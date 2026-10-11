"""Shared project configuration: coordinate frames, extents, resolutions, course definition.

World frame: NAD83(CSRS) / UTM zone 17N (EPSG:2958), the frame of the Ontario LiDAR; heights CGVD2013 (m).
WGS84 inputs (OSM, web imagery) are projected with pyproj; the imagery is then registered to the LiDAR empirically
(measure_registration.py), which also absorbs the ~1 m WGS84 / NAD83(CSRS) difference.
Model frame (glTF, Y-up, metres): x = E - ORIGIN_E, y = H - BASE_H, z = -(N - ORIGIN_N).
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BUILD = ROOT / "build"
FEATURES = ROOT / "features"
OUTPUT = ROOT / "output"

COURSE_NAME = "Westmount Golf & Country Club"
COURSE_SHORT = "Westmount G&CC"
LAYOUT = "18 holes"
MODEL_NAME = "westmount"          # output/<MODEL_NAME>.glb, output/<MODEL_NAME>_noveg.glb
UNITY_SCRIPT = "WestmountSetup.cs"

CRS = "EPSG:2958"
CRS_LABEL = "NAD83(CSRS) / UTM zone 17N (EPSG:2958); heights CGVD2013 (m)"
ORIGIN_E = 537500.0
ORIGIN_N = 4810850.0
BASE_H = 345.0  # metres CGVD2013 subtracted from heights in the model frame

PROFILE = os.environ.get("MG_PROFILE", "course")
# Build extent: all 18 holes (OSM course outline E 536898-538156, N 4810400-4811320) + >= 100 m margin, 6 x 5 tiles of 256 m.
CORE = dict(xmin=536760.0, ymin=4810220.0, xmax=538296.0, ymax=4811500.0)
TILE = 256.0  # processing tile size (m); rasters are built tile by tile with overlap
# Unity/GSPro terrain square (2048 m, 4097^2 heightmap at 0.5 m) centred on CORE; cells outside CORE come from the backdrop DEM
TERRAIN = dict(xmin=536504.0, ymin=4809836.0, xmax=538552.0, ymax=4811884.0)
if PROFILE == "test":  # small regression build around holes 1-2 (MG_PROFILE=test), written to build_test/
    CORE = dict(xmin=537340.0, ymin=4810720.0, xmax=537980.0, ymax=4811360.0)
    TERRAIN = dict(CORE)
    BUILD = ROOT / "build_test"
    FEATURES = BUILD / "features"
    OUTPUT = BUILD / "output"
    for _d in (BUILD, FEATURES, OUTPUT):
        _d.mkdir(parents=True, exist_ok=True)
DEM_RES = 0.25  # metres

LIDAR_TILES = sorted((DATA / "lidar").glob("*.laz"))
LIDAR_LEAF_OFF = True   # March 2018 flights: deciduous crowns are sparse in the CHM (detect_trees.py closes them)
IMAGERY_LEAF_OFF = True  # spring photo: the ground is visible through the bare crowns (vectorize.py keeps it)

# Aerial imagery covering CORE (+20 m): Ontario SWOOP 2025, 0.16 m, 4 bands (R, G, B, NIR), native EPSG:2958, Open
# Government Licence - Ontario (scripts/fetch_imageserver.py). The pipeline reads the registered copy written by
# register_imagery.py; band 4 (NIR) feeds the classifier, everything else reads bands 1-3.
IMAGERY_RAW = DATA / "imagery" / "swoop2025_course.tif"
IMAGERY_RES = 0.16
# SWOOP 2025 vs the 2018 LiDAR (measure_registration.py, 59 bunkers: photo sand vs LiDAR hollows): dx 0.00 m, dy -0.25 m,
# MAD 0.25 m, uniform over the course (north/south/east/west halves agree); OSM buildings within 0.5 m
IMAGERY_SHIFT = (0.0, -0.25)  # metres +E/+N applied to the photo
IMAGERY = DATA / "imagery" / "swoop2025_course_reg.tif"
IMAGERY_CREDIT = "Contains information licensed under the Open Government Licence - Ontario (SWOOP 2025 orthoimagery)"

# Turf colour of the glTF / viewer textures: the spring photo shows dormant, hazy turf (greens straw-coloured), so the
# median colour of each turf surface is moved to a summer target (sRGB) and the photo only contributes the local
# variation (mowing, wear, shade). None = use the photo's own colours. GSPro assigns its own turf materials by name.
TURF_TINT = {"green": (96, 138, 62), "fringe": (88, 130, 56), "fairway": (86, 128, 54), "tee": (90, 132, 58),
             "semirough": (78, 116, 50), "rough": (72, 108, 46)}

YARDS_PER_M = 1.0 / 0.9144


# ---- course definition: OSM golf=hole refs 1-18 are the course holes (verified against the scorecard pars)
def course_hole(osm_ref):
    """OSM golf=hole ref -> course hole number (99 = not a course hole)."""
    try:
        r = int(osm_ref)
    except (TypeError, ValueError):
        return 99
    return r if 1 <= r <= 18 else 99


PLAYABLE = tuple(range(1, 19))
SCENERY_HOLES = ()  # holes visible from play but not played (none at Westmount)
NINE = {**{h: "Front" for h in range(1, 10)}, **{h: "Back" for h in range(10, 19)}}

# Tee sets, back to front: (key, display name, marker colour). SCORECARD yardages follow this order. The club's
# combination sets (Blue/White, White/Red, Red/Gold) reuse these boxes hole by hole and need no geometry of their own.
TEES = (("blue", "Blue", "#2a52be"), ("white", "White", "#f5f5f5"), ("red", "Red", "#c8102e"), ("gold", "Gold", "#d4a017"))
TEE_KEYS = tuple(k for k, _, _ in TEES)
TEE_NAMES = {k: n for k, n, _ in TEES}
TEE_COLOURS = {k: c for k, _, c in TEES}
# Scorecard: Golf Canada Score Centre (course 20954), live 2026-10-11 = the 2025-07 card (new back tees on 5 and 11 in
# 2024, hole 8 lengthened in 2025). Cross-checked against the club's 2024 card, Golf Ontario and Wayback captures
# (research/NOTES.md). (par, Blue, White, Red, Gold)
SCORECARD = {
    1: (5, 559, 535, 514, 433),  2: (4, 373, 357, 335, 286),  3: (3, 195, 179, 165, 160),  4: (4, 412, 385, 365, 323),
    5: (5, 605, 568, 527, 455),  6: (3, 202, 180, 163, 133),  7: (5, 541, 503, 483, 449),  8: (4, 305, 275, 260, 245),
    9: (4, 401, 373, 346, 334), 10: (4, 334, 319, 304, 217), 11: (5, 580, 540, 502, 451), 12: (3, 141, 127, 108, 93),
    13: (5, 554, 520, 503, 439), 14: (4, 375, 359, 318, 293), 15: (4, 453, 396, 367, 315), 16: (4, 439, 418, 400, 359),
    17: (3, 165, 149, 132, 113), 18: (4, 384, 367, 351, 334),
}
# Men's stroke index (Golf Canada 2026 allocation)
HANDICAP = dict(zip(range(1, 19), (7, 13, 9, 1, 3, 15, 11, 17, 5, 12, 6, 18, 8, 10, 2, 4, 16, 14)))
HANDICAP_WOMEN = dict(zip(range(1, 19), (3, 11, 15, 9, 1, 17, 5, 13, 7, 14, 6, 18, 8, 12, 2, 4, 16, 10)))
RATINGS = {  # tee: (men rating, men slope, women rating, women slope, total yards) - Golf Canada, re-rated late 2024
    "blue": (73.0, 132, None, None, 7018), "white": (71.1, 129, 76.9, 135, 6550),
    "red": (69.3, 121, 75.1, 130, 6143), "gold": (66.3, 113, 71.3, 121, 5432)}


# LiDAR tree archetypes (detect_trees.assign_archetypes): Southern Ontario parkland species groups
#   maple  sugar / silver / Norway maple, basswood: dense rounded deciduous crowns
#   oak    red / bur oak, honey locust, ash: broad, more open, irregular crowns
#   pine   eastern white pine (+ Scots / red pine): tall, open, layered, high crown base
#   spruce Norway / white / blue spruce, cedar: dense narrow cones with branches to the ground
#   shrub  under 4.5 m
TREE_ARCHETYPES = ("maple", "oak", "pine", "spruce", "shrub")


def to_model(e, n, h):
    """UTM easting/northing/height -> glTF model coordinates (x, y, z)."""
    return (e - ORIGIN_E, h - BASE_H, -(n - ORIGIN_N))
