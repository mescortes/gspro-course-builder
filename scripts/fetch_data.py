"""Fetch every input for the course extent (idempotent; skips files that already exist).

  LiDAR    classified point-cloud tiles covering config.FETCH_CORE + 15 m, from the course's [sources.lidar] provider
           (scripts/sources), into data/<slug>/lidar
  OSM      golf / building / road features via Overpass, or the OSM API when Overpass is down
           (courses/<slug>/research/osm_all.json, osm_golf.json, both in Overpass 'out geom' JSON)
  Imagery  the [sources.imagery] orthophoto (R, G, B, NIR) over FETCH_CORE + 20 m (config.IMAGERY_RAW)
  Backdrop handled by fetch_backdrop.py / build_backdrop.py
"""
import sys, json, time
from pathlib import Path
import requests
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).parent))
import config as C

from sources.http import UA
OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter")
OSM_API = "https://api.openstreetmap.org/api/0.6/map"


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


def overpass(query, path):
    """Run an Overpass query against the public mirrors; True when `path` was written."""
    for attempt in range(3):
        for ep in OVERPASS:
            try:
                r = requests.post(ep, data={"data": query}, headers=dict(UA, Accept="application/json"), timeout=300)
            except requests.RequestException as ex:
                print("  overpass", ep, ex.__class__.__name__, flush=True); continue
            if r.status_code == 200 and r.text.lstrip().startswith("{"):
                Path(path).write_text(r.text); return True
            print("  overpass", ep, r.status_code, flush=True)
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


def osm_api_map(bb, step=0.012):
    """All OSM data in a lon/lat box from the main API, tile by tile (fallback when Overpass is down)."""
    docs = []
    for t in split_bbox(bb, step):
        for attempt in range(5):
            r = requests.get(OSM_API, params={"bbox": ",".join(f"{v:.6f}" for v in t)}, headers=UA, timeout=300)
            if r.status_code == 200:
                docs.append(r.text); break
            print("  osm api", r.status_code, r.text[:120], flush=True); time.sleep(10 * (attempt + 1))
        else:
            raise RuntimeError(f"OSM API failed for tile {t}")
    return osm_xml_to_elements(docs)


def fetch_osm():
    """courses/<slug>/research/osm_all.json + osm_golf.json. An existing snapshot is kept (the model and its QA
    overrides were built from it); delete both files to refresh."""
    snap = [C.RESEARCH / "osm_all.json", C.RESEARCH / "osm_golf.json"]
    if all(p.exists() for p in snap):
        print(f"osm: keeping the snapshot in {C.RESEARCH} (delete osm_all.json and osm_golf.json to refresh)")
        return
    w, s, e, n = lonlat_bbox(C.FETCH_CORE, 400)
    bb = f"{s},{w},{n},{e}"
    C.RESEARCH.mkdir(parents=True, exist_ok=True)
    ok = overpass(f'[out:json][timeout:180];(nwr({bb}););out geom;', C.RESEARCH / "osm_all.json") and \
        overpass(f'[out:json][timeout:180];(nwr({bb})["golf"];nwr({bb})["leisure"="golf_course"];);out geom;',
                 C.RESEARCH / "osm_golf.json")
    if not ok:
        print("overpass unavailable: falling back to the OSM API", flush=True)
        els = osm_api_map((w, s, e, n))
        meta = {"version": 0.6, "generator": "fetch_data.py (OSM API /map fallback)",
                "osm3s": {"copyright": "The data included in this document is from www.openstreetmap.org. The data is made "
                                       "available under ODbL."}}
        json.dump(dict(meta, elements=els), open(C.RESEARCH / "osm_all.json", "w"))
        json.dump(dict(meta, elements=golf_only(els)), open(C.RESEARCH / "osm_golf.json", "w"))
    print("osm ok")


def fetch_imagery():
    e = C.FETCH_CORE; m = 20  # the course extent in both profiles (they share data/<slug>/)
    dst = C.IMAGERY_RAW
    if dst.exists():
        return
    import sources
    mod, spec = sources.provider("imagery")
    mod.fetch(spec, e["xmin"] - m, e["ymin"] - m, e["xmax"] + m, e["ymax"] + m, C.IMAGERY_RES, dst, bands=tuple(spec["bands"]))


if __name__ == "__main__":
    what = sys.argv[1:] or ["lidar", "osm", "imagery"]
    if "lidar" in what:
        fetch_lidar()
    if "osm" in what:
        fetch_osm()
    if "imagery" in what:
        fetch_imagery()
