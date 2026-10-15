"""USGS 3DEP lidar point clouds (public domain): LAZ tiles (LAS 1.4) of one project, listed by The National Map API.

  [sources.lidar]
  provider = "usgs_3dep"
  project = "CA_NorthCoastRanges_B23"   # the work unit's project name, as in the tile titles

The API pads its lon/lat boxes by ~11 m and lists every project, so tiles are kept by project name and by their box,
shrunk by `pad` m, overlapping the extent in the course CRS. Tile names do not mark a whole-km corner.
"""
from pyproj import Transformer
from sources import http

TNM = "https://tnmaccess.nationalmap.gov/api/v1/products"


def items(spec, ext, crs, margin=15.0, pad=20.0):
    """[(title, url)] of the project's tiles reaching ext + margin."""
    to_ll = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    to_xy = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    xs = (ext["xmin"] - margin, ext["xmax"] + margin); ys = (ext["ymin"] - margin, ext["ymax"] + margin)
    ll = [to_ll.transform(x, y) for x in xs for y in ys]
    bbox = ",".join(f"{v:.6f}" for v in (min(p[0] for p in ll), min(p[1] for p in ll), max(p[0] for p in ll), max(p[1] for p in ll)))
    out, offset = [], 0
    while True:
        r = http.requests.get(TNM, params=dict(datasets="Lidar Point Cloud (LPC)", bbox=bbox, max=200, offset=offset),
                              headers=http.UA, timeout=120)
        page = r.json()
        for it in page.get("items", []):
            if spec["project"] not in it.get("title", "") + it.get("downloadURL", ""):
                continue
            b = it["boundingBox"]
            corners = [to_xy.transform(x, y) for x in (b["minX"], b["maxX"]) for y in (b["minY"], b["maxY"])]
            x0 = min(c[0] for c in corners) + pad; x1 = max(c[0] for c in corners) - pad
            y0 = min(c[1] for c in corners) + pad; y1 = max(c[1] for c in corners) - pad
            if x0 < xs[1] and x1 > xs[0] and y0 < ys[1] and y1 > ys[0]:
                out.append((it["title"], it["downloadURL"]))
        offset += len(page.get("items", []))
        if not page.get("items") or offset >= page.get("total", 0):
            return sorted(set(out), key=lambda t: t[1])


def fetch(spec, ext, out, crs, margin=15.0):
    out.mkdir(parents=True, exist_ok=True)
    tiles = items(spec, ext, crs, margin)
    for _, u in tiles:
        http.download(u, out / u.split("/")[-1])
    if not tiles:
        print(f"lidar: no {spec['project']} tile reaches the extent", flush=True)
    return len(tiles)
