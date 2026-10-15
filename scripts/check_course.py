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
    return p


def data_report():
    """Downloads present and covering the extent."""
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
    import rasterio
    for what, p, bands in (("photo", C.IMAGERY_RAW, 4), ("backdrop DTM", C.DATA / "dem/backdrop_dem.tif", 1),
                           ("backdrop DSM", C.DATA / "dem/backdrop_dsm.tif", 1)):
        if not p.exists():
            out.append(f"{'' if what == 'backdrop DSM' else '!! '}{what}: missing ({p.relative_to(C.ROOT)})")
            continue
        with rasterio.open(p) as ds:
            nan = float(np.isnan(ds.read(1, out_shape=(1, 256, 256)).astype(float)).mean()) if ds.dtypes[0].startswith("float") else 0.0
            out.append(f"{'!! ' if ds.count < bands else ''}{what}: {ds.count} bands, {ds.res[0]:.2f} m, {nan:.1%} empty")
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
