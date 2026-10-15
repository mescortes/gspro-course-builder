"""What a region preset (regions/<name>.toml) must hold: the tables and keys the engine reads, and the script that reads
each. A missing one used to fail as a bare KeyError at import, part-way through a build (the tree classifier's only
after every LiDAR tile). check_course.py lists a course's gaps with problems(), tests/test_scaffold.py runs it over
every regions/*.toml, and new_course.py checks the [scaffold] table before it writes a course.
regions/TEMPLATE.toml.example is a commented template.

Importing this module loads no course: new_course.py runs before the course exists.
"""
import string

# (table, keys, reader). A course.toml table of the same name overrides the region's key by key (config.REGION).
TABLES = (
    ("trees", ("archetypes", "classifier", "bark", "shapes", "backdrop"), "detect_trees, make_trees, add_vegetation"),
    ("trees.backdrop", ("kinds", "share", "crown"), "backdrop_objects (backdrop billboards)"),
    ("buildings", ("wall_palette", "roof_palette", "parking_stall", "suv_share"), "add_structures, backdrop_objects"),
    ("backdrop", ("summer_grade", "summer_green", "ndvi"), "build_backdrop (photo grade of the 5 km backdrop)"),
    ("materials", ("deeprough", "native"), "export_course, fetch_textures (Poly Haven ground sets)"),
    ("grass", ("3dg", "viewer"), "grass_spec (3D grass hand-off and viewer preview)"),
)
# make_trees: the keys of each [trees.shapes.<archetype>] (clumps, clump_sd, leader, droop, tip_depth are optional)
SHAPE_KEYS = ("H", "R", "crown", "trunk", "attract", "seg", "infl", "kill", "tropism", "tip_r", "exp", "cards", "card",
              "lean", "nsides", "up_bias", "trunk_r")
# make_foliage: the keys of each [foliage.<archetype>] (src = "" for an archetype drawn as needles, [trees] needles)
FOLIAGE_KEYS = ("src", "hsv", "n", "scale", "twig", "alt")
NEEDLE_STYLES = ("pine", "spruce")
# detect_trees.CLASSIFIERS: the parameters each classifier reads from [trees.<classifier>] and the names it gives
# (its [trees.<classifier>] names maps each to an archetype). Optional there: lidar_leaf_off / imagery_leaf_off, the
# leaf state of the data the rules were tuned on (check_course compares them with the course's [lidar] / [imagery]
# leaf_off).
CLASSIFIERS = {
    "leaf_off_parkland": (("shrub_h", "conifer_pen", "conifer_green", "pine_base", "pine_tall", "oak_pct", "oak_min_h",
                           "oak_default"), ("shrub", "pine", "conifer", "broad", "other")),
    "leaf_on_woodland": (("shrub_h", "pine_min_h", "pine_max_ratio", "pine_min_pen", "big_h"),
                         ("shrub", "pine", "big", "other")),
}
# new_course.py: [scaffold] keys (crs is optional: an EPSG code, or a CRS name with {zone} / {hemisphere} for a
# datum whose UTM zones EPSG names otherwise, e.g. "GDA2020 / MGA zone {zone}")
SCAFFOLD_KEYS = ("datum", "vertical", "imagery_res", "lidar_leaf_off", "imagery_leaf_off", "lidar", "backdrop", "imagery")
# new_course.discover_sources: what its search for a [scaffold] lidar provider reads besides the provider, as
# (table, key, what it is, the {fields} of a URL pattern)
SCAFFOLD_SEARCH_KEYS = {
    "nrcan_copc": (("lidar", "province", "the province or territory folder of NRCan's point clouds, "
                    "pointclouds_nuagespoints/<province>/", ()),
                   ("backdrop", "url", "the 1 m DTM file URL of a LiDAR project", ("province", "project", "kind"))),
}


def _get(r, path):
    for k in path.split("."):
        r = r.get(k) if isinstance(r, dict) else None
    return r


def scaffold_problems(region):
    """What new_course.py needs from [scaffold] and is missing, as messages."""
    sc = region.get("scaffold")
    if not isinstance(sc, dict):
        return ["no [scaffold] table (new_course.py reads the datum, providers and photo resolution from it)"]
    out = [f"[scaffold] {k}: missing" for k in SCAFFOLD_KEYS if k not in sc]
    out += [f"[scaffold] {k}: no provider" for k in ("lidar", "backdrop", "imagery")
            if isinstance(sc.get(k), dict) and "provider" not in sc[k]]
    out += [f"[scaffold] {k}: true or false (the usual leaf state of the region's data), not {sc[k]!r}"
            for k in ("lidar_leaf_off", "imagery_leaf_off") if k in sc and not isinstance(sc[k], bool)]
    provider = sc.get("lidar", {}).get("provider") if isinstance(sc.get("lidar"), dict) else None
    for table, key, what, fields in SCAFFOLD_SEARCH_KEYS.get(provider, ()):
        t = sc.get(table) if isinstance(sc.get(table), dict) else {}
        if not isinstance(t.get(key), str):
            out.append(f"[scaffold] {table}: no {key} (new_course.py's {provider} search reads it: {what}"
                       + (f", with {', '.join('{' + f + '}' for f in fields)}" if fields else "") + ")")
            continue
        try:
            have = {f for _, f, _, _ in string.Formatter().parse(t[key]) if f is not None}
        except ValueError as e:  # an unclosed brace
            out.append(f"[scaffold] {table} {key}: {t[key]!r} is not a URL pattern ({e}): {what}")
            continue
        if fields and have != set(fields):
            out.append(f"[scaffold] {table} {key}: {t[key]!r} must hold {', '.join('{' + f + '}' for f in fields)} "
                       f"and no other field" + (f" (not {', '.join('{' + f + '}' for f in sorted(have - set(fields)))})"
                                               if have - set(fields) else "") + f": {what}")
    return out


def problems(region, scaffold=True):
    """Every table and key the engine reads that `region` (a parsed regions/<name>.toml, or config.REGION) lacks, as
    messages naming the table: [] when the region is complete. scaffold=False skips [scaffold] (config.REGION, the
    merged region a course builds with, does not carry it)."""
    out = []
    for table, keys, reader in TABLES:
        t = _get(region, table)
        if not isinstance(t, dict):
            out.append(f"[{table}]: missing ({reader})")
            continue
        out += [f"[{table}] {k}: missing ({reader})" for k in keys if k not in t]
    tr = region.get("trees") if isinstance(region.get("trees"), dict) else {}
    arch = list(tr.get("archetypes", ()))
    shapes, bark = tr.get("shapes"), tr.get("bark")   # a missing table is reported above, once
    foliage, needles = region.get("foliage"), tr.get("needles", {})
    if arch and not isinstance(foliage, dict):
        out.append("[foliage]: missing (make_foliage: leaf cards per archetype)")
    for a in arch:
        if isinstance(shapes, dict) and a not in shapes:
            out.append(f"[trees.shapes.{a}]: missing (make_trees draws every archetype)")
        elif isinstance(shapes, dict):
            out += [f"[trees.shapes.{a}] {k}: missing" for k in SHAPE_KEYS if k not in shapes[a]]
        if isinstance(bark, dict) and a not in bark:
            out.append(f"[trees] bark: no {a} (add_vegetation, fetch_textures)")
        if not isinstance(foliage, dict):
            continue
        if a not in foliage:
            out.append(f"[foliage.{a}]: missing (make_foliage)")
        else:
            out += [f"[foliage.{a}] {k}: missing" for k in FOLIAGE_KEYS if k not in foliage[a]]
            if not foliage[a].get("src") and needles.get(a) not in NEEDLE_STYLES:
                out.append(f"[foliage.{a}]: no leaf sprites (src) and no needle style in [trees] needles "
                           f"({' / '.join(NEEDLE_STYLES)})")
    for k, v in needles.items():
        if v not in NEEDLE_STYLES:
            out.append(f"[trees] needles: {k} = {v!r} is not a needle style ({' / '.join(NEEDLE_STYLES)})")
    bd = tr.get("backdrop", {})
    if isinstance(bd, dict):
        out += [f"[trees.backdrop] kinds: {k} is not an archetype" for k in bd.get("kinds", ()) if k not in arch]
        if "kinds" in bd and "share" in bd and len(bd["kinds"]) != len(bd["share"]):
            out.append(f"[trees.backdrop]: {len(bd['kinds'])} kinds for {len(bd['share'])} shares")
    name = tr.get("classifier")
    if name is not None and name not in CLASSIFIERS:
        out.append(f"[trees] classifier: {name!r} is not one of detect_trees' classifiers ({', '.join(CLASSIFIERS)})")
    elif name is not None:
        params, roles = CLASSIFIERS[name]
        prm = tr.get(name)
        if not isinstance(prm, dict):
            out.append(f"[trees.{name}]: missing (the classifier's parameters and names)")
        else:
            out += [f"[trees.{name}] {k}: missing" for k in params if k not in prm]
            names = prm.get("names", {})
            out += [f"[trees.{name}] names: no {k}" for k in roles if k not in names]
            out += [f"[trees.{name}] names: {k} = {v!r} is not an archetype ([trees] archetypes)"
                    for k, v in names.items() if v not in arch]
            out += [f"[trees.{name}] {k}: true or false, not {prm[k]!r}"
                    for k in ("lidar_leaf_off", "imagery_leaf_off") if k in prm and not isinstance(prm[k], bool)]
    return out + (scaffold_problems(region) if scaffold else [])
