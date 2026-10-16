"""Fetch every input for the course extent (idempotent; skips files that already exist).

  LiDAR    classified point-cloud tiles covering config.FETCH_CORE + 15 m, from the course's [sources.lidar] provider
           (scripts/sources), into data/<slug>/lidar, listed in data/<slug>/lidar/tiles.json
  OSM      golf / building / road features via Overpass, or the OSM API when Overpass is down
           (courses/<slug>/research/osm_all.json, osm_golf.json, both in Overpass 'out geom' JSON); `osm-relations`
           completes the multipolygons of a snapshot the OSM API fallback left without their members outside the box
  Imagery  the [sources.imagery] orthophoto (R, G, B, NIR) over FETCH_CORE + 20 m (config.IMAGERY_RAW)
  Backdrop handled by fetch_backdrop.py / build_backdrop.py

Every file is written whole or not at all (scripts/sources/store.py), with <file>.source.json recording what it was
fetched from. An existing photo or OSM snapshot is kept only while it is still what course.toml asks for: after
[frame] core, [imagery] res or [sources.imagery] changed, the fetch stops and says which setting and what to do.
"""
import sys, json, time
from pathlib import Path
import requests
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).parent))
import config as C

from sources import store
from sources.http import UA, permanent
OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter")
OSM_API = "https://api.openstreetmap.org/api/0.6/map"
OSM_API_RELATION = "https://api.openstreetmap.org/api/0.6/relation/{}/full"
# Overpass remarks of a query too big for it ('Query timed out in "query" ...', 'Query run out of memory ...'), unlike
# a busy server's ('Dispatcher_Client::request_read_and_idx::timeout. The server is probably too busy ...')
TOO_BIG = ("timed out", "out of memory")


def lonlat_bbox(e, margin=0.0):
    tr = Transformer.from_crs(C.CRS, "EPSG:4326", always_xy=True)
    xs = [e["xmin"] - margin, e["xmax"] + margin]; ys = [e["ymin"] - margin, e["ymax"] + margin]
    pts = [tr.transform(x, y) for x in xs for y in ys]
    return min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)


def fetch_lidar():
    import sources
    mod, spec = sources.provider("lidar")
    kw = dict(crs=C.CRS) if spec["provider"] == "usgs_3dep" else {}
    print("lidar tiles:", mod.fetch(spec, C.FETCH_CORE, C.DATA / "lidar", **kw))


def overpass_error(text):
    """Why an HTTP 200 Overpass reply is not a snapshot (None when it is one). A query that hits the timeout or the
    memory limit, or reaches a busy server, still answers 200, with a 'remark' saying 'runtime error: ...' and empty or
    partial elements."""
    try:
        reply = json.loads(text)
    except ValueError:
        return "not JSON"
    if not isinstance(reply, dict) or not isinstance(reply.get("elements"), list):
        return "no elements"
    remark = str(reply.get("remark", ""))
    return f"remark: {remark}" if "error" in remark.lower() else None


def overpass(query, path):
    """Run an Overpass query against the public mirrors; True when `path` was written. When every mirror that answers
    says the query is too big for it (TOO_BIG), False at once: the OSM API fallback fetches the box in tiles. A busy
    mirror (its remark, an HTTP 429 / 504), another error or no answer is tried again, up to three rounds."""
    for attempt in range(3):
        too_big = []   # per mirror that answered: whether it said the query is too big
        for ep in OVERPASS:
            try:
                r = requests.post(ep, data={"data": query}, headers=dict(UA, Accept="application/json"), timeout=300)
            except requests.RequestException as ex:
                print("  overpass", ep, ex.__class__.__name__, flush=True); continue
            why = f"HTTP {r.status_code}" if r.status_code != 200 else overpass_error(r.text)
            if why is None:
                store.write_text(path, r.text); return True
            print("  overpass", ep, why[:200], flush=True)
            too_big.append(why.startswith("remark") and any(s in why.lower() for s in TOO_BIG))
        if too_big and all(too_big):
            return False
        time.sleep(10 * (attempt + 1))
    return False


def split_bbox(bb, step):
    """(w, s, e, n) lon/lat box -> list of tiles no larger than `step` degrees (OSM API: <= 0.25 deg2, 50k nodes)."""
    import math
    w, s, e, n = bb
    nx = max(1, math.ceil((e - w) / step - 1e-9)); ny = max(1, math.ceil((n - s) / step - 1e-9))
    xs = [w + (e - w) * i / nx for i in range(nx + 1)]; ys = [s + (n - s) * j / ny for j in range(ny + 1)]
    return [(xs[i], ys[j], xs[i + 1], ys[j + 1]) for j in range(ny) for i in range(nx)]


def osm_xml_to_elements(xml_docs):
    """OSM API /map XML documents (tiles) -> Overpass 'out geom' JSON elements: tagged nodes, every way with its node
    list and geometry, relations with member geometry where the member way was fetched. Tiles are merged by id."""
    import xml.etree.ElementTree as ET
    nodes, ways, rels = {}, {}, {}
    for doc in xml_docs:
        root = ET.fromstring(doc.encode() if isinstance(doc, str) else doc)
        for el in root:
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            i = int(el.get("id", 0))
            if el.tag == "node":
                nodes[i] = (float(el.get("lat")), float(el.get("lon")), tags)
            elif el.tag == "way":
                ways[i] = ([int(nd.get("ref")) for nd in el.findall("nd")], tags)
            elif el.tag == "relation":
                rels[i] = ([(m.get("type"), int(m.get("ref")), m.get("role", "")) for m in el.findall("member")], tags)
    def geom(refs):
        return [{"lat": nodes[r][0], "lon": nodes[r][1]} for r in refs if r in nodes]
    out = []
    for i, (lat, lon, tags) in nodes.items():
        if tags:
            out.append({"type": "node", "id": i, "lat": lat, "lon": lon, "tags": tags})
    for i, (refs, tags) in ways.items():
        e = {"type": "way", "id": i, "nodes": refs, "geometry": geom(refs)}
        if tags:
            e["tags"] = tags
        out.append(e)
    for i, (members, tags) in rels.items():
        ms = []
        for typ, ref, role in members:
            m = {"type": typ, "ref": ref, "role": role}
            if typ == "way" and ref in ways:
                m["geometry"] = geom(ways[ref][0])
            elif typ == "node" and ref in nodes:
                m["lat"], m["lon"] = nodes[ref][0], nodes[ref][1]
            ms.append(m)
        out.append({"type": "relation", "id": i, "members": ms, "tags": tags})
    return out


def golf_only(elements):
    return [e for e in elements if "golf" in e.get("tags", {}) or e.get("tags", {}).get("leisure") == "golf_course"]


def osm_api_tile(t, depth=0):
    """The OSM API /map XML documents of one lon/lat tile: retried on network errors and 5xx / 429, split in four
    (down to 1/64 of the tile) when the API refuses it as over its 50,000-node limit (a 400 no retry changes)."""
    err = None
    for attempt in range(5):
        try:
            r = requests.get(OSM_API, params={"bbox": ",".join(f"{v:.6f}" for v in t)}, headers=UA, timeout=300)
        except requests.RequestException as ex:
            err = ex.__class__.__name__
        else:
            if r.status_code == 200:
                return [r.text]
            if r.status_code == 400 and "too many nodes" in r.text.lower() and depth < 3:
                w, s, e, n = t; mx, my = (w + e) / 2, (s + n) / 2
                return [d for q in ((w, s, mx, my), (mx, s, e, my), (w, my, mx, n), (mx, my, e, n))
                        for d in osm_api_tile(q, depth + 1)]
            err = f"HTTP {r.status_code} {r.text[:120]}"
            if permanent(r.status_code):
                break
        print("  osm api", err, flush=True); time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"OSM API failed for tile {t} ({err}); Overpass failed too: rerun fetch_data.py osm later")


def osm_api_relation(rid):
    """The OSM API /relation/<rid>/full XML document (the relation, its member ways and their nodes), retried on network
    errors and 5xx / 429; None, with a warning, when the API cannot give it."""
    err = None
    for attempt in range(5):
        try:
            r = requests.get(OSM_API_RELATION.format(rid), headers=UA, timeout=300)
        except requests.RequestException as ex:
            err = ex.__class__.__name__
        else:
            if r.status_code == 200:
                return r.text
            err = f"HTTP {r.status_code} {r.text[:120]}"
            if permanent(r.status_code):
                break
        print("  osm api relation", rid, err, flush=True); time.sleep(10 * (attempt + 1))
    print(f"  osm api: relation {rid} left without the members outside the box ({err})", flush=True)
    return None


def complete_multipolygons(elements, full=None):
    """In place (and returned): the OSM API's /map gives a relation with the geometry of only its member ways inside the
    box, so a multipolygon reaching past it (Deer Ridge: the Grand River, 5 of its 47 members) is never polygonised.
    Each multipolygon with a member way lacking geometry gets its members' geometry from full(id) (the
    /relation/<id>/full XML: osm_api_relation), as Overpass 'out geom' gives it; those ways are not added as features.
    A relation full() cannot give (None) stays as it was."""
    full = osm_api_relation if full is None else full
    for e in elements:
        if e["type"] != "relation" or e.get("tags", {}).get("type") != "multipolygon":
            continue
        if all(m.get("geometry") for m in e["members"] if m["type"] == "way"):
            continue
        doc = full(e["id"])
        if doc is None:
            continue
        ways = {x["id"]: x for x in osm_xml_to_elements([doc]) if x["type"] == "way"}
        for m in e["members"]:
            if m["type"] == "way" and not m.get("geometry") and ways.get(m["ref"], {}).get("geometry"):
                m["geometry"] = ways[m["ref"]]["geometry"]
    return elements


def osm_api_map(bb, step=0.012):
    """All OSM data in a lon/lat box from the main API, tile by tile (fallback when Overpass is down), with the
    multipolygons that reach past the box completed (complete_multipolygons)."""
    return complete_multipolygons(osm_xml_to_elements([d for t in split_bbox(bb, step) for d in osm_api_tile(t)]))


def osm_snapshot():
    return [C.RESEARCH / "osm_all.json", C.RESEARCH / "osm_golf.json"]


def osm_problems(bbox=None):
    """Snapshot files whose record says they were fetched for a lon/lat box that does not reach `bbox` (default:
    FETCH_CORE + 400 m). A snapshot fetched before records existed has none and is taken as it is."""
    w, s, e, n = bbox or lonlat_bbox(C.FETCH_CORE, 400)
    out = []
    for p in osm_snapshot():
        rec = store.read_record(p) if p.exists() else None
        if rec and rec.get("bbox"):
            rw, rs, re_, rn = rec["bbox"]
            if rw > w + 1e-7 or rs > s + 1e-7 or re_ < e - 1e-7 or rn < n - 1e-7:
                out.append(f"{p.name} was fetched for lon/lat {rw:.5f},{rs:.5f},{re_:.5f},{rn:.5f}, which does not reach "
                           f"[frame] core + 400 m ({w:.5f},{s:.5f},{e:.5f},{n:.5f})")
    return out


def incomplete_multipolygons(elements):
    """{relation id: (a main tag, member ways with geometry, member ways)} of the multipolygons in `elements` that lack
    the geometry of a member way."""
    out = {}
    for e in elements:
        if e["type"] == "relation" and e.get("tags", {}).get("type") == "multipolygon":
            ways = [m for m in e["members"] if m["type"] == "way"]
            n = sum(1 for m in ways if m.get("geometry"))
            if n < len(ways):
                t = e["tags"]
                k = next((k for k in ("natural", "water", "golf", "leisure", "landuse", "building", "amenity") if k in t), "type")
                out[e["id"]] = (f"{k}={t[k]}", n, len(ways))
    return out


def osm_incomplete():
    """The multipolygons of the OSM snapshot that lack member ways (a snapshot from the OSM API fallback before it
    completed them: complete_multipolygons), as "relation <id> (<tag>): <n> of <m> member ways"."""
    found = {}
    for p in osm_snapshot():
        if p.exists():
            found.update(incomplete_multipolygons(json.load(open(p))["elements"]))
    return [f"relation {i} ({t}): {n} of {m} member ways" for i, (t, n, m) in sorted(found.items())]


def complete_snapshot():
    """`fetch_data.py osm-relations`: complete the multipolygons of the OSM snapshot that lack member ways
    (osm_incomplete) from the OSM API, in place: only their members' geometry is added, every other element stays as
    it was, so the course's QA overrides still fit it."""
    for p in osm_snapshot():
        if not p.exists():
            continue
        d = json.load(open(p))
        before = incomplete_multipolygons(d["elements"])
        if not before:
            continue
        after = incomplete_multipolygons(complete_multipolygons(d["elements"]))
        store.write_text(p, json.dumps(d))
        print(f"osm: {p.name}: {len(before) - len(after)} of {len(before)} multipolygons completed"
              + (f" ({', '.join(f'relation {i} {t}' for i, (t, _, _) in after.items())} still lack members)" if after else ""))


def fetch_osm():
    """courses/<slug>/research/osm_all.json + osm_golf.json. An existing snapshot is kept (the model and its QA
    overrides were built from it); delete both files to refresh. A snapshot recorded for a box that no longer reaches
    the course extent stops the fetch: the OSM features of the new strip would be missing."""
    snap = osm_snapshot()
    w, s, e, n = lonlat_bbox(C.FETCH_CORE, 400)
    if all(p.exists() for p in snap):
        problems = osm_problems((w, s, e, n))
        if problems:
            sys.exit("osm: " + "; ".join(problems) + f". Delete osm_all.json and osm_golf.json in {C.RESEARCH} (and their "
                     ".source.json) to fetch a snapshot of the new extent, then check the course's overrides against it")
        print(f"osm: keeping the snapshot in {C.RESEARCH} (delete osm_all.json and osm_golf.json to refresh)")
        for x in osm_incomplete():
            print(f"!! osm: {x}, the rest outside the box: fetch_data.py osm-relations completes it", flush=True)
        return
    bb = f"{s},{w},{n},{e}"
    C.RESEARCH.mkdir(parents=True, exist_ok=True)
    queries = (f'[out:json][timeout:180];(nwr({bb}););out geom;',
               f'[out:json][timeout:180];(nwr({bb})["golf"];nwr({bb})["leisure"="golf_course"];);out geom;')
    ok = overpass(queries[0], snap[0]) and overpass(queries[1], snap[1])
    if ok:
        for p, q in zip(snap, queries):
            store.write_record(p, dict(provider="overpass", bbox=[w, s, e, n], query=q))
    else:
        print("overpass unavailable: falling back to the OSM API", flush=True)
        els = osm_api_map((w, s, e, n))
        meta = {"version": 0.6, "generator": "fetch_data.py (OSM API /map fallback)",
                "osm3s": {"copyright": "The data included in this document is from www.openstreetmap.org. The data is made "
                                       "available under ODbL."}}
        for p, keep in zip(snap, (els, golf_only(els))):
            store.write_text(p, json.dumps(dict(meta, elements=keep)))
            store.write_record(p, dict(provider="osm_api", bbox=[w, s, e, n], url=OSM_API))
    print("osm ok")


def imagery_request():
    """(provider module, spec, box, bands, request) of the course photo: [sources.imagery] over FETCH_CORE + 20 m (the
    course extent in both profiles: they share data/<slug>/) at [imagery] res."""
    import sources
    mod, spec = sources.provider("imagery")
    e, m = C.FETCH_CORE, 20
    box, bands = (e["xmin"] - m, e["ymin"] - m, e["xmax"] + m, e["ymax"] + m), tuple(spec["bands"])
    return mod, spec, box, bands, mod.request(spec, *box, C.IMAGERY_RES, bands)


def imagery_problems():
    """Why the photo on disk is not the one course.toml asks for ([] when it is, or when there is none). Its extent,
    resolution and bands are read from the GeoTIFF itself, its source from its record (a photo fetched before records
    existed has none: then only the GeoTIFF is checked)."""
    dst = C.IMAGERY_RAW
    if not dst.exists() or not C.DATA_SOURCES.get("imagery"):
        return []
    import rasterio
    _, _, box, bands, req = imagery_request()
    with rasterio.open(dst) as ds:
        b, res, count = ds.bounds, ds.res[0], ds.count
    out, tol = [], max(res, C.IMAGERY_RES)   # the grid is a whole number of pixels: within a pixel of the box
    if b.left > box[0] + tol or b.bottom > box[1] + tol or b.right < box[2] - tol or b.top < box[3] - tol:
        out.append(f"it covers E {b.left:.0f}-{b.right:.0f} N {b.bottom:.0f}-{b.top:.0f}, short of [frame] core + 20 m "
                   f"(E {box[0]:.0f}-{box[2]:.0f} N {box[1]:.0f}-{box[3]:.0f})")
    if abs(res - C.IMAGERY_RES) > 1e-6:
        out.append(f"it is at {res:g} m, [imagery] res is {C.IMAGERY_RES:g} m")
    if count < len(bands):
        out.append(f"it has {count} bands, [sources.imagery] bands lists {len(bands)}")
    for k, old, new in store.changes(dst, req, ignore=("bbox", "res")) or ():
        out.append(f"it was fetched with [sources.imagery] {k} = {old!r}, course.toml now has {new!r}")
    return out


def fetch_imagery():
    """The course photo, unless the one on disk is still what course.toml asks for (imagery_problems)."""
    dst = C.IMAGERY_RAW
    if dst.exists() and not C.DATA_SOURCES.get("imagery"):
        return   # a photo put there by hand: no source to compare it with
    if dst.exists():
        problems = imagery_problems()
        if problems:
            sys.exit(f"imagery: {dst}: " + "; ".join(problems) + ". Delete it to fetch the photo course.toml asks for "
                     "(fetch_data.py imagery), then re-measure [imagery] shift (measure_registration.py); or put the old "
                     "setting back")
        if store.read_record(dst) is None:
            store.write_record(dst, imagery_request()[-1])
            print(f"imagery: {dst.name} has no record of its source (an older fetch): taken as course.toml's "
                  f"[sources.imagery], recorded in {store.record_path(dst).name}")
        return
    mod, spec, box, bands, _ = imagery_request()
    # [sources.imagery] max_empty: the share of the photo the service may leave empty (black) before the fetch fails
    mod.fetch(spec, *box, C.IMAGERY_RES, dst, bands=bands, max_empty=spec.get("max_empty", 0.01))


if __name__ == "__main__":
    what = sys.argv[1:] or ["lidar", "osm", "imagery"]
    if "lidar" in what:
        fetch_lidar()
    if "osm" in what:
        fetch_osm()
    if "osm-relations" in what:
        complete_snapshot()
    if "imagery" in what:
        fetch_imagery()
