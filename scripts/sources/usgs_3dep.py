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
ACCEPT_ONLY = ("max_uncovered",)    # keys that accept or refuse a fetch, not choose its tiles (config.lidar_problems)


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
    """(share, gaps) of ext + margin outside every box, sampled every `step` m; (0.0, []) when covered. Each connected
    gap is ((x0, y0, x1, y1), edges): the box of its samples (padded by half a sample) and the edges of the extent it
    lies along, the largest gap first. The boxes are the listed ones, a few metres too big, so two abutting tiles leave
    no sliver between them."""
    from scipy import ndimage
    (ax, bx), (ay, by) = _read_box(ext, margin)
    X, Y = np.meshgrid(np.linspace(ax, bx, int(math.ceil((bx - ax) / step)) + 1),
                       np.linspace(ay, by, int(math.ceil((by - ay) / step)) + 1))
    inside = np.zeros(X.shape, bool)
    for x0, y0, x1, y1 in boxes:
        inside |= (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1)
    if inside.all():
        return 0.0, []
    lab, n = ndimage.label(~inside, structure=np.ones((3, 3)))
    size = np.bincount(lab.ravel())
    hx, hy = (X[0, 1] - X[0, 0]) / 2, (Y[1, 0] - Y[0, 0]) / 2
    gaps = []
    for i in sorted(range(1, n + 1), key=lambda i: -size[i]):
        g = lab == i
        rows, cols = np.nonzero(g)
        h, w = rows.max() - rows.min() + 1, cols.max() - cols.min() + 1
        # (samples on the edge, depth away from it): a gap lies along an edge it runs at least as far as it is deep
        runs = dict(north=(g[-1].sum(), h), south=(g[0].sum(), h), east=(g[:, -1].sum(), w), west=(g[:, 0].sum(), w))
        touched = [e for e, (run, _) in runs.items() if run]
        gaps.append(((max(ax, X[0, cols.min()] - hx), max(ay, Y[rows.min(), 0] - hy), min(bx, X[0, cols.max()] + hx),
                      min(by, Y[rows.max(), 0] + hy)), [e for e in touched if runs[e][0] >= runs[e][1]] or touched))
    return float((~inside).mean()), gaps


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
    share, gaps = uncovered([b for _, _, b in tiles], ext, margin)
    if share > spec.get("max_uncovered", 0.0):
        (x0, y0, x1, y1), edges = gaps[0]
        where = (f"{len(gaps)} gaps, the largest " if len(gaps) > 1 else "") + f"E {x0:.0f}-{x1:.0f} N {y0:.0f}-{y1:.0f}"
        where += (f" on its {' and '.join(', '.join(edges).rsplit(', ', 1))} edge{'s' * (len(edges) > 1)}" if edges
                  else " inside it")
        sys.exit(f"lidar: the {spec['project']} tiles leave {f'{share:.1%}' if share >= 0.001 else 'under 0.1%'} of the "
                 f"extent ([frame] core + {margin:g} m) uncovered ({where}): set [sources.lidar] project in course.toml "
                 f"to one that covers the course or, if that part is open water or out of play, allow it with "
                 f"[sources.lidar] max_uncovered = {math.ceil(share * 100) / 100}")
    for _, u, _ in tiles:
        http.download(u, out / u.split("/")[-1])
    store.write_tiles(out, spec, ext, [u.split("/")[-1] for _, u, _ in tiles])
    return len(tiles)
