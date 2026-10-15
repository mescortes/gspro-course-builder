"""Course configuration, loaded from courses/<slug>/course.toml. The course is chosen with COURSE=<slug>; it can be
left out while courses/ holds a single course.

Folders, per course:
  courses/<slug>/           tracked: course.toml, features/ (hand-made sources: overrides, structures, patios ...),
                            research/ (OSM snapshot, notes, QA verdicts)
  data/<slug>/              downloads (LiDAR, imagery, backdrop DEM, textures) and a few derived caches
  build/<slug>/             intermediate products; generated features in build/<slug>/features
  output/<slug>/            the model, the GSPro package, maps, viewer presets
MG_PROFILE=test builds the [test_profile] extent of course.toml into build/<slug>-test/ (features/, output/ inside).

World frame: the course's projected CRS (Westmount: NAD83(CSRS) / UTM zone 17N, EPSG:2958, the frame of the Ontario
LiDAR; heights CGVD2013, m). WGS84 inputs (OSM, web imagery) are projected with pyproj; the imagery is then registered
to the LiDAR empirically (measure_registration.py), which also absorbs the ~1 m WGS84 / NAD83(CSRS) difference.
Model frame (glTF, Y-up, metres): x = E - ORIGIN_E, y = H - BASE_H, z = -(N - ORIGIN_N).
"""
import json, os, re, sys, tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _slug():
    known = sorted(p.parent.name for p in (ROOT / "courses").glob("*/course.toml"))
    if not known:
        sys.exit("no course: add courses/<slug>/course.toml")
    for k in known:  # build/<slug>-test is the test profile's folder, so no slug may end in -test
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", k) or k.endswith("-test"):
            sys.exit(f"courses/{k}: a course folder name is lower-case words joined by '-', not ending in '-test'")
    slug = os.environ.get("COURSE") or None  # COURSE= (empty) is the same as unset
    if slug is None and len(known) == 1:
        return known[0]
    if slug not in known:
        sys.exit(f"{'unknown course ' + repr(slug) if slug else 'set COURSE'}: courses/ has {', '.join(known)}")
    return slug


def _holes(spec):
    """"1-9,11" or [1, 2] -> (1, ..., 9, 11)"""
    if not isinstance(spec, str):
        return tuple(spec)
    out = []
    for part in filter(None, (s.strip() for s in spec.split(","))):
        a, _, b = part.partition("-")
        out += range(int(a), int(b or a) + 1)
    return tuple(out)


SLUG = _slug()
COURSE_DIR = ROOT / "courses" / SLUG
try:
    with open(COURSE_DIR / "course.toml", "rb") as _f:  # TOML is UTF-8 whatever the locale
        _T = tomllib.load(_f)
    _course, _frame, _img, _holes_t = _T["course"], _T["frame"], _T.get("imagery", {}), _T.get("holes", {})
    for _k in ("crs", "origin", "base_h", "core", "terrain"):
        _frame[_k]
    _course["name"]
except (tomllib.TOMLDecodeError, KeyError) as _e:
    sys.exit(f"courses/{SLUG}/course.toml: {'missing ' + str(_e) if isinstance(_e, KeyError) else _e}")


def _merge(a, b):
    """b over a, key by key for nested tables."""
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


# Region preset: regions/<region>.toml (species, foliage, turf, buildings, backdrop grade ...). A course.toml table of
# the same name overrides it key by key.
REGION_NAME = _course.get("region")
REGION_TABLES = ("turf_tint", "trees", "foliage", "grass", "buildings", "backdrop", "materials", "viewer")
_region = {}
if REGION_NAME:
    try:
        with open(ROOT / "regions" / f"{REGION_NAME}.toml", "rb") as _f:
            _region = tomllib.load(_f)
    except FileNotFoundError:
        _known = sorted(p.stem for p in (ROOT / "regions").glob("*.toml"))
        sys.exit(f"courses/{SLUG}/course.toml: unknown region {REGION_NAME!r} (regions/ has {', '.join(_known) or 'none'})")
REGION = _merge({k: v for k, v in _region.items() if k in REGION_TABLES}, {k: v for k, v in _T.items() if k in REGION_TABLES})


def as_tuples(v):
    """TOML arrays back to the tuples the engine uses (recursively, through tables)."""
    if isinstance(v, list):
        return tuple(as_tuples(x) for x in v)
    return {k: as_tuples(x) for k, x in v.items()} if isinstance(v, dict) else v


TUNING, REGION_TUNING = _T.get("tuning", {}), _region.get("tuning", {})  # check_course names keys the engine never reads


def tuning(key, default):
    """A tuned limit: course.toml [tuning], else the region's [tuning], else the engine default. A TOML list for a tuple
    default comes back as a tuple, a TOML integer for a float default as a float."""
    v = TUNING.get(key, REGION_TUNING.get(key, default))
    if isinstance(default, tuple) and isinstance(v, list):
        return tuple(v)
    if isinstance(default, float) and isinstance(v, int) and not isinstance(v, bool):
        return float(v)
    return v

SOURCES = COURSE_DIR / "features"   # hand-made course features (tracked)
RESEARCH = COURSE_DIR / "research"  # OSM snapshot, notes, QA verdicts (tracked)
DATA = ROOT / "data" / SLUG
BUILD = ROOT / "build" / SLUG
FEATURES = BUILD / "features"       # generated features: auto_core, course_surfaces, trees
OUTPUT = ROOT / "output" / SLUG

COURSE_NAME = _course["name"]
COURSE_SHORT = _course.get("short", COURSE_NAME)
MODEL_NAME = _course.get("model_name", SLUG)    # output/<slug>/<MODEL_NAME>.glb, <MODEL_NAME>_noveg.glb
_unity = "".join(w.title() for w in SLUG.split("-"))  # a C# class name starts with a letter: 18-oaks -> Course18Oaks
UNITY_SCRIPT = _course.get("unity_script", ("" if _unity[:1].isalpha() else "Course") + _unity + "Setup.cs")
UNITY_NAME = UNITY_SCRIPT.removesuffix(".cs").removesuffix("Setup")  # class <UNITY_NAME>Setup, menu and Assets/<UNITY_NAME>

CRS = _frame["crs"]
CRS_LABEL = _frame.get("crs_label", CRS)
ORIGIN_E, ORIGIN_N = (float(v) for v in _frame["origin"])
BASE_H = float(_frame["base_h"])  # metres subtracted from heights in the model frame

PROFILE = os.environ.get("MG_PROFILE", "course")
CORE = dict(_frame["core"])  # build extent: every hole + >= 100 m margin, a whole number of TILEs
FETCH_CORE = dict(CORE)  # downloads cover the course extent in both profiles (data/<slug>/ is shared)
TILE = float(_frame.get("tile", 256.0))  # processing tile size (m); rasters are built tile by tile with overlap
# Unity/GSPro terrain square (2048 m gives a 4097^2 heightmap at 0.5 m) centred on CORE; cells outside CORE come from
# the backdrop DEM
TERRAIN = dict(_frame["terrain"])
FETCH_TERRAIN = dict(TERRAIN)  # in both profiles: the backdrop DEM (data/<slug>/, shared) covers its GSPro outer plot
PLAYABLE = _holes(_holes_t.get("playable", "1-18"))
_tp = _T.get("test_profile", {})
TEST_HOLES = _holes(_tp.get("holes", PLAYABLE))  # the holes the test profile covers
TEST_CORE = dict(_tp["core"]) if "core" in _tp else None  # [test_profile] core, in either profile (check_course)
if PROFILE == "test":  # small regression build ([test_profile] in course.toml), written to build/<slug>-test/
    CORE = dict(_tp.get("core", CORE))
    TERRAIN = dict(_tp.get("terrain", CORE))
    BUILD = ROOT / "build" / f"{SLUG}-test"
    FEATURES = BUILD / "features"
    OUTPUT = BUILD / "output"
for _d in (BUILD, FEATURES, OUTPUT):  # git-ignored: absent on a fresh clone
    _d.mkdir(parents=True, exist_ok=True)
DEM_RES = float(_frame.get("dem_res", 0.25))  # metres


def grid_problems(ext, res, table="frame"):
    """A DEM resolution and a build extent ([frame] or [test_profile] core) the engine cannot build, as messages. The
    DEM grid must be exactly twice as fine as the 0.5 m DSM / CHM grid: the DEM is averaged 2 x 2 onto it, and
    surface_classify, vectorize, export_course and measure_registration expand the CHM 2 x 2 back onto the DEM grid. So
    dem_res is 0.25 and each side of the extent a whole number of 0.5 m. build_rasters stops on them before the LiDAR
    pass, check_course reports them before anything is fetched. res=None checks the extent only."""
    out = []
    if res is not None and res != 0.25:
        out.append(f"[frame] dem_res = {res:g}, but the engine builds the DEM at 0.25 m only (half the 0.5 m canopy "
                   "grid): remove dem_res")
    for a, b in (("xmin", "xmax"), ("ymin", "ymax")):
        side = ext[b] - ext[a]
        if abs(side / 0.5 - round(side / 0.5)) > 1e-6:
            out.append(f"[{table}] core {a}..{b} is {side:g} m: each side of the build extent must be a whole number of "
                       "0.5 m (new_course.py writes whole tiles)")
    return out

LIDAR_TILES = sorted((DATA / "lidar").glob("*.laz"))  # the build reads them through lidar_tiles(), which checks tiles.json
_lidar = _T.get("lidar", {})
LIDAR_LEAF_OFF = bool(_lidar.get("leaf_off", False))  # deciduous crowns sparse in the CHM (detect_trees closes them)
IMAGERY_LEAF_OFF = bool(_img.get("leaf_off", False))  # ground visible through bare crowns (vectorize.py keeps it)
# The flags course.toml leaves out, which check_course flags: a missing flag reads as leaf-on, and leaf-off data then
# builds without a warning (bare crowns split into several trees, bunkers under bare branches dropped).
LEAF_OFF_UNSET = tuple(t for t, d in (("lidar", _lidar), ("imagery", _img)) if "leaf_off" not in d)

# Aerial imagery covering CORE (+20 m). The pipeline reads the registered copy written by register_imagery.py; band 4
# (NIR), when present, feeds the classifier, everything else reads bands 1-3.
IMAGERY_RAW = DATA / "imagery" / _img.get("raw", "imagery.tif")
IMAGERY_RES = float(_img.get("res", 0.16))
IMAGERY_SHIFT = tuple(float(v) for v in _img.get("shift", (0.0, 0.0)))  # metres +E/+N applied to the photo
IMAGERY = DATA / "imagery" / _img.get("registered", IMAGERY_RAW.stem + "_reg.tif")
IMAGERY_CREDIT = _img.get("credit", "")

# Turf colour of the glTF / viewer textures: the median colour of each turf surface is moved to this summer target
# (sRGB) and the photo only contributes the local variation. None = use the photo's own colours.
TURF_TINT = {k: tuple(v) for k, v in REGION["turf_tint"].items()} if "turf_tint" in REGION else None

YARDS_PER_M = 1.0 / 0.9144


# ---- course definition
SCENERY_HOLES = _holes(_holes_t.get("scenery", ()))  # holes visible from play but not played
_OSM_REF = {int(k): int(v) for k, v in _holes_t.get("osm_ref", {}).items()}  # OSM golf=hole ref -> hole, if not equal


def course_hole(osm_ref):
    """OSM golf=hole ref -> course hole number (99 = not a course hole)."""
    try:
        r = int(osm_ref)
    except (TypeError, ValueError):
        return 99
    r = _OSM_REF.get(r, r)
    return r if r in PLAYABLE or r in SCENERY_HOLES else 99


def lidar_problems():
    """What is wrong with data/<slug>/lidar against the tiles.json its last fetch wrote (scripts/sources/store.py): []
    when the folder holds exactly the listed tiles, fetched for the current [sources.lidar] and [frame] core. A folder
    fetched before tiles.json existed has none and is taken as it is."""
    folder = DATA / "lidar"
    try:
        m = json.loads((folder / "tiles.json").read_text())
    except FileNotFoundError:
        return []
    except ValueError:
        return [f"{folder / 'tiles.json'} is unreadable: rerun fetch_data.py lidar"]
    out = []
    if m.get("spec") != json.loads(json.dumps(DATA_SOURCES.get("lidar"))) or m.get("extent") != FETCH_CORE:
        out.append(f"the tiles in {folder} were fetched for another [sources.lidar] or [frame] core than "
                   f"courses/{SLUG}/course.toml's: rerun fetch_data.py lidar")
    have, listed = {p.name for p in folder.glob("*.laz")}, set(m.get("tiles", ()))
    if have - listed:
        out.append(f"{folder}: {', '.join(sorted(have - listed))} not in tiles.json (the tiles fetch_data.py lidar "
                   f"fetched): another project's? move them out of the folder, or rerun fetch_data.py lidar")
    if listed - have:
        out.append(f"{folder}: {', '.join(sorted(listed - have))} in tiles.json but missing: rerun fetch_data.py lidar")
    return out


def lidar_tiles():
    """LIDAR_TILES, or exit naming the folder: an empty folder used to build all-NaN rasters without an error, and a
    switched project's old tiles were built together with the new ones (lidar_problems)."""
    if not LIDAR_TILES:
        sys.exit(f"no lidar tiles in {DATA / 'lidar'}: run fetch_data.py lidar"
                 + (f" (or move the old data/ into data/{SLUG}/)" if (ROOT / "data" / "lidar").exists() else ""))
    problems = lidar_problems()
    if problems:
        sys.exit("lidar: " + "\nlidar: ".join(problems))
    return LIDAR_TILES


def lidar_crs_problems(tiles):
    """The tiles whose header CRS is not the course frame ([frame] crs), as messages. The engine reads LiDAR coordinates
    as they are, so tiles in State Plane feet, the neighbouring UTM zone or a national grid failed later as 'no LiDAR
    tile covers ...', which reads as a download gap. A tile whose header names no CRS is not checked."""
    import laspy
    from pyproj import CRS as _CRS
    frame = _CRS(CRS)
    bad = {}  # problem -> tile names
    for f in tiles:
        with laspy.open(f) as r:
            try:
                tc = r.header.parse_crs()
            except Exception:  # an odd or broken CRS record: nothing to compare
                tc = None
        if tc is None:
            continue
        h = tc.sub_crs_list[0] if tc.is_compound else tc
        v = tc.sub_crs_list[1] if tc.is_compound and len(tc.sub_crs_list) > 1 else None
        code = h.to_epsg()
        if not (h.equals(frame, ignore_axis_order=True) or (code is not None and code == frame.to_epsg())):
            why = (f"in {h.name!r}{f' (EPSG:{code})' if code else ''}, the course frame is {frame.name!r} ({CRS}, "
                   f"courses/{SLUG}/course.toml [frame] crs): reproject the tiles to {CRS} (e.g. pdal translate with "
                   f"filters.reprojection), or move the course to the tiles' CRS (new_course.py with --crs "
                   f"{f'EPSG:{code}' if code else '<code>'} --dry-run prints the [frame] table to copy)")
        elif v is not None and v.axis_info and v.axis_info[0].unit_conversion_factor != 1.0:
            why = (f"heights in {v.axis_info[0].unit_name} ({v.name!r}): the engine reads them as metres; convert the "
                   "tiles' heights to metres")
        else:
            continue
        bad.setdefault(why, []).append(Path(f).name)
    return [f"{len(n)} tile{'s' * (len(n) > 1)} ({', '.join(n[:3])}{', ...' * (len(n) > 3)}) {why}" for why, n in bad.items()]


LAYOUT = _course.get("layout", f"{len(PLAYABLE)} holes")
NINE = {h: n for n, spec in _holes_t.get("nines", {}).items() for h in _holes(spec)} or \
    {h: "Front" if h <= 9 else "Back" for h in PLAYABLE}

# Tee sets, back to front: (key, display name, marker colour). SCORECARD yardages follow this order.
TEES = tuple((t["key"], t["name"], t["colour"]) for t in _T.get("tees", ()))
TEE_GKD = {t["key"]: t["gkd_slot"] for t in _T.get("tees", ()) if "gkd_slot" in t}  # GreenKeeper TeeType per card tee
TEE_KEYS = tuple(k for k, _, _ in TEES)
TEE_NAMES = {k: n for k, n, _ in TEES}
TEE_COLOURS = {k: c for k, _, c in TEES}


def tee_labels(keys):
    """Marker labels: the shortest capitalised prefix of each tee key that no other tee shares (Black / Blue -> Bla, Blu)."""
    out = {}
    for k in keys:
        n = 1
        while any(o != k and o[:n] == k[:n] for o in keys) and n < len(k):
            n += 1
        out[k] = k[:n].capitalize()
    return out


TEE_LABEL = tee_labels(TEE_KEYS)  # hole summaries and QA images
# [scorecard] units: the unit of the card's distances, "yards" (the default) or "metres". The engine works in yards, so a
# metric card is converted to whole yards here (read as yards, a 400 m hole had its markers 34 m forward).
_card = dict(_T.get("scorecard", {}))
SCORECARD_UNITS = _card.pop("units", "yards")
SCORECARD_UNITS = "metres" if SCORECARD_UNITS == "meters" else SCORECARD_UNITS
if SCORECARD_UNITS not in ("yards", "metres"):
    sys.exit(f'courses/{SLUG}/course.toml: [scorecard] units = {SCORECARD_UNITS!r}: "yards" or "metres"')
SCORECARD = {int(h): tuple(v) if SCORECARD_UNITS == "yards" else (*v[:1], *(round(d * YARDS_PER_M) for d in v[1:]))
             for h, v in _card.items()}  # hole: (par, yards per tee...)
_si = _T.get("stroke_index", {})
HANDICAP = dict(zip(PLAYABLE, _si.get("men", ())))
if isinstance(_si.get("women"), str) and _si["women"] != "same":  # "same": one stroke index for everyone
    sys.exit(f'courses/{SLUG}/course.toml: [stroke_index] women = {_si["women"]!r}: a list, or "same" (the men\'s)')
HANDICAP_WOMEN = dict(HANDICAP) if _si.get("women") == "same" else dict(zip(PLAYABLE, _si.get("women", ())))
RATINGS = {t: (*r.get("men", (None, None)), *r.get("women", (None, None)), r.get("yards"))  # (men rating, slope,
           for t, r in _T.get("ratings", {}).items()}                                      # women rating, slope, yards)

# LiDAR tree archetypes (detect_trees.assign_archetypes)
TREE_ARCHETYPES = tuple(REGION.get("trees", {}).get("archetypes", ("maple", "oak", "pine", "spruce", "shrub")))
PARKING = tuple(_T.get("structures", {}).get("parking", ()))  # OSM amenity=parking ids that get parked cars
_osm = _T.get("osm", {})
_osm_ref = lambda s: (s.partition("/")[0], int(s.partition("/")[2]))   # "way/152133739" -> ("way", 152133739)
OSM_OUTLINE = tuple(_osm_ref(s) for s in _osm.get("outline", ()))  # the course's leisure=golf_course outline(s)
OSM_EXCLUDE = {_osm_ref(s) for s in _osm.get("exclude", ())}       # OSM elements left out (a disused runway ...)
DATA_SOURCES = _T.get("sources", {})  # [sources.lidar], [sources.imagery], [sources.backdrop]: scripts/sources
TESTS = _T.get("tests", {})  # limits of the built-course tests (tests/test_course.py), e.g. known_tee_gaps
DRAFT = _T.get("draft", {})  # draft_features.py thresholds (sections turf, green, tee, sand, water, outline, path)


def to_model(e, n, h):
    """UTM easting/northing/height -> glTF model coordinates (x, y, z)."""
    return (e - ORIGIN_E, h - BASE_H, -(n - ORIGIN_N))
