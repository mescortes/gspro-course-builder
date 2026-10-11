"""Fetch every input for the configured extent (idempotent; skips files that already exist).

  LiDAR    USGS 3DEP LPC tiles (TNM API) from the preferred project, covering config.CORE + margin
  OSM      golf / building / road features via Overpass (research/osm_all.json, research/osm_golf.json)
  Imagery  Esri World Imagery z20 over CORE + margin (data/imagery/esri_z20_core.tif)
  Backdrop handled by fetch_backdrop.py / build_backdrop.py
"""
import sys, json, time, subprocess, urllib.parse
from pathlib import Path
import requests
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).parent))
import config as C

UA = {"User-Agent": "mountain-gate-course-builder/0.1 (personal research)"}
LIDAR_PROJECT = "CA_2025LosAngelesPostWildfire_C25"   # newest, densest coverage (~41 pts/m2)
MARGIN = 15.0


def lonlat_bbox(e, margin=0.0):
    tr = Transformer.from_crs(C.CRS, "EPSG:4326", always_xy=True)
    xs = [e["xmin"] - margin, e["xmax"] + margin]; ys = [e["ymin"] - margin, e["ymax"] + margin]
    pts = [tr.transform(x, y) for x in xs for y in ys]
    return min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)


def fetch_lidar():
    w, s, e, n = lonlat_bbox(C.CORE, MARGIN)
    url = ("https://tnmaccess.nationalmap.gov/api/v1/products?datasets=" + urllib.parse.quote("Lidar Point Cloud (LPC)") +
           f"&bbox={w},{s},{e},{n}&max=200&outputFormat=JSON")
    items = requests.get(url, headers=UA, timeout=120).json().get("items", [])
    items = [i for i in items if LIDAR_PROJECT in i["downloadURL"]]
    # TNM returns everything touching the (lon/lat) query box; test real overlap in UTM, where tiles are aligned
    to_utm = Transformer.from_crs("EPSG:4326", C.CRS, always_xy=True)
    def overlaps(it):
        bb = it.get("boundingBox") or {}
        xs, ys = to_utm.transform([bb["minX"], bb["maxX"], bb["minX"], bb["maxX"]], [bb["minY"], bb["minY"], bb["maxY"], bb["maxY"]])
        # TNM boxes are padded by ~11 m around the 750 m UTM tile; shrink before testing overlap
        tx0, tx1, ty0, ty1 = min(xs) + 12, max(xs) - 12, min(ys) + 12, max(ys) - 12
        a = C.CORE
        return tx0 < a["xmax"] + MARGIN and tx1 > a["xmin"] - MARGIN and ty0 < a["ymax"] + MARGIN and ty1 > a["ymin"] - MARGIN
    items = [i for i in items if overlaps(i)]
    out = C.DATA / "lidar"; out.mkdir(parents=True, exist_ok=True)
    for it in items:
        dst = out / it["downloadURL"].split("/")[-1]
        if dst.exists() and dst.stat().st_size == it.get("sizeInBytes", dst.stat().st_size):
            continue
        print("downloading", dst.name, round(it.get("sizeInBytes", 0) / 1e6), "MB", flush=True)
        for attempt in range(5):
            try:
                with requests.get(it["downloadURL"], headers=UA, stream=True, timeout=(60, 600)) as r:
                    r.raise_for_status()
                    with open(dst, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                break
            except requests.RequestException as ex:
                print("  retry", attempt + 1, ex.__class__.__name__, flush=True); time.sleep(20 * (attempt + 1))
    print("lidar tiles:", len(items))


def overpass(query, path):
    for attempt in range(4):
        r = requests.post("https://overpass-api.de/api/interpreter", data={"data": query},
                          headers=dict(UA, Accept="application/json"), timeout=300)
        if r.status_code == 200 and r.text.lstrip().startswith("{"):
            Path(path).write_text(r.text); return
        time.sleep(10 * (attempt + 1))
    raise RuntimeError("overpass failed")


def fetch_osm():
    w, s, e, n = lonlat_bbox(C.CORE, 400)
    bb = f"{s},{w},{n},{e}"
    overpass(f'[out:json][timeout:180];(nwr({bb}););out geom;', C.ROOT / "research/osm_all.json")
    overpass(f'[out:json][timeout:180];(nwr({bb})["golf"];nwr({bb})["leisure"="golf_course"];);out geom;',
             C.ROOT / "research/osm_golf.json")
    print("osm ok")


def fetch_imagery():
    e = C.CORE; m = 20
    dst = C.IMAGERY
    if dst.exists():
        return
    subprocess.run([sys.executable, str(C.ROOT / "scripts/fetch_tiles.py"), "esri", "20", str(e["xmin"] - m), str(e["ymin"] - m),
                    str(e["xmax"] + m), str(e["ymax"] + m), "0.125", str(dst)], check=True)


if __name__ == "__main__":
    what = sys.argv[1:] or ["lidar", "osm", "imagery"]
    if "lidar" in what:
        fetch_lidar()
    if "osm" in what:
        fetch_osm()
    if "imagery" in what:
        fetch_imagery()
