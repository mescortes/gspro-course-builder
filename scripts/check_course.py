"""What a course still needs, before and after fetching: OSM coverage per hole, data coverage, gaps in course.toml.

  COURSE=<slug> check_course.py

Lines starting with '!!' need attention. OSM is read through surface_classify.osm_geoms(), so the course's own
golf.geojson, [osm] exclude and [osm] outline are applied as the build will apply them.
"""
import sys
from pathlib import Path
import numpy as np
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).parent)); import config as C


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
    water = [g for _, t, g in G if t.get("golf") in ("water_hazard", "lateral_water_hazard") or t.get("natural") == "water"]
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
    slots = ("Black", "White", "Green", "Blue", "Yellow", "Red")
    for k in keys:
        if k not in c.RATINGS:
            p.append(f"[ratings]: no rating for tee {k}")
        if k not in c.TEE_GKD:
            p.append(f"[[tees]] {k}: no gkd_slot (GreenKeeper tee slot)")
        elif c.TEE_GKD[k] not in slots:
            p.append(f"[[tees]] {k}: gkd_slot {c.TEE_GKD[k]!r} is not a GreenKeeper slot ({', '.join(slots)})")
    used = list(c.TEE_GKD.values())
    for s in sorted({s for s in used if used.count(s) > 1}):
        p.append(f"[[tees]]: two tees have gkd_slot {s!r}")
    if not c.REGION_NAME:
        p.append("[course]: no region")
    for kind in ("lidar", "imagery", "backdrop"):
        if not c.DATA_SOURCES.get(kind):
            p.append(f"[sources.{kind}]: missing")
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


def main():
    from surface_classify import osm_geoms
    print(f"course {C.SLUG}: {C.COURSE_NAME} ({C.REGION_NAME}, {C.CRS})")
    print("\n== OSM and course features (per playable hole)")
    rows, problems = osm_report(osm_geoms())
    print("hole  par  line green tee fairway bunkers water  source")
    for r in rows:
        y = lambda b: "yes" if b else " - "
        print(f"{r['hole']:>4}  {r['par'] or '-':>3}  {y(r['line'])}  {y(r['green'])}  {y(r['tee'])}  {y(r['fairway'])}"
              f"  {r['bunkers']:>7} {r['water']:>5}  {r['source'] or '-'}")
    for x in problems:
        print("!!", x)
    print("\n== data")
    for x in data_report():
        print(x)
    print("\n== course.toml")
    for x in course_report() or ["complete"]:
        print(("!! " if x != "complete" else "") + x)


if __name__ == "__main__":
    main()
