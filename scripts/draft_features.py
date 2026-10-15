"""Draft the golf features of a course OSM does not map (Brambles), from the 4-band photo (R, G, B, NIR) and, when the
rasters step has run, the LiDAR (canopy height to drop trees and roofs, DEM to confirm bunkers are hollows). Seeds:
the lines of play (courses/<slug>/features/golf.geojson, golf=hole) and the GPS layout points
(courses/<slug>/research/layout.geojson: tee points per tee set, green front / centre / back).

  turf      bright, high-NIR, smooth ground (zoysia tee to green at Brambles): fairways once greens and tees are cut out
  greens    region grown from each green-centre point in colour + NIR; the largest colour threshold whose region stays
            within 1.5 x the GPS green radius (half its front-back depth); else the GPS disc itself
  tees      turf within tee_r of each tee point (the tee sets of a hole merge where their pads overlap)
  bunkers   bare (NDVI ~0), bright sand near the turf, compact (paths of the same gravel are long and thin), and a
            LiDAR hollow when the DEM exists
  water     dark, low-NIR ground
  paths     centre lines of the long thin strips of the same bare gravel (golf=cartpath, surface=gravel)
  outline   leisure=golf_course: the hole corridors and the turf, closed

The draft replaces the previous one in features/golf.geojson (features tagged draft=yes); features drawn by hand (no
draft tag) are kept. vectorize treats drafted bunkers as training labels, not survey data: the photo bunkers over
them get the LiDAR test of unmapped ones (vectorize.survey_bunkers), hand-drawn ones do not. Review sheets per hole: build/<slug>/draft/hole_NN.jpg. Thresholds: course.toml [draft]
(sections turf, green, tee, sand, water, outline, path), defaults below.

  COURSE=brambles python scripts/draft_features.py
"""
import json, sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize, shapes
from rasterio.warp import reproject, Resampling
from scipy import ndimage
from shapely.geometry import Point, Polygon, mapping, shape
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).parent))
import config as C

DEFAULTS = {
    "turf": dict(nir_min=205.0, L_min=60.0, b_min=18.0, tex_max=6.0, min_area=400.0, chm_max=1.0),
    "green": dict(thresholds=[3, 4, 5, 6, 7, 8], max_outside=0.04, max_area_ratio=1.6, weights=[1.0, 1.5, 1.0, 0.235],
                  radius=15.0),
    "tee": dict(radius=6.0, min_area=20.0),
    "sand": dict(ndvi_max=0.005, L_min=58.0, a_min=-8.0, b_min=6.0, b_max=23.0, near_turf=25.0, min_area=8.0,
                 max_elong=6.0, hollow=0.15),
    "water": dict(L_max=40.0, nir_max=90.0, min_area=50.0),
    "outline": dict(corridor=45.0, close=30.0),
    "path": dict(min_len=25.0, width=[1.5, 7.0], gap=15.0),
}


def params():
    out = {k: dict(v) for k, v in DEFAULTS.items()}
    for k, v in getattr(C, "DRAFT", {}).items():
        out.setdefault(k, {}).update(v)
    return out


def _px(m, res):
    return max(1, int(round(m / res)))


def _components(mask, min_px):
    lab, n = ndimage.label(mask)
    if not n:
        return mask.copy()
    size = ndimage.sum(mask, lab, range(1, n + 1))
    keep = np.zeros(n + 1, bool); keep[1:] = size >= min_px
    return keep[lab]


def turf_mask(nir, L, b, res, prm):
    """Maintained turf: NIR, lightness and yellowness above their minimum and smooth (local std of L below tex_max).
    The texture test keeps tree crowns and scrub out but also eats the turf edge, so the colour mask is kept within
    2 px of the smooth core."""
    s = 0.9 / res
    Ls, bs, ns = (ndimage.gaussian_filter(a, s) for a in (L, b, nir))
    m1 = ndimage.gaussian_filter(L, 2.0); m2 = ndimage.gaussian_filter(L * L, 2.0)
    tex = np.sqrt(np.maximum(m2 - m1 * m1, 0))
    colour = (ns >= prm["nir_min"]) & (Ls >= prm["L_min"]) & (bs >= prm["b_min"])
    core = colour & (tex < prm["tex_max"])
    core = ndimage.binary_opening(core, iterations=_px(1.2, res))
    core = ndimage.binary_closing(core, iterations=_px(1.8, res))
    core = _components(core, prm["min_area"] / res ** 2)
    m = (colour & ndimage.binary_dilation(core, iterations=2)) | core
    return _components(m, prm["min_area"] / res ** 2)


def _seed_component(m, seed):
    lab, _ = ndimage.label(m)
    k = lab[seed]
    return (lab == k) if k else np.zeros_like(m)


def grow_green(F, seed, r0_px, thresholds, max_outside, max_area_ratio):
    """Region grown from `seed` (row, col) in the feature stack F (H, W, k): the pixels within a colour distance t of
    the median around the seed, connected to it, holes filled, opened. Returns (mask, t) for the largest threshold t
    whose region has at most max_outside of its pixels beyond 1.5 r0_px and at most max_area_ratio x the disc area;
    (the GPS disc, None) when no threshold qualifies."""
    H, W = F.shape[:2]
    yy, xx = np.mgrid[:H, :W]
    rr = np.hypot(yy - seed[0], xx - seed[1])
    core = rr <= max(2.0, 0.3 * r0_px)
    med = np.median(F[core], 0)
    dE = np.sqrt(((F - med) ** 2).sum(-1))
    best = None
    for t in sorted(thresholds):
        m = _seed_component(dE < t, seed)
        if not m.any():
            continue
        m = ndimage.binary_opening(ndimage.binary_fill_holes(m), iterations=2)
        if not m[seed]:
            continue
        m = _seed_component(m, seed)
        n = m.sum()
        if (m & (rr > 1.5 * r0_px)).sum() <= max_outside * n and n <= max_area_ratio * np.pi * r0_px ** 2:
            best = (m, t)
    return best if best else (rr <= r0_px, None)


def compact_blobs(mask, res, min_area, max_elong):
    """Components at least min_area m2 whose skeleton length^2 / area is at most max_elong (a bunker is compact; a
    gravel path of the same colour is long and thin)."""
    from skimage.morphology import skeletonize
    lab, n = ndimage.label(mask)
    keep = np.zeros(n + 1, bool)
    for i, sl in enumerate(ndimage.find_objects(lab)):
        comp = lab[sl] == i + 1
        area = comp.sum() * res * res
        if area < min_area:
            continue
        skel = skeletonize(np.pad(comp, 1)).sum() * res
        keep[i + 1] = skel * skel / area <= max_elong
    return keep[lab]


def path_lines(mask, T, min_len, width, max_elong, gap=0.0):
    """Centre lines of the bare strips that are not compact blobs (gravel tracks and paths): trace_paths.centrelines
    over the components compact_blobs rejects, aligned pieces up to `gap` m apart joined, then at least min_len m."""
    from trace_paths import centrelines, bridge
    res = abs(T.a)
    strips = mask & ~compact_blobs(mask, res, 0.0, max_elong)
    lines = centrelines(strips, T, min_len=6.0, width=tuple(width))
    if gap:
        lines = bridge(lines, max_gap=gap, max_angle=35.0)
    return sorted([g for g in lines if g.length >= min_len], key=lambda g: (-round(g.length, 2), g.bounds))


def is_hollow(dem, mask, res, ring_m=2.0, depth=0.15):
    """The mean ground inside `mask` lies at least `depth` m below the median of a ring_m wide ring around it."""
    ring = ndimage.binary_dilation(mask, iterations=_px(ring_m, res)) & ~mask
    v = dem[mask]; r = dem[ring]
    v, r = v[np.isfinite(v)], r[np.isfinite(r)]
    if not len(v) or not len(r):
        return False
    return float(v.mean()) <= float(np.median(r)) - depth


def layout_points(path):
    """{hole: {"tees": {tee key: (x, y)}, "green": (x, y) or None, "depth": front-back distance (m) or None}}."""
    out = {}
    for f in json.load(open(path))["features"]:
        p = f["properties"]; xy = tuple(float(v) for v in f["geometry"]["coordinates"][:2])
        h = out.setdefault(int(p["hole"]), {"tees": {}, "green": None, "depth": None, "_fb": {}})
        if p["kind"] == "tee":
            h["tees"][p["tee"]] = xy
        elif p["kind"] == "green_center":
            h["green"] = xy
        elif p["kind"] in ("green_front", "green_back"):
            h["_fb"][p["kind"]] = xy
    for h in out.values():
        fb = h.pop("_fb")
        if len(fb) == 2:
            (x0, y0), (x1, y1) = fb["green_front"], fb["green_back"]
            h["depth"] = round(float(np.hypot(x1 - x0, y1 - y0)), 2)
    return out


def mask_polys(mask, T, simplify=0.2):
    """Polygons (pixel-edge outlines, simplified) of a boolean mask on the grid with transform T, largest first."""
    if not mask.any():
        return []
    gs = [shape(s) for s, v in shapes(mask.astype(np.uint8), mask=mask, transform=T, connectivity=4) if v == 1]
    u = unary_union(gs)
    out = [p.simplify(simplify) for p in getattr(u, "geoms", [u]) if p.geom_type == "Polygon"]
    return sorted([p for p in out if p.is_valid and not p.is_empty], key=lambda p: (-round(p.area, 2), p.bounds))


def outline(lines, polys, corridor, close):
    """leisure=golf_course outline: the lines of play buffered by `corridor` m, with the turf, closed by `close` m and
    without holes."""
    u = unary_union([l.buffer(corridor) for l in lines] + list(polys))
    u = u.buffer(close).buffer(-close)
    parts = [Polygon(p.exterior) for p in getattr(u, "geoms", [u]) if p.geom_type == "Polygon"]
    return unary_union(parts)


def merge(fc, drafted):
    """features/golf.geojson with the previous draft (draft=yes) replaced by `drafted`; hand-drawn features kept."""
    keep = [f for f in fc.get("features", []) if f.get("properties", {}).get("draft") != "yes"]
    return dict(fc, features=keep + list(drafted))


def _feature(geom, **props):
    def rnd(o):
        if isinstance(o, (list, tuple)):
            return [rnd(v) for v in o]
        return round(float(o), 2)
    g = mapping(geom)
    return {"type": "Feature", "properties": dict(props, draft="yes"),
            "geometry": {"type": g["type"], "coordinates": rnd(g["coordinates"])}}


def _smooth(p, r=0.6, simp=0.3):
    q = p.buffer(r, join_style=1).buffer(-r, join_style=1).simplify(simp)
    return q if not q.is_empty else p


def _on_photo(path, T, shape_, resampling):
    out = np.full(shape_, np.nan, np.float32)
    with rasterio.open(path) as ds:
        reproject(rasterio.band(ds, 1), out, src_transform=ds.transform, src_crs=ds.crs, dst_transform=T,
                  dst_crs=ds.crs, resampling=resampling, src_nodata=ds.nodata, dst_nodata=np.nan)
    return out


def sheets(img, T, lines, layers, out_dir):
    """One review image per hole: the photo with the draft (green red, tee white, bunker magenta, water blue, fairway
    cyan, outline yellow, path grey), the line of play and a 20 m grid."""
    from PIL import Image, ImageDraw
    out_dir.mkdir(parents=True, exist_ok=True)
    rgb = np.clip(np.moveaxis(img[:3], 0, -1), 0, 255).astype(np.uint8)
    col = {"fairway": (0, 230, 255), "green": (255, 40, 40), "tee": (255, 255, 255), "bunker": (255, 0, 255),
           "water": (40, 90, 255), "outline": (255, 230, 0), "path": (210, 210, 210)}
    inv = ~T
    for ref, line in sorted(lines.items()):
        x0, y0, x1, y1 = line.buffer(60).bounds
        c0, r0 = (int(v) for v in inv * (x0, y1)); c1, r1 = (int(v) for v in inv * (x1, y0))
        c0, r0 = max(c0, 0), max(r0, 0); c1, r1 = min(c1, rgb.shape[1]), min(r1, rgb.shape[0])
        sc = min(3.0, 1100 / max(c1 - c0, r1 - r0))
        im = Image.fromarray(rgb[r0:r1, c0:c1]).resize((int((c1 - c0) * sc), int((r1 - r0) * sc)), Image.BILINEAR)
        dr = ImageDraw.Draw(im)
        def px(x, y):
            c, r = inv * (x, y)
            return ((c - c0) * sc, (r - r0) * sc)
        for gx in np.arange(np.ceil(x0 / 20) * 20, x1, 20):
            dr.line([px(gx, y0), px(gx, y1)], fill=(0, 0, 0), width=1)
        for gy in np.arange(np.ceil(y0 / 20) * 20, y1, 20):
            dr.line([px(x0, gy), px(x1, gy)], fill=(0, 0, 0), width=1)
        for kind, geoms in layers.items():
            for g in geoms:
                for p in getattr(g, "geoms", [g]):
                    if p.geom_type == "Polygon":
                        dr.line([px(*xy) for xy in p.exterior.coords], fill=col[kind], width=2)
                    elif p.geom_type == "LineString":
                        dr.line([px(*xy) for xy in p.coords], fill=col[kind], width=3)
        dr.line([px(*xy) for xy in line.coords], fill=(255, 140, 0), width=1)
        dr.text((6, 6), f"hole {ref}  grid 20 m  E{x0:.0f} N{y1:.0f}", fill=(255, 255, 0))
        im.save(out_dir / f"hole_{int(ref):02d}.jpg", quality=88)


def main():
    from skimage.color import rgb2lab
    prm = params()
    fc_path = C.SOURCES / "golf.geojson"
    fc = json.load(open(fc_path))
    lines = {f["properties"]["ref"]: shape(f["geometry"]) for f in fc["features"]
             if f["properties"].get("golf") == "hole" and f["properties"].get("draft") != "yes"}
    lay = layout_points(C.RESEARCH / "layout.geojson")
    src = C.IMAGERY if C.IMAGERY.exists() else C.IMAGERY_RAW
    with rasterio.open(src) as ds:
        img = ds.read().astype(np.float32); T = ds.transform
    res = T.a
    if img.shape[0] < 4:
        sys.exit(f"draft_features: {src} has no NIR band")
    lab = rgb2lab(np.moveaxis(img[:3], 0, -1) / 255.0).astype(np.float32)
    L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
    nir, red = img[3], img[0]
    chm = dem = None
    if (C.BUILD / "chm.tif").exists():
        chm = _on_photo(C.BUILD / "chm.tif", T, L.shape, Resampling.max)
    if (C.BUILD / "dem.tif").exists():
        dem = _on_photo(C.BUILD / "dem.tif", T, L.shape, Resampling.average)
    print(f"photo {src.name} {L.shape[1]}x{L.shape[0]} @ {res} m; LiDAR: chm {chm is not None}, dem {dem is not None}")

    def burn(geoms, buf=0.0):
        gs = [g.buffer(buf) if buf else g for g in geoms]
        gs = [g for g in gs if not g.is_empty]
        return rasterize([(g, 1) for g in gs], out_shape=L.shape, transform=T, fill=0, dtype="uint8").astype(bool) \
            if gs else np.zeros(L.shape, bool)

    tp = prm["turf"]
    turf = turf_mask(nir, L, B, res, tp)
    if chm is not None:
        turf &= ~(np.nan_to_num(chm, nan=0.0) > tp["chm_max"])
    corridor = burn(list(lines.values()), prm["outline"]["corridor"])
    lb, n = ndimage.label(turf)
    hit = np.unique(lb[corridor & turf])
    keep = np.zeros(n + 1, bool); keep[hit[hit > 0]] = True
    turf = keep[lb]

    # greens
    gp = prm["green"]
    w = np.asarray(gp["weights"], np.float32)
    feats = np.dstack([ndimage.gaussian_filter(a, 1.2) * wi for a, wi in zip((L, A, B, nir), w)])
    inv = ~T
    greens = {}
    for hole, h in sorted(lay.items()):
        if not h["green"]:
            continue
        r0 = (h["depth"] / 2) if h["depth"] else gp["radius"]
        c, r = (int(v) for v in inv * h["green"])
        half = int((2.5 * r0 + 10) / res)
        r_0, c_0 = max(r - half, 0), max(c - half, 0)
        sub = feats[r_0:r + half, c_0:c + half]
        m, t = grow_green(sub, (r - r_0, c - c_0), r0 / res, gp["thresholds"], gp["max_outside"], gp["max_area_ratio"])
        full = np.zeros(L.shape, bool); full[r_0:r_0 + m.shape[0], c_0:c_0 + m.shape[1]] = m
        ps = [p for p in mask_polys(full, T) if p.buffer(1.0).contains(Point(h["green"]))] or mask_polys(full, T)[:1]
        greens[hole] = (_smooth(ps[0]), t)
        print(f"  green {hole:2d}: {greens[hole][0].area:6.0f} m2 (GPS disc {np.pi * r0 * r0:5.0f}) t={t}")
    green_m = burn([g for g, _ in greens.values()])

    # tees: the turf within radius of each tee point (or the disc where the photo shows none), merged per hole
    tq = prm["tee"]
    tees = []
    for hole, h in sorted(lay.items()):
        pads = []
        for key, xy in h["tees"].items():
            d = Point(xy).buffer(tq["radius"])
            t_m = burn([d]) & turf & ~green_m
            ps = [p for p in mask_polys(t_m, T) if p.area >= tq["min_area"]]
            pad = unary_union(ps).intersection(d) if ps else Point(xy).buffer(0.6 * tq["radius"])
            pads.append((key, pad))
        u = unary_union([p for _, p in pads])
        for part in getattr(u, "geoms", [u]):
            if part.geom_type != "Polygon":
                continue
            sets = [k for k, p in pads if p.intersects(part)]
            tees.append((hole, ",".join(sets), _smooth(part, 0.4, 0.2)))
    tee_m = burn([g for _, _, g in tees])

    # water
    wp = prm["water"]
    Ls = ndimage.gaussian_filter(L, 1.0); ns = ndimage.gaussian_filter(nir, 1.0)
    water_m = ndimage.binary_opening((Ls < wp["L_max"]) & (ns < wp["nir_max"]), iterations=2)
    if chm is not None:
        water_m &= ~(np.nan_to_num(chm, nan=0.0) > 1.0)
    water_m = _components(ndimage.binary_fill_holes(water_m), wp["min_area"] / res ** 2)

    # bunkers
    sp = prm["sand"]
    Bs = ndimage.gaussian_filter(B, 0.8); As = ndimage.gaussian_filter(A, 0.8); Ls8 = ndimage.gaussian_filter(L, 0.8)
    nd = ndimage.gaussian_filter((nir - red) / (nir + red + 1e-3), 0.8)
    near = ndimage.binary_dilation(turf | green_m, iterations=_px(sp["near_turf"], res))
    bare = (nd < sp["ndvi_max"]) & (Ls8 > sp["L_min"]) & (As > sp["a_min"]) & (Bs > sp["b_min"]) & (Bs < sp["b_max"])
    bare = ndimage.binary_opening(bare & ~green_m & ~tee_m & ~water_m, iterations=1)
    sand = compact_blobs(bare & near, res, sp["min_area"], sp["max_elong"])
    bunkers = []
    for p in mask_polys(sand, T, 0.15):
        if dem is not None and not is_hollow(dem, burn([p]), res, 2.0, sp["hollow"]):
            continue
        bunkers.append(_smooth(p, 0.3, 0.15))
    bunker_m = burn(bunkers)

    # fairways and the course outline
    fair_m = turf & ~ndimage.binary_dilation(green_m, iterations=_px(1.5, res)) & ~tee_m & ~water_m & ~bunker_m
    fair_m = _components(ndimage.binary_opening(fair_m, iterations=1), tp["min_area"] / res ** 2)
    fairways = [_smooth(p) for p in mask_polys(fair_m, T, 0.3)]
    op = prm["outline"]
    course = outline(list(lines.values()), fairways + [g for g, _ in greens.values()], op["corridor"], op["close"])
    waters = [p for p in mask_polys(water_m, T, 0.3) if course.intersection(p).area >= 0.5 * p.area]
    # gravel tracks and paths: the long thin bare strips on the course (the bunker colour, not compact)
    pp = prm["path"]
    paths = path_lines(bare & burn([course]), T, pp["min_len"], pp["width"], sp["max_elong"], pp["gap"])

    def hole_of(g):
        return max(lines, key=lambda k: lines[k].buffer(op["corridor"]).intersection(g).area)

    out = [_feature(course, leisure="golf_course", name=C.COURSE_NAME)]
    out += [_feature(g, golf="green", ref=str(h), draft_t=str(t) if t else "gps_disc") for h, (g, t) in sorted(greens.items())]
    out += [_feature(g, golf="tee", ref=str(h), tees=s) for h, s, g in tees]
    out += [_feature(g, golf="fairway", hole=hole_of(g)) for g in fairways if course.intersection(g).area >= 0.5 * g.area]
    out += [_feature(g, golf="bunker", hole=hole_of(g)) for g in bunkers if course.contains(g.centroid)]
    out += [_feature(g, natural="water", water="pond") for g in waters]
    out += [_feature(g, golf="cartpath", surface="gravel") for g in paths]
    merged = merge(fc, out)
    fc_path.write_text(json.dumps(merged, indent=1) + "\n")
    kinds = {}
    for f in out:
        k = f["properties"].get("golf") or f["properties"].get("natural") or f["properties"].get("leisure")
        kinds[k] = kinds.get(k, 0) + 1
    print(f"wrote {fc_path.relative_to(C.ROOT)}: draft {kinds}")
    layers = {"outline": [course], "fairway": fairways, "green": [g for g, _ in greens.values()],
              "tee": [g for _, _, g in tees], "bunker": bunkers, "water": waters, "path": paths}
    sheets(img, T, lines, layers, C.BUILD / "draft")
    print(f"review sheets in {(C.BUILD / 'draft').relative_to(C.ROOT)}")


if __name__ == "__main__":
    main()
