"""USGS 3DEP lidar point clouds (public domain): LAZ tiles (LAS 1.4) of one project, listed by The National Map API.

  [sources.lidar]
  provider = "usgs_3dep"
  project = "CA_NorthCoastRanges_B23"   # the work unit's project name, as in the tile titles
  max_uncovered = 0.0                   # optional: share of the extent the tiles may leave uncovered (open water ...)

The API lists every project's tiles in lon/lat boxes; projected back they are about tile side x sin(grid
convergence) too big per side (~5 m at Brambles). Tiles are kept by project name and by their box, shrunk by `pad`
m, overlapping the extent + margin in the course CRS. Tile names do not mark a whole-km corner.

The listing comes in pages: a page that answers an error (or an HTML gateway page) is retried, never taken for the end
of the listing. The fetch stops when no tile of the project reaches the extent (naming the projects listed there) and
when the tiles leave part of the extent uncovered, before downloading anything. The fetched tiles are listed in
<out>/tiles.json.
"""
import math, sys
import numpy as np
from pyproj import Transformer
from sources import http, store

TNM = "https://tnmaccess.nationalmap.gov/api/v1/products"
TITLE = "USGS Lidar Point Cloud "   # tile titles: TITLE + project + " " + tile id


def _read_box(ext, margin):
    return (ext["xmin"] - margin, ext["xmax"] + margin), (ext["ymin"] - margin, ext["ymax"] + margin)


def listing(ext, crs, margin=15.0):
    """Every point-cloud item The National Map lists over ext + margin, all pages."""
    to_ll = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    xs, ys = _read_box(ext, margin)
    ll = [to_ll.transform(x, y) for x in xs for y in ys]
    bbox = ",".join(f"{v:.6f}" for v in (min(p[0] for p in ll), min(p[1] for p in ll), max(p[0] for p in ll), max(p[1] for p in ll)))
    out, offset = [], 0
    while True:
        # a page with no items before `total` is reached is an error reply ({"errorMessage": ...}), not the end
        page = http.get_json(TNM, dict(datasets="Lidar Point Cloud (LPC)", bbox=bbox, max=200, offset=offset),
                             valid=lambda p: isinstance(p, dict) and isinstance(p.get("items"), list)
                             and (bool(p["items"]) or offset >= p.get("total", 0)))
        out += page["items"]
        offset += len(page["items"])
        if not page["items"] or offset >= page.get("total", 0):
            return out


def project(title):
    """The project name in a tile title."""
    return title.removeprefix(TITLE).rsplit(" ", 1)[0]


def keep(spec, its, ext, crs, margin=15.0, pad=5.0):
    """[(title, url, box)] of the project's items whose box (in the course CRS, as listed: a few metres too big) shrunk
    by `pad` overlaps ext + margin, sorted by URL."""
    to_xy = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    xs, ys = _read_box(ext, margin)
    out = {}
    for it in its:
        if spec["project"] not in it.get("title", "") + it.get("downloadURL", ""):
            continue
        b = it["boundingBox"]
        corners = [to_xy.transform(x, y) for x in (b["minX"], b["maxX"]) for y in (b["minY"], b["maxY"])]
        x0 = min(c[0] for c in corners); x1 = max(c[0] for c in corners)
        y0 = min(c[1] for c in corners); y1 = max(c[1] for c in corners)
        if x0 + pad < xs[1] and x1 - pad > xs[0] and y0 + pad < ys[1] and y1 - pad > ys[0]:
            out[it["downloadURL"]] = (it["title"], it["downloadURL"], (x0, y0, x1, y1))
    return [out[u] for u in sorted(out)]


def items(spec, ext, crs, margin=15.0, pad=5.0):
    """[(title, url)] of the project's tiles reaching ext + margin."""
    return [(t, u) for t, u, _ in keep(spec, listing(ext, crs, margin), ext, crs, margin, pad)]


def uncovered(boxes, ext, margin=15.0, step=10.0):
    """(share, (x0, y0, x1, y1)) of ext + margin outside every box, sampled every `step` m; (0.0, None) when covered.
    The boxes are the listed ones, a few metres too big, so two abutting tiles leave no sliver between them."""
    (ax, bx), (ay, by) = _read_box(ext, margin)
    X, Y = np.meshgrid(np.linspace(ax, bx, int(math.ceil((bx - ax) / step)) + 1),
                       np.linspace(ay, by, int(math.ceil((by - ay) / step)) + 1))
    inside = np.zeros(X.shape, bool)
    for x0, y0, x1, y1 in boxes:
        inside |= (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1)
    if inside.all():
        return 0.0, None
    out = ~inside
    return float(out.mean()), (X[out].min(), Y[out].min(), X[out].max(), Y[out].max())


def fetch(spec, ext, out, crs, margin=15.0):
    """Download the project's tiles reaching the extent into `out` and list them in out/tiles.json; returns their number."""
    out.mkdir(parents=True, exist_ok=True)
    try:
        its = listing(ext, crs, margin)
    except RuntimeError as ex:
        sys.exit(f"lidar: The National Map did not list the tiles ({ex}): rerun fetch_data.py lidar later")
    tiles = keep(spec, its, ext, crs, margin)
    if not tiles:
        there = sorted({project(it.get("title", "")) for it in its} - {""})
        sys.exit(f"lidar: no tile of project {spec['project']!r} reaches the extent. The National Map lists "
                 f"{', '.join(there) if there else 'no point cloud'} over it: set [sources.lidar] project in course.toml")
    share, where = uncovered([b for _, _, b in tiles], ext, margin)
    if share > spec.get("max_uncovered", 0.0):
        sys.exit(f"lidar: the {spec['project']} tiles leave {share:.0%} of the extent uncovered (E {where[0]:.0f}-"
                 f"{where[2]:.0f} N {where[1]:.0f}-{where[3]:.0f}): set [sources.lidar] project in course.toml to one that "
                 f"covers the course or, if that part is open water or out of play, allow it with [sources.lidar] "
                 f"max_uncovered = {math.ceil(share * 100) / 100}")
    for _, u, _ in tiles:
        http.download(u, out / u.split("/")[-1])
    store.write_tiles(out, spec, ext, [u.split("/")[-1] for _, u, _ in tiles])
    return len(tiles)
