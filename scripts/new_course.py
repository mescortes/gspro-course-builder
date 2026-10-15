"""Start a new course: courses/<slug>/course.toml with the frame, extents and likely data sources filled in.

  new_course.py <slug> "Course name" --region <region> (--osm way/123 [--osm way/456] | --bbox=w,s,e,n) [--crs EPSG:n] [--force]

--osm names the course's OSM leisure=golf_course outline(s) (a practice area can be a second one); --bbox (lon/lat)
stands in for a course OSM does not map. The region file's [scaffold] table gives the datum, the providers, the photo
resolution and the usual leaf state of the data. The frame is the datum's UTM zone ([scaffold] crs or --crs for a grid
EPSG names otherwise, e.g. GDA2020 / MGA). Found from the network: the outline, the OSM hole lines inside it, the LiDAR
project(s) covering it (NRCan: the S3 folders that hold its tiles; USGS 3DEP: the newest project), the backdrop DEM
files and the median ground height; another provider's tables are copied from the region for you to fill in.
Scorecard, tees, ratings and tuning are left for research (check_course.py lists what is missing).

Frame (the rules Westmount was set up with): CORE = the outline + 100 m, rounded up to whole 256 m tiles and centred on
it; TERRAIN = a 2048 m square centred on CORE (a 4097^2 GSPro heightmap at 0.5 m); ORIGIN = the CORE centre floored to
50 m; BASE_H = the median ground height rounded to 5 m.
"""
import argparse, json, math, re, sys, tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
from sources.http import UA  # noqa: E402

TILE, MARGIN, TERRAIN = 256.0, 100.0, 2048.0
# A frame whose metres differ from ground metres by more than this at the course (the grid's scale factor) gives wrong
# distances and yardages: 0.5 % is 2 yards on a 400-yard hole. A UTM zone is within 0.1 % (0.2-0.3 % in the
# neighbouring zone); Web Mercator is 38 % off at 43 N.
MAX_SCALE_ERROR = 0.005


def utm_crs(lon, lat, datum, template=None):
    """EPSG code of the course's map frame at lon/lat: `datum` / UTM zone <n>N|S, or the region's [scaffold] crs
    `template` (an EPSG code, or a CRS name with {zone} and {hemisphere}, e.g. "GDA2020 / MGA zone {zone}": EPSG names
    the UTM zones of some datums otherwise)."""
    from pyproj.aoi import AreaOfInterest
    from pyproj.database import query_crs_info
    from pyproj.enums import PJType
    zone = int((lon + 180) // 6) + 1
    hemisphere = "N" if lat >= 0 else "S"
    if template and template.upper().startswith("EPSG:"):
        return template.upper()
    name = (template or "{datum} / UTM zone {zone}{hemisphere}").format(datum=datum, zone=zone, hemisphere=hemisphere)
    for c in query_crs_info(auth_name="EPSG", pj_types=PJType.PROJECTED_CRS):
        if c.name == name and not c.deprecated:
            return f"EPSG:{c.code}"
    here = [c for c in query_crs_info(auth_name="EPSG", pj_types=PJType.PROJECTED_CRS, contains=True,
                                      area_of_interest=AreaOfInterest(lon, lat, lon, lat))
            if not c.deprecated and c.name.startswith(f"{datum} /")]
    sys.exit(f"no EPSG CRS is named {name!r}. " + (f"The {datum} CRSs covering the course: " + "; ".join(
        f"EPSG:{c.code} {c.name}" for c in here[:12]) + ". " if here else f"No {datum} CRS covers the course. ") +
        "Pass the frame CRS with --crs EPSG:<code> (the CRS the LiDAR is delivered in), or set the region's "
        "[scaffold] crs to an EPSG code or a name with {zone} / {hemisphere} (e.g. \"GDA2020 / MGA zone {zone}\").")


def zone_crs(zone, lat, datum, template=None):
    """'EPSG:<code> (<name>)' of `datum` / UTM zone `zone` (or the region's [scaffold] crs name template, as utm_crs)
    for messages, or None: EPSG names no such CRS, or the template is a fixed code."""
    from pyproj.database import query_crs_info
    from pyproj.enums import PJType
    if template and template.upper().startswith("EPSG:"):
        return None
    name = (template or "{datum} / UTM zone {zone}{hemisphere}").format(datum=datum, zone=zone,
                                                                        hemisphere="N" if lat >= 0 else "S")
    return next((f"EPSG:{c.code} ({c.name})" for c in query_crs_info(auth_name="EPSG", pj_types=PJType.PROJECTED_CRS)
                 if c.name == name and not c.deprecated), None)


def neighbour_zone(lon, zone):
    """The UTM zone across the boundary of `zone` nearer to lon (zones 60 and 1 are neighbours)."""
    return zone % 60 + 1 if lon > (zone - 1) * 6 - 177 else (zone - 2) % 60 + 1


def check_frame_crs(crs, lon=None, lat=None):
    """`crs` as EPSG:<code>, or exit: the engine reads every course coordinate as metres east / north and names the
    frame by its EPSG code (the photo request, the feature files' crs). With the course's lon / lat, the grid's metres
    must also be ground metres there, within MAX_SCALE_ERROR."""
    from pyproj import CRS, Proj
    from pyproj.exceptions import CRSError
    where = f"frame CRS {crs} (--crs or the region's [scaffold] crs)"
    try:
        c = CRS(crs)
    except CRSError:
        sys.exit(f"{where}: not a CRS pyproj knows (an EPSG code such as EPSG:2958)")
    if c.is_compound:
        h = c.sub_crs_list[0].to_epsg()
        sys.exit(f"{where} ({c.name}) is a compound CRS (position and heights): the frame is the horizontal part"
                 + (f", --crs EPSG:{h}" if h else "") + " (the heights stay as the LiDAR gives them)")
    if not c.is_projected:
        sys.exit(f"{where} ({c.name}) is not a projected CRS: the course frame is a map grid in metres")
    if any(a.unit_conversion_factor != 1.0 for a in c.axis_info):
        units = sorted({a.unit_name for a in c.axis_info})
        here = zone_crs(int((lon + 180) // 6) + 1, lat, c.name.split(" / ")[0]) if lon is not None else None
        sys.exit(f"{where} ({c.name}) is in {', '.join(units)}: the course frame must be a metre grid (the engine "
                 "reads every course coordinate as metres). LiDAR delivered in feet or in another zone is reprojected "
                 "as it is read, so frame the course in a metre CRS of the same datum: leave out --crs (new_course.py "
                 "picks the region datum's UTM zone)" + (f"; here {here}" if here else ""))
    fix = ("use the course's UTM zone (leave out --crs: new_course.py picks the region datum's zone) or the national "
           "metre grid the LiDAR is delivered in")
    method = (c.coordinate_operation.method_name if c.coordinate_operation else "").lower()
    if "pseudo mercator" in method or ("mercator" in method and "spherical" in method):
        sys.exit(f"{where} ({c.name}) is Web Mercator, a map-tile projection whose metres are not ground metres "
                 f"(a metre on the ground is 1.38 of its metres at 43 N): {fix}")
    code = c.to_epsg()
    if code is None:
        sys.exit(f"{where} ({c.name}) has no EPSG code: the engine names the frame EPSG:<code>, so pass the EPSG code "
                 "of this CRS (--crs EPSG:<code>)")
    if lon is not None and lat is not None:
        f = Proj(c).get_factors(lon, lat)
        k = max((f.meridional_scale, f.parallel_scale), key=lambda s: abs(s - 1))
        if not math.isfinite(k):
            sys.exit(f"{where} ({c.name}) does not reach the course at {lon:.4f}, {lat:.4f}: {fix}")
        if abs(k - 1) > MAX_SCALE_ERROR:
            sys.exit(f"{where} ({c.name}): a metre on the ground is {k:.4f} of its metres at the course "
                     f"({abs(k - 1):.1%} off: a 400-yard hole would measure {400 * k:.0f} yards): {fix}")
    return f"EPSG:{code}"


def frame(outline_xy, median_ground):
    """origin, base_h, core, terrain (dicts of floats) from the outline vertices in the course CRS."""
    xs = [p[0] for p in outline_xy]; ys = [p[1] for p in outline_xy]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    w = math.ceil((max(xs) - min(xs) + 2 * MARGIN) / TILE) * TILE
    h = math.ceil((max(ys) - min(ys) + 2 * MARGIN) / TILE) * TILE
    x0 = round((cx - w / 2) / 10) * 10.0; y0 = round((cy - h / 2) / 10) * 10.0
    core = dict(xmin=x0, ymin=y0, xmax=x0 + w, ymax=y0 + h)
    ccx, ccy = x0 + w / 2, y0 + h / 2
    terrain = dict(xmin=ccx - TERRAIN / 2, ymin=ccy - TERRAIN / 2, xmax=ccx + TERRAIN / 2, ymax=ccy + TERRAIN / 2)
    return {"origin": [math.floor(ccx / 50) * 50.0, math.floor(ccy / 50) * 50.0],
            "base_h": round(median_ground / 5) * 5.0, "core": core, "terrain": terrain}


def _toml(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml(x) for x in v) + "]"
    return "{ " + ", ".join(f"{k} = {_toml(x)}" for k, x in v.items()) + " }"


def _ranges(holes):
    out, run = [], [holes[0]]
    for h in holes[1:]:
        if h == run[-1] + 1:
            run.append(h)
        else:
            out.append(run); run = [h]
    out.append(run)
    return ",".join(f"{r[0]}-{r[-1]}" if len(r) > 1 else str(r[0]) for r in out)


def course_toml(name, region_name, region, crs, fr, holes, lidar, backdrop, outline=(), notes=(), ground_known=True):
    """The course.toml skeleton text. holes: the OSM hole refs ([] writes 1-18 marked TODO); ground_known=False marks
    base_h TODO (no DTM gave a ground height)."""
    sc = region["scaffold"]
    base_note = ("metres subtracted from heights in the model frame" if ground_known else
                 "TODO: no DTM gave a ground height: set the median ground height (m) rounded to 5 m")
    lines = [f"# {name}. Skeleton written by new_course.py: check every value, then run check_course.py.", ""]
    lines += [f"# {n}" for n in notes] + ([""] if notes else [])
    lines += ["[course]", f"name = {_toml(name)}", f"region = {_toml(region_name)}", "",
              "[frame]", f"crs = {_toml(crs)}", f"crs_label = {_toml(crs + '; heights ' + sc['vertical'] + ' (m)')}",
              f"origin = {_toml(fr['origin'])}", f"base_h = {_toml(fr['base_h'])}  # {base_note}",
              f"core = {_toml(fr['core'])}  # the outline + 100 m, whole 256 m tiles",
              f"terrain = {_toml(fr['terrain'])}  # 2048 m GSPro terrain square", ""]
    if outline:
        lines += ["[osm]", f"outline = {_toml(list(outline))}  # this course's leisure=golf_course outline(s)", ""]
    # leaf-off LiDAR / photo change the tree detection and the surfaces under canopy: the region's usual data is only a
    # guess for this course
    lines += ["[lidar]", f"leaf_off = {_toml(sc['lidar_leaf_off'])}  # regions/{region_name}.toml's usual LiDAR: check the "
              "flight dates (true = flown with the deciduous trees bare)", ""]
    lines += ["[sources.lidar]"] + [f"{k} = {_toml(v)}" for k, v in lidar.items()] + [""]
    lines += ["[sources.imagery]"] + [f"{k} = {_toml(v)}" for k, v in sc["imagery"].items()] + [""]
    lines += ["[sources.backdrop]"] + [f"{k} = {_toml(v)}" for k, v in backdrop.items()] + [""]
    lines += ["[imagery]", 'raw = "photo.tif"', 'registered = "photo_reg.tif"', f"res = {_toml(sc['imagery_res'])}",
              "shift = [0.0, 0.0]  # measure_registration.py after the first build (it prints the line to paste)",
              f"leaf_off = {_toml(sc['imagery_leaf_off'])}  # regions/{region_name}.toml's usual photo: check the photo "
              "date (true = taken with the deciduous trees bare)", ""]
    play = (f'playable = "{_ranges(holes)}"' if holes else
            'playable = "1-18"  # TODO: OSM has no golf=hole lines here: set the course\'s holes')
    lines += ["[holes]", play, "", "# [[tees]] key / name / colour / gkd_slot, back to front",
              '# [scorecard] units = "yards" (or "metres", as the card gives them); hole = [par, distance per tee...]',
              '# [stroke_index] men / women (women = "same" for one index); [ratings] tee = { men = [rating, slope], '
              "women = [...], yards = the tee's total in yards } ({} for an unrated tee): from research", ""]
    return "\n".join(lines)


# ---- network: OSM outline and holes, LiDAR projects, backdrop DEM, ground height
def osm_outline(refs):
    """lon/lat rings of the OSM elements (way/<id> or relation/<id>) from the OSM API."""
    import requests
    rings = []
    for ref in refs:
        typ, _, oid = ref.partition("/")
        r = requests.get(f"https://api.openstreetmap.org/api/0.6/{typ}/{oid}/full.json", headers=UA, timeout=120)
        r.raise_for_status()
        els = r.json()["elements"]
        nodes = {e["id"]: (e["lon"], e["lat"]) for e in els if e["type"] == "node"}
        for e in els:
            if e["type"] == "way" and (typ == "way" and e["id"] == int(oid) or typ == "relation"):
                rings.append([nodes[n] for n in e["nodes"]])
    return rings


def osm_holes(bbox_ll):
    """Sorted golf=hole refs in a lon/lat box (Overpass, else the OSM API)."""
    import requests
    w, s, e, n = bbox_ll
    q = f'[out:json][timeout:120];way["golf"="hole"]({s},{w},{n},{e});out tags;'
    for ep in ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"):
        try:
            r = requests.post(ep, data={"data": q}, headers=dict(UA, Accept="application/json"), timeout=180)
            if r.status_code == 200:
                return sorted({int(x["tags"]["ref"]) for x in r.json()["elements"] if x.get("tags", {}).get("ref", "").isdigit()})
        except requests.RequestException:
            continue
    return []


def nrcan_projects(core, zone, province):
    """[{folder, suffix}] of the NRCan point-cloud folders holding the core's 1 km tiles, most tiles first."""
    import requests, xml.etree.ElementTree as ET
    from sources import nrcan_copc
    bucket = nrcan_copc.BUCKET.rsplit("/", 1)[0]
    ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    def ls(prefix, delim=None):
        p = dict({"list-type": "2", "prefix": prefix}, **({"delimiter": delim} if delim else {}))
        return ET.fromstring(requests.get(bucket + "/", params=p, headers=UA, timeout=120).content)
    root = ls(f"pointclouds_nuagespoints/{province}/", "/")
    folders = [c.find("s3:Prefix", ns).text for c in root.findall("s3:CommonPrefixes", ns)]
    found = {}
    for e, n in nrcan_copc.tiles(core):
        for f in folders:
            name = f"1km{zone}{e:04d}{n:05d}"
            for k in ls(f + name).findall("s3:Contents/s3:Key", ns):
                m = re.fullmatch(re.escape(f + name) + r"(.+)\.copc\.laz", k.text)
                if m:
                    key = (f[len("pointclouds_nuagespoints/"):].rstrip("/"), m.group(1))
                    found[key] = found.get(key, 0) + 1
    return [{"folder": f, "suffix": s} for (f, s), _ in sorted(found.items(), key=lambda kv: -kv[1])]


def usgs_projects(bbox_ll):
    """3DEP point-cloud projects over the box, newest first: [(project, publication date)]."""
    import requests
    w, s, e, n = bbox_ll
    r = requests.get("https://tnmaccess.nationalmap.gov/api/v1/products", headers=UA, timeout=120,
                     params=dict(datasets="Lidar Point Cloud (LPC)", bbox=f"{w},{s},{e},{n}", max=200))
    proj = {}
    for it in r.json().get("items", []):
        m = re.search(r"USGS_LPC_(.+?)_[^_]+\.laz$", it.get("downloadURL", ""))
        if m:
            proj[m.group(1)] = max(proj.get(m.group(1), ""), it.get("publicationDate", ""))
    return sorted(proj.items(), key=lambda kv: kv[1], reverse=True)


def usgs_dem(bbox_ll, project):
    """3DEP 1 m DEM COG URLs over the box for a project (its 1 m DEM shares the project name)."""
    import requests
    w, s, e, n = bbox_ll
    r = requests.get("https://tnmaccess.nationalmap.gov/api/v1/products", headers=UA, timeout=120,
                     params=dict(datasets="Digital Elevation Model (DEM) 1 meter", bbox=f"{w},{s},{e},{n}", max=200))
    base = project.split("_", 2)[:2]
    return sorted({it["downloadURL"] for it in r.json().get("items", []) if "_".join(base) in it.get("downloadURL", "")})


def median_ground(dtm_urls, crs, ext, res=10.0):
    """Median of the DTM over ext (course CRS), read from the COGs; None when no DTM covers it."""
    import numpy as np, rasterio
    from rasterio.transform import from_origin
    from rasterio.vrt import WarpedVRT
    from rasterio.enums import Resampling
    W = int((ext["xmax"] - ext["xmin"]) / res); H = int((ext["ymax"] - ext["ymin"]) / res)
    vals = []
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="5", GDAL_HTTP_RETRY_DELAY="1"):
        for u in dtm_urls:
            try:
                with rasterio.open("/vsicurl/" + u) as ds, WarpedVRT(ds, crs=crs, transform=from_origin(ext["xmin"], ext["ymax"], res, res),
                                                                    width=W, height=H, resampling=Resampling.average,
                                                                    src_nodata=ds.nodata, nodata=np.nan, dtype="float32") as v:
                    a = v.read(1)
                vals.append(a[np.isfinite(a) & (a > -1000)])
            except rasterio.errors.RasterioIOError:
                continue
    v = np.concatenate(vals) if vals else np.array([])
    return float(np.median(v)) if v.size else None


def load_region(name):
    """regions/<name>.toml, or exit naming the known regions or what its [scaffold] lacks."""
    import region_spec
    path = ROOT / "regions" / f"{name}.toml"
    try:
        with open(path, "rb") as f:
            region = tomllib.load(f)
    except FileNotFoundError:
        known = sorted(p.stem for p in (ROOT / "regions").glob("*.toml"))
        sys.exit(f"--region {name}: no regions/{name}.toml (regions/ has {', '.join(known) or 'none'}; "
                 "regions/TEMPLATE.toml.example starts a new one)")
    except tomllib.TOMLDecodeError as e:
        sys.exit(f"regions/{name}.toml: {e}")
    bad = region_spec.scaffold_problems(region)
    if bad:
        sys.exit(f"regions/{name}.toml: " + "; ".join(bad) + " (see regions/TEMPLATE.toml.example)")
    return region


def discover_sources(sc, fr, bbox_ll, crs, zone):
    """([sources.lidar], [sources.backdrop], notes) for the course: the LiDAR projects and backdrop DEM files found
    for the region's providers (NRCan, USGS 3DEP), or the region's [scaffold] tables as they are for a provider
    new_course.py cannot search. Exits when no LiDAR project covers the course."""
    from pyproj import Transformer
    provider, notes = sc["lidar"]["provider"], []
    if provider == "nrcan_copc":
        province = sc["lidar"]["province"]
        lon, lat = (bbox_ll[0] + bbox_ll[2]) / 2, (bbox_ll[1] + bbox_ll[3]) / 2
        code = lambda z: zone_crs(z, lat, sc["datum"], sc.get("crs")) or f"that zone's {sc['datum']} / UTM EPSG code"
        if zone is None:  # tile names are the tiles' UTM coordinates in their zone, read from the frame's
            own = int((lon + 180) // 6) + 1
            sys.exit(f"frame CRS {crs} is not a UTM zone, but NRCan names its 1 km tiles by UTM zone and their "
                     f"coordinates in that zone: the frame must be a {sc['datum']} / UTM zone CRS. Leave --crs out "
                     f"for the course's own zone, {code(own)}; near a zone boundary the project may be delivered in "
                     f"the neighbouring zone: --crs {code(neighbour_zone(lon, own))}")
        projects = nrcan_projects(fr["core"], zone, province)
        if not projects:
            sys.exit(f"no NRCan point-cloud folder under pointclouds_nuagespoints/{province}/ holds the course's 1 km "
                     f"tiles (zone {zone}): check --osm / --bbox, or the region's [scaffold] lidar; near a zone "
                     f"boundary the project may be delivered in the neighbouring zone: --crs "
                     f"{code(neighbour_zone(lon, zone))}")
        lidar = {"provider": "nrcan_copc", "zone": zone, "projects": projects}
        dtm = [sc["backdrop"]["url"].format(province=province, project=p["folder"].split("/", 1)[1], kind="dtm")
               for p in projects]
        backdrop = {"provider": "cog_dem", "dtm": dtm, "dsm": [u.replace("-1m-dtm.tif", "-1m-dsm.tif") for u in dtm]}
        notes.append("LiDAR folders: " + ", ".join(p["folder"] for p in projects) +
                     " (folder names do not tell the flight date: read the points' GPS times)")
    elif provider == "usgs_3dep":
        projects = usgs_projects(bbox_ll)
        if not projects:
            sys.exit(f"no USGS 3DEP point-cloud project covers {bbox_ll} (TNM API; retry if it was down): check --osm / "
                     "--bbox, or the region's [scaffold] lidar")
        lidar = {"provider": "usgs_3dep", "project": projects[0][0]}
        bt = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        b = fr["terrain"]; cx, cy = (b["xmin"] + b["xmax"]) / 2, (b["ymin"] + b["ymax"]) / 2
        bl = [bt.transform(cx + dx, cy + dy) for dx in (-2500, 2500) for dy in (-2500, 2500)]
        dem = usgs_dem((min(p[0] for p in bl), min(p[1] for p in bl), max(p[0] for p in bl), max(p[1] for p in bl)), lidar["project"])
        backdrop = {"provider": "cog_dem", "dtm": dem}
        notes.append("3DEP projects, newest first: " + ", ".join(f"{p} ({d})" for p, d in projects))
        if not dem:
            notes.append(f"TODO: no 3DEP 1 m DEM named for {lidar['project']}: list the backdrop DTM files in "
                         "[sources.backdrop] dtm")
    else:  # a provider with no search here: the region's tables as they are
        lidar, backdrop = dict(sc["lidar"]), dict(sc["backdrop"])
        notes.append(f"TODO: new_course.py cannot search provider {provider!r}: [sources.lidar] and [sources.backdrop] "
                     f"are the region's [scaffold] tables; fill in this course's tiles (scripts/sources/{provider}.py)")
    return lidar, backdrop, notes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("slug"); ap.add_argument("name"); ap.add_argument("--region", required=True)
    ap.add_argument("--osm", action="append", default=[]); ap.add_argument("--bbox")
    ap.add_argument("--force", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--crs", help="the course frame, e.g. EPSG:7856 (default: the region's datum in the UTM zone)")
    a = ap.parse_args(argv)
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", a.slug) or a.slug.endswith("-test"):
        sys.exit("slug: lower-case words joined by '-', not ending in '-test'")
    out = ROOT / "courses" / a.slug / "course.toml"
    if out.exists() and not (a.force or a.dry_run):
        sys.exit(f"{out} exists (--force to overwrite)")
    region = load_region(a.region)
    sc = region["scaffold"]
    if a.osm:
        rings = osm_outline(a.osm)
        ll = [p for r in rings for p in r]
    elif a.bbox:
        w, s, e, n = map(float, a.bbox.split(","))
        ll = [(w, s), (e, s), (e, n), (w, n)]
    else:
        sys.exit("--osm or --bbox")
    lon = sum(p[0] for p in ll) / len(ll); lat = sum(p[1] for p in ll) / len(ll)
    crs = check_frame_crs(a.crs or utm_crs(lon, lat, sc["datum"], sc.get("crs")), lon, lat)
    from pyproj import CRS, Transformer
    tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    xy = [tr.transform(*p) for p in ll]
    bbox_ll = (min(p[0] for p in ll), min(p[1] for p in ll), max(p[0] for p in ll), max(p[1] for p in ll))
    fr = frame(xy, 0.0)
    notes = []
    holes = osm_holes(bbox_ll) if a.osm else []
    notes.append(f"OSM: {len(holes)} golf=hole refs inside the outline box" + (f" ({_ranges(holes)})" if holes else
                 " - draw the holes in courses/<slug>/features/golf.geojson"))
    zone = CRS(crs).utm_zone  # the frame's zone ("18N"), not the longitude's: the frame may be --crs another zone
    zone = int(zone[:-1]) if zone else None
    lidar, backdrop, found = discover_sources(sc, fr, bbox_ll, crs, zone)
    notes += found
    ground = median_ground(backdrop.get("dtm") or [], crs, fr["core"])
    fr = frame(xy, 0.0 if ground is None else ground)
    text = course_toml(a.name, a.region, region, crs, fr, holes, lidar, backdrop, a.osm, notes, ground_known=ground is not None)
    if a.dry_run:
        print(text); return
    out.parent.mkdir(parents=True, exist_ok=True)
    for d in (("features", "overrides"), ("research",)):
        out.parent.joinpath(*d).mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print("wrote", out)


if __name__ == "__main__":
    main()
