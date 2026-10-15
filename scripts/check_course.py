"""What a course still needs, before and after fetching: OSM coverage per hole (and its pars against the card), data
coverage and CRS, feature files outside the course CRS, gaps in course.toml and its region preset (scripts/region_spec.py).

  COURSE=<slug> check_course.py

Lines starting with '!!' need attention. OSM is read through surface_classify.osm_geoms(), so the course's own
golf.geojson, [osm] exclude and [osm] outline are applied as the build will apply them.
"""
import json, re, sys
from pathlib import Path
import numpy as np
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).parent)); import config as C
import region_spec  # noqa: E402


def osm_report(G, playable=None):
    """(rows, problems): per playable hole, its OSM / course features."""
    playable = playable or C.PLAYABLE
    lines, problems = {}, []
    for oid, t, g in G:
        if t.get("golf") == "hole" and t.get("ref") and g.geom_type == "LineString":
            h = C.course_hole(t["ref"]) if playable is C.PLAYABLE else int(t["ref"])
            if h in lines:
                problems.append(f"duplicate golf=hole ref {t['ref']} (ways {lines[h][0]} and {oid}): set [osm] outline or exclude one")
                continue
            lines[h] = (oid, t, g)
    courses = [oid for oid, t, g in G if t.get("leisure") == "golf_course" and g.geom_type in ("Polygon", "MultiPolygon")]
    if len(courses) > 1 and not C.OSM_OUTLINE:
        problems.append(f"{len(courses)} leisure=golf_course outlines in the OSM box ({', '.join(map(str, courses))}): "
                        "set [osm] outline to this course's so the others' golf features are left out")
    kinds = {k: [g for _, t, g in G if t.get("golf") == k] for k in ("green", "tee", "fairway", "bunker")}
    from surface_classify import is_water   # the water the build sees
    water = [g for _, t, g in G if is_water(t)]
    rows = []
    for h in playable:
        r = {"hole": h, "line": h in lines, "par": None, "green": False, "tee": False, "fairway": False, "bunkers": 0,
             "water": 0, "source": None}
        if h in lines:
            oid, t, g = lines[h]
            a, b = Point(g.coords[0]), Point(g.coords[-1])
            r.update(par=t.get("par"), source=t.get("source", "osm"),
                     green=any(x.distance(b) < 25 for x in kinds["green"]), tee=any(x.distance(a) < 30 for x in kinds["tee"]),
                     fairway=any(x.intersects(g) for x in kinds["fairway"]),
                     bunkers=sum(x.distance(g) < 60 for x in kinds["bunker"]), water=sum(x.distance(g) < 60 for x in water))
        for k, what in (("line", "no golf=hole line"), ("green", "no green at the end of the line"),
                        ("tee", "no tee at the start of the line")):
            if not r[k] and (k == "line" or r["line"]):
                problems.append(f"hole {h}: {what}")
        rows.append(r)
    return rows, problems


def par_problems(rows, scorecard):
    """Holes whose OSM golf=hole par differs from [scorecard]: OSM may number them differently (swapped nines, a
    renumbered course), and hole_data then puts each hole's card yardages on another hole's tees."""
    out = []
    for r in rows:
        par, card = r.get("par"), scorecard.get(r["hole"])
        if card and str(par or "").strip().isdigit() and int(par) != card[0]:
            out.append(f"hole {r['hole']}: OSM par {par}, [scorecard] par {card[0]}: if OSM numbers the holes differently, "
                       "map them in course.toml [holes] osm_ref = { <OSM ref> = <hole> }")
    return out


def _ranges(hs):
    """[1, 2, 3, 7] -> '1-3, 7'"""
    runs = []
    for h in sorted(hs):
        if runs and h == runs[-1][-1] + 1:
            runs[-1].append(h)
        else:
            runs.append([h])
    return ", ".join(f"{r[0]}-{r[-1]}" if len(r) > 1 else str(r[0]) for r in runs)


def _leaf_problems(c):
    """[lidar] / [imagery] leaf_off: missing, or not the leaf state the region's tree classifier was tuned on."""
    p = []
    what = {"lidar": ("LiDAR", "flight dates"), "imagery": ("photo", "photo date")}
    unset = getattr(c, "LEAF_OFF_UNSET", ())
    tr = (getattr(c, "REGION", None) or {}).get("trees", {})
    name = tr.get("classifier")
    prm = tr.get(name) if isinstance(tr.get(name), dict) else {}
    state = lambda off: "leaf-off" if off else "leaf-on"
    for t, have in (("lidar", getattr(c, "LIDAR_LEAF_OFF", None)), ("imagery", getattr(c, "IMAGERY_LEAF_OFF", None))):
        want = prm.get(f"{t}_leaf_off")
        tuned = (f"the tree classifier {name!r} (regions/{c.REGION_NAME}.toml [trees]) is tuned on {state(want)} "
                 f"{what[t][0]}") if isinstance(want, bool) else None
        if t in unset:
            p.append(f"[{t}] leaf_off: not set, so the {what[t][0]} is taken as leaf-on"
                     + (f" ({tuned})" if tuned and want else "") + f": set it from the {what[t][1]} (true = the "
                     "deciduous trees were bare)")
        elif tuned and have is not None and want != have:
            others = [k for k in region_spec.CLASSIFIERS if k != name]
            p.append(f"[{t}] leaf_off = {str(have).lower()}, but {tuned}: check the {what[t][1]}; if they are right, set "
                     f"course.toml [trees] classifier to one for {state(have)} data ({', '.join(others)}) with its "
                     "[trees.<classifier>] table")
    return p


def course_report(c=C):
    """Gaps in course.toml."""
    p = []
    keys, holes = c.TEE_KEYS, c.PLAYABLE
    if not c.TEES:
        p.append("no [[tees]]")
    missing = [h for h in holes if h not in c.SCORECARD]
    if missing:
        p.append(f"[scorecard]: no hole {', '.join(map(str, missing))}" if len(missing) < 4 else
                 f"[scorecard]: no holes {missing[0]}-{missing[-1]} ({len(missing)})")
    for h in holes:
        card = c.SCORECARD.get(h)
        if card is not None and len(card) != 1 + len(keys):
            p.append(f"[scorecard] hole {h}: {len(card) - 1} yardages for {len(keys)} tees")
    for name, si in (("men", c.HANDICAP), ("women", c.HANDICAP_WOMEN)):
        if sorted(si.get(h) or 0 for h in holes) != list(range(1, len(holes) + 1)):
            p.append(f"[stroke_index] {name}: the stroke index is not a permutation of 1-{len(holes)}")
    nine = getattr(c, "NINE", None)
    if nine is not None:  # hole_data reads every playable hole's nine
        loose = [h for h in holes if h not in nine]
        if loose:
            p.append(f"[holes] nines: hole {_ranges(loose)} in no nine "
                     "(list every playable hole, e.g. nines = { Front = \"1-9\", Back = \"10-18\" })")
        extra = [h for h in nine if h not in holes and h not in getattr(c, "SCENERY_HOLES", ())]
        if extra:
            p.append(f"[holes] nines: hole {_ranges(extra)} is not playable ([holes] playable)")
    slots = ("Black", "White", "Green", "Blue", "Yellow", "Red")
    for k in keys:
        if k not in c.RATINGS:
            p.append(f"[ratings]: no rating for tee {k} (an unrated tee: {k} = {{}})")
        if k not in c.TEE_GKD:
            p.append(f"[[tees]] {k}: no gkd_slot (GreenKeeper tee slot)")
        elif c.TEE_GKD[k] not in slots:
            p.append(f"[[tees]] {k}: gkd_slot {c.TEE_GKD[k]!r} is not a GreenKeeper slot ({', '.join(slots)})")
    used = list(c.TEE_GKD.values())
    for s in sorted({s for s in used if used.count(s) > 1}):
        p.append(f"[[tees]]: two tees have gkd_slot {s!r}")
    if not c.REGION_NAME:
        p.append("[course]: no region (region = the name of a regions/*.toml: trees, foliage, grass, buildings ...)")
    elif getattr(c, "REGION", None) is not None:  # the region as the course builds with it (course.toml tables merged)
        p += [f"regions/{c.REGION_NAME}.toml (or the course.toml table): {x}"
              for x in region_spec.problems(c.REGION, scaffold=False)]
    p += _leaf_problems(c)
    for kind in ("lidar", "imagery", "backdrop"):
        if not c.DATA_SOURCES.get(kind):
            p.append(f"[sources.{kind}]: missing")
            continue
        spec = c.DATA_SOURCES[kind]
        for k, v in (spec.items() if isinstance(spec, dict) else ()):  # what new_course.py could not find
            if v == "?" or (v == [] and k in ("projects", "dtm")):
                p.append(f"[sources.{kind}] {k}: {'empty' if v == [] else 'not found (?)'}: fill it in "
                         "(scripts/sources/<provider>.py says what it takes)")
    cls = getattr(c, "UNITY_NAME", None)
    if cls is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", cls + "Setup"):
        p.append(f"[course] unity_script {c.UNITY_SCRIPT!r}: class {cls}Setup is not a C# name (letters, digits and _, "
                 "not starting with a digit)")
    core, ter = getattr(c, "CORE", None), getattr(c, "TERRAIN", None)
    if core and ter and not (ter["xmin"] <= core["xmin"] and core["xmax"] <= ter["xmax"]
                             and ter["ymin"] <= core["ymin"] and core["ymax"] <= ter["ymax"]):
        p.append(f"[frame]: core {core['xmax'] - core['xmin']:.0f} x {core['ymax'] - core['ymin']:.0f} m does not fit in "
                 f"the {ter['xmax'] - ter['xmin']:.0f} x {ter['ymax'] - ter['ymin']:.0f} m terrain: the GSPro heightmap "
                 f"would cut off part of the course")
    return p


OVERLAP_SHARE = 0.1  # two LiDAR tiles whose boxes share more than this of the smaller one cover the same ground


def lidar_overlaps(names, mins, maxs):
    """'a and b' for each pair of tiles whose boxes overlap by more than OVERLAP_SHARE of the smaller box: two projects
    (or flights) over the same ground, which the rasters would merge (the DSM keeps the higher return of both years)."""
    out = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            w = min(maxs[i][0], maxs[j][0]) - max(mins[i][0], mins[j][0])
            h = min(maxs[i][1], maxs[j][1]) - max(mins[i][1], mins[j][1])
            small = min(np.prod(np.subtract(maxs[i], mins[i])), np.prod(np.subtract(maxs[j], mins[j])))
            if w > 0 and h > 0 and w * h > OVERLAP_SHARE * small:
                out.append(f"{names[i]} and {names[j]}")
    return out


def _rel(p):
    try:
        return p.relative_to(C.ROOT)
    except ValueError:
        return p


def data_report():
    """Downloads present, covering the extent, and made from what course.toml asks for."""
    import fetch_backdrop, fetch_data
    out = []
    tiles = C.LIDAR_TILES
    if not tiles:
        out.append(f"!! no LiDAR tiles in {C.DATA / 'lidar'} (fetch_data.py lidar)")
    else:
        import laspy
        mins, maxs = [], []
        for f in tiles:
            with laspy.open(f) as r:
                mins.append(r.header.mins[:2]); maxs.append(r.header.maxs[:2])
        lo, hi = np.min(mins, 0), np.max(maxs, 0)
        e = C.FETCH_CORE
        ok = lo[0] <= e["xmin"] and lo[1] <= e["ymin"] and hi[0] >= e["xmax"] and hi[1] >= e["ymax"]
        out.append(f"{'' if ok else '!! '}LiDAR: {len(tiles)} tiles, E {lo[0]:.0f}-{hi[0]:.0f} N {lo[1]:.0f}-{hi[1]:.0f}"
                   + ("" if ok else " (does not cover CORE)"))
        pairs = lidar_overlaps([f.name for f in tiles], mins, maxs)
        if pairs:
            out.append(f"!! LiDAR: {'; '.join(pairs[:5])}{' ...' if len(pairs) > 5 else ''} cover the same ground (two "
                       f"projects or flights?): keep one project's tiles in {C.DATA / 'lidar'}")
        out += ["!! LiDAR: " + x for x in C.lidar_problems()]
    import rasterio
    sq = fetch_backdrop.B
    # more than this share empty: a black strip for the photo (as fetch_data.py's limit), a hole in the backdrop for the
    # DTM (fetch_backdrop.py fills small gaps); the DSM is optional
    limit = {"photo": C.DATA_SOURCES.get("imagery", {}).get("max_empty", 0.01), "backdrop DTM": 0.0, "backdrop DSM": 1.0}
    for what, p, bands, box in (("photo", C.IMAGERY_RAW, 4, None), ("backdrop DTM", C.DATA / "dem/backdrop_dem.tif", 1, sq),
                                ("backdrop DSM", C.DATA / "dem/backdrop_dsm.tif", 1, sq)):
        if not p.exists():
            out.append(f"{'' if what == 'backdrop DSM' else '!! '}{what}: missing ({_rel(p)})")
            continue
        with rasterio.open(p) as ds:
            a = ds.read(out_shape=(ds.count, 256, 256))
            empty = float(np.isnan(a[0]).mean()) if ds.dtypes[0].startswith("float") else float((a == 0).all(0).mean())
            count, res, b = ds.count, ds.res[0], ds.bounds
        short = box is not None and (b.left > box["xmin"] + res or b.bottom > box["ymin"] + res
                                     or b.right < box["xmax"] - res or b.top < box["ymax"] - res)
        bad = count < bands or empty > limit[what] or short
        out.append(f"{'!! ' if bad else ''}{what}: {count} bands, {res:.2f} m, {empty:.1%} empty"
                   + (f" (covers E {b.left:.0f}-{b.right:.0f} N {b.bottom:.0f}-{b.top:.0f}, not the backdrop square E "
                      f"{box['xmin']:.0f}-{box['xmax']:.0f} N {box['ymin']:.0f}-{box['ymax']:.0f}: rerun fetch_backdrop.py)"
                      if short else ""))
    out += ["!! photo: " + x for x in fetch_data.imagery_problems()]
    out += ["!! OSM: " + x for x in fetch_data.osm_problems()]
    return out


def lidar_crs_report(c=C):
    """The LiDAR tiles' header CRS against the course frame: the engine reads their coordinates as course-CRS metres."""
    if not c.LIDAR_TILES:
        return []
    return [f"!! LiDAR CRS: {x}" for x in c.lidar_crs_problems(c.LIDAR_TILES)] or \
        [f"LiDAR CRS: no tile names a CRS other than the frame's ({c.CRS})"]


def photo_crs_report(c=C):
    """The raw photo's CRS against the course frame: the pipeline reads it through course-CRS windows, so a photo placed
    by hand in another CRS gave black windows (fetch_data.py imagery asks the service for the course CRS)."""
    if not Path(c.IMAGERY_RAW).exists():
        return []
    import rasterio
    from pyproj import CRS
    with rasterio.open(c.IMAGERY_RAW) as ds:
        pc = CRS(ds.crs.to_wkt()) if ds.crs else None
    frame = CRS(c.CRS)
    if pc is None or pc.equals(frame, ignore_axis_order=True) or (pc.to_epsg() or -1) == frame.to_epsg():
        return []
    return [f"!! photo CRS: {Path(c.IMAGERY_RAW).name} is in {pc.name!r}, the course frame is {c.CRS} ({frame.name}): "
            f"reproject it (gdalwarp -t_srs {c.CRS}) or fetch it again (fetch_data.py imagery)"]


def feature_files_report(c=C):
    """Hand-made feature files (courses/<slug>/features/**.geojson, research/layout.geojson) that are not in the course
    CRS, as messages. They are read as course-CRS metres: a file drawn in lon/lat (geojson.io, a QGIS layer in EPSG:4326)
    put every feature near the grid origin, and the build then had no golf labels on the course."""
    from pyproj import CRS
    from pyproj.exceptions import CRSError
    from shapely.geometry import shape
    frame = CRS(c.CRS)
    ext = [dict(c.TERRAIN)] + ([dict(c.FETCH_CORE)] if getattr(c, "FETCH_CORE", None) else [])
    near = (min(e["xmin"] for e in ext) - 1000, min(e["ymin"] for e in ext) - 1000,   # the course + 1 km, either profile
            max(e["xmax"] for e in ext) + 1000, max(e["ymax"] for e in ext) + 1000)
    files = sorted(Path(c.SOURCES).rglob("*.geojson")) + [p for p in [Path(c.RESEARCH) / "layout.geojson"] if p.exists()]
    fix = f"reproject it to {c.CRS} ({frame.name}; QGIS: Export > Save Features As, CRS {c.CRS})"
    out = []
    for f in files:
        name = f"courses/{Path(c.COURSE_DIR).name}/{f.relative_to(c.COURSE_DIR).as_posix()}"
        try:
            fc = json.load(open(f))
            b = [shape(x["geometry"]).bounds for x in fc.get("features", []) if x.get("geometry")]
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            out.append(f"{name}: not a GeoJSON feature collection ({e})")
            continue
        named = ((fc.get("crs") or {}).get("properties") or {}).get("name")
        if named:
            try:
                fcrs = CRS(named)
            except CRSError:
                out.append(f"{name}: names CRS {named!r}, which pyproj does not know: {fix}")
                continue
            if not (fcrs.equals(frame, ignore_axis_order=True) or (fcrs.to_epsg() or -1) == frame.to_epsg()):
                out.append(f"{name}: in {fcrs.name!r} ({named}), the course frame is {c.CRS}: {fix}")
                continue
        if not b:
            continue
        x0, y0 = min(v[0] for v in b), min(v[1] for v in b); x1, y1 = max(v[2] for v in b), max(v[3] for v in b)
        if max(abs(x0), abs(x1)) <= 180 and max(abs(y0), abs(y1)) <= 90:
            out.append(f"{name}: coordinates look like lon/lat ({x0:.4f}, {y0:.4f}); feature files are in the course "
                       f"CRS (metres): {fix}")
        elif x1 < near[0] or x0 > near[2] or y1 < near[1] or y0 > near[3]:
            out.append(f"{name}: E {x0:.0f}-{x1:.0f} N {y0:.0f}-{y1:.0f} is far outside the course terrain: if it was "
                       f"drawn in another CRS, {fix}")
    return out


def main():
    from surface_classify import osm_geoms
    tr = C.REGION.get("trees", {})
    print(f"course {C.SLUG}: {C.COURSE_NAME} ({C.REGION_NAME}, {C.CRS}, scorecard in {C.SCORECARD_UNITS})")
    print(f"leaf-off: LiDAR {C.LIDAR_LEAF_OFF}, photo {C.IMAGERY_LEAF_OFF}; tree classifier {tr.get('classifier')}")
    features = feature_files_report()
    if features:
        print("\n== course feature files")
        for x in features:
            print("!!", x)
    print("\n== OSM and course features (per playable hole)")
    rows, problems = osm_report(osm_geoms())
    problems += par_problems(rows, C.SCORECARD)
    print("hole  par  line green tee fairway bunkers water  source")
    for r in rows:
        y = lambda b: "yes" if b else " - "
        print(f"{r['hole']:>4}  {r['par'] or '-':>3}  {y(r['line'])}  {y(r['green'])}  {y(r['tee'])}  {y(r['fairway'])}"
              f"  {r['bunkers']:>7} {r['water']:>5}  {r['source'] or '-'}")
    for x in problems:
        print("!!", x)
    print("\n== data")
    for x in data_report() + lidar_crs_report() + photo_crs_report():
        print(x)
    print("\n== course.toml")
    for x in course_report() or ["complete"]:
        print(("!! " if x != "complete" else "") + x)


if __name__ == "__main__":
    main()
