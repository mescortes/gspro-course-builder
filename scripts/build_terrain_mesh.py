"""Conforming, crack-free terrain triangulation from the surface partition + LiDAR DEM.

All surface boundaries become constraint segments of a single constrained Delaunay triangulation, so the per-surface
meshes share identical boundary vertices (no T-junctions, no cracks). Triangle size depends on the surface and on
whether it lies in the detail zone around the focus hole.

Output: build/terrain_mesh.npz
  V      (n,3) float64  UTM easting, northing, height (config.CRS_LABEL)
  F      (m,3) int32
  surf   (m,)  int16    index into SURFACES
  hole   (m,)  int16
"""
import sys, json
import numpy as np
import rasterio
import triangle
import shapely
from shapely.geometry import shape, box, Polygon, MultiPolygon, LineString, MultiLineString
from shapely.ops import unary_union
from scipy import ndimage
from scipy.interpolate import RegularGridInterpolator

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C

SURFACES = ["rough", "semirough", "fairway", "fringe", "green", "tee", "bunker", "cartpath", "native", "road",
            "building", "court", "water", "deeprough", "bunkerlip", "wateredge"]  # last two: OPCD edge rings (edges.py)
SID = {n: i for i, n in enumerate(SURFACES)}
# max triangle area (m^2) inside the detail zone; outside it is multiplied by COARSE
MAX_AREA = {"green": 0.03, "fringe": 0.06, "tee": 0.12, "bunker": 0.08, "fairway": 0.25, "semirough": 0.3,
            "cartpath": 0.3, "native": 0.8, "deeprough": 1.0, "rough": 0.6, "road": 3.0, "building": 4.0, "court": 4.0, "water": 1.0,
            "bunkerlip": 0.03, "wateredge": 0.1}
COARSE = 6.0          # outside any hole zone
SCENERY = 2.5         # scenery holes (visible from play, not played)
FOCUS_HOLES = C.PLAYABLE
SCENERY_HOLES = tuple(C.SCENERY_HOLES)
DETAIL_BUFFER = 45.0


def load_features(path):
    gj = json.load(open(path))
    feats = []
    for f in gj["features"]:
        g = shape(f["geometry"])
        if g.is_empty:
            continue
        feats.append((g, f["properties"]["surface"], int(f["properties"].get("hole", 99))))
    return feats


def detail_zone(feats, holes=FOCUS_HOLES, buffer=DETAIL_BUFFER):
    """Union of per-hole zones (convex hull of each hole's features, buffered)."""
    zones = []
    for h in holes:
        g = [x for x, s, hh in feats if hh == h]
        if g:
            zones.append(unary_union(g).convex_hull.buffer(buffer, join_style=1))
    if not zones:
        return Polygon()
    return unary_union(zones).simplify(1.0)


def zone_rings(zone, aoi):
    z = zone.intersection(aoi)
    out = []
    for p in getattr(z, "geoms", [z]):
        if p.geom_type == "Polygon" and not p.is_empty:
            out.append(p.exterior); out.extend(p.interiors)
    return out


def build_pslg(feats, aoi, zone, tol_in=0.03, tol_out=0.2, zone2=None, grid=0.01):
    """Node all boundaries, simplify every shared edge exactly once (so neighbours stay consistent), emit a PSLG."""
    lines = [aoi.exterior]
    for g, _, _ in feats:
        for p in getattr(g, "geoms", [g]):
            lines.append(p.exterior)
            lines.extend(p.interiors)
    if not zone.is_empty:
        lines.extend(zone_rings(zone, aoi))
    if zone2 is not None and not zone2.is_empty:
        lines.extend(zone_rings(zone2, aoi))
    noded = unary_union([LineString(l.coords) for l in lines])
    merged = shapely.line_merge(noded)
    zone_b = zone.buffer(2.0) if not zone.is_empty else Polygon()
    simp = []
    for ls in getattr(merged, "geoms", [merged]):
        tol = tol_in if ls.intersects(zone_b) else tol_out
        g = ls.simplify(tol, preserve_topology=False)
        if g.length > 0:
            simp.append(g)
    # re-node (simplified edges may now touch/cross) and snap-round to a grid so no near-coincident vertices remain
    net = shapely.set_precision(unary_union(simp), grid)
    net = shapely.set_precision(unary_union(net), grid)
    segs = []
    for ls in getattr(net, "geoms", [net]):
        c = np.asarray(ls.coords)
        if len(c) < 2:
            continue
        segs.append(np.stack([c[:-1], c[1:]], 1))
    segs = np.concatenate(segs)
    pts = np.round((segs.reshape(-1, 2) - [C.ORIGIN_E, C.ORIGIN_N]) / grid) * grid
    uniq, inv = np.unique(pts, axis=0, return_inverse=True)
    S = inv.reshape(-1, 2)
    S = S[S[:, 0] != S[:, 1]]
    S = np.unique(np.sort(S, 1), axis=0)
    S = fix_needles(uniq, S)
    return uniq, S


def fix_needles(V, S, min_deg=1.0, max_iter=20):
    """Remove needle configurations Triangle cannot refine (two boundary segments leaving a vertex at < min_deg):
    the shorter segment's far end lies (almost) on the longer one, so split the longer segment there."""
    from collections import defaultdict
    segs = set(map(tuple, S.tolist()))
    for it in range(max_iter):
        inc = defaultdict(set)
        for a, b in segs:
            inc[a].add(b); inc[b].add(a)
        changed = 0
        for v, nb in inc.items():
            if len(nb) < 2:
                continue
            nb = list(nb)
            d = V[nb] - V[v]
            ang = np.arctan2(d[:, 1], d[:, 0])
            order = np.argsort(ang)
            a_s = ang[order]
            gaps = np.degrees(np.diff(np.r_[a_s, a_s[0] + 2 * np.pi]))
            for k in np.flatnonzero(gaps < min_deg):
                i, j = nb[order[k]], nb[order[(k + 1) % len(order)]]
                near, far = (i, j) if np.linalg.norm(V[i] - V[v]) <= np.linalg.norm(V[j] - V[v]) else (j, i)
                e = (min(v, far), max(v, far))
                if e in segs and near != far:
                    segs.discard(e)
                    segs.add((min(near, far), max(near, far)))
                    changed += 1
                    break  # incidence changed: recompute next iteration
        if not changed:
            break
    out = np.array(sorted(segs), np.int64)
    print(f"needle fix: {len(S) - len(out):+d} segments after {it + 1} passes", flush=True)
    return out


def seed_point(q):
    inner = q.buffer(-0.35)
    if not inner.is_empty:
        big = max(getattr(inner, "geoms", [inner]), key=lambda x: x.area)
        return big.representative_point()
    return q.representative_point()


def label_faces(Vt, Ft, nbr, segs, feats):
    """Label triangles by majority vote of centroid-in-polygon over each constraint-bounded face."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    n = len(Ft); NV = len(Vt) + 1
    ss = np.sort(segs, 1).astype(np.int64); seg_keys = ss[:, 0] * NV + ss[:, 1]
    rows, cols = [], []
    t = np.arange(n)
    for k in range(3):
        u = nbr[:, k]
        e = np.sort(np.stack([Ft[:, (k + 1) % 3], Ft[:, (k + 2) % 3]], 1), 1).astype(np.int64)
        ok = (u >= 0) & ~np.isin(e[:, 0] * NV + e[:, 1], seg_keys)
        rows.append(t[ok]); cols.append(u[ok])
    rows = np.concatenate(rows); cols = np.concatenate(cols)
    g = coo_matrix((np.ones(len(rows), np.int8), (rows, cols)), shape=(n, n))
    _, roots = connected_components(g, directed=False)
    # point-in-polygon via a 0.125 m label raster of the non-rough polygons (rough = complement); exact enough for a
    # per-face majority vote and O(n) instead of an STRtree query per triangle
    from rasterio.features import rasterize
    fg = [(g, s, h) for g, s, h in feats if s != "rough"]
    s_of = np.r_[SID["rough"], [SID.get(s, 0) for _, s, _ in fg]].astype(np.int64)
    h_of = np.r_[99, [h for _, _, h in fg]].astype(np.int64)
    res = 0.125
    e = C.CORE
    Wr = int(round((e["xmax"] - e["xmin"]) / res)); Hr = int(round((e["ymax"] - e["ymin"]) / res))
    Tr = rasterio.transform.from_origin(e["xmin"], e["ymax"], res, res)
    lab_r = rasterize([(g, i + 1) for i, (g, _, _) in enumerate(fg)], out_shape=(Hr, Wr), transform=Tr, fill=0, dtype="int32")
    cent = Vt[Ft].mean(1) + [C.ORIGIN_E, C.ORIGIN_N]
    cc = np.clip(((cent[:, 0] - e["xmin"]) / res).astype(int), 0, Wr - 1)
    rr = np.clip(((e["ymax"] - cent[:, 1]) / res).astype(int), 0, Hr - 1)
    k = lab_r[rr, cc]
    del lab_r
    tri_s = s_of[k]; tri_h = h_of[k]
    # majority per face (weighted by triangle area)
    e1 = Vt[Ft[:, 1]] - Vt[Ft[:, 0]]; e2 = Vt[Ft[:, 2]] - Vt[Ft[:, 0]]
    a = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    nf = roots.max() + 1; ns = len(SURFACES)
    w = np.bincount(roots * ns + tri_s, weights=a, minlength=nf * ns).reshape(nf, ns)
    face_s = np.argmax(w, 1)
    win = tri_s == face_s[roots]
    # hole per face: most common hole among the triangles of the winning surface
    key = roots[win].astype(np.int64) * 128 + np.minimum(tri_h[win], 127)
    cnt = np.bincount(key, minlength=nf * 128).reshape(nf, 128)
    face_h = np.argmax(cnt, 1)
    face_h[cnt.max(1) == 0] = 99
    surf = face_s[roots].astype(np.int16); hole = face_h[roots].astype(np.int16)
    bounds = np.arange(nf + 1)
    print("faces", len(bounds) - 1, flush=True)
    return surf, hole


def height_field():
    with rasterio.open(C.BUILD / "dem.tif") as ds:
        dem = ds.read(1).astype(np.float64); T = ds.transform
    return dem, T


def level_tees(dem, T, tees, max_slope=0.01, deck_tol=0.06, deck_slope=0.035, max_area=500.0, bank=1 / 3,
               max_feather=8.0, flat_frac=0.8, protect=None, holes=None, neighbour_m=40.0, max_lift=2.5,
               enabled=True, warn_step=0.1):
    """In place: tees that are not decks in the LiDAR (built after the survey, e.g. Westmount's 2023 / 2025 back tees on
    holes 5, 8 and 11) get a synthetic deck - a plane of at most `max_slope` at the tee's mean height - blended into the
    surrounding ground. The feather (up to `max_feather` m) is wide enough that the banks are at most `bank` (rise / run)
    steeper than the ground (the smoothstep's peak gradient is 1.5x its mean); it never reaches into `protect` (a bool
    raster of paths, roads, buildings, greens, bunkers and water, which keep their height: QA round 2, hole 8).
    Where the feather stops at a protected surface the bank ends in a step: one over `warn_step` m is reported (the tee,
    its height, and the setting below). enabled=False ([tuning.level_tees] enabled = false): no synthetic decks at all,
    for a LiDAR flown after every tee was built (Brambles, 2023). There the drafted tee polygons take in the banks of the
    real decks, fail the deck tests and were cut and filled up to 1.5 m: by the 10th green the bank of the hole-7 back
    tee ended in a 1.0 m step at the fringe.

    Left alone:
    * a tee whose DEM already fits a plane within `deck_tol` m (std) and `deck_slope` (real decks fall 1.5-3 % for
      drainage);
    * a tee whose cells are at least `flat_frac` locally flat (<= `deck_slope`): several real decks merged into one
      polygon, with a step between them (QA round 2, hole 8 White / Red);
    * a polygon over `max_area` m2 (a digitising error, not a deck; flattening it would terrace a hillside - QA fixes
      the polygon instead).

    With `holes` (the hole of each tee): a new tee whose deck at the slope's mean would be cut into the hill (ground
    within 3 m of it more than 0.3 m higher) and that has a higher real deck of the same hole within `neighbour_m` m is
    built up (at most `max_lift` m) to that deck's level. Hole 8's 2025 Blue tee otherwise sat 1.7 m below the White
    deck beside it, in a hole. Decks are never lowered to a neighbour (hole 11's back tee would sink 2.2 m)."""
    from rasterio.features import rasterize
    from rasterio.windows import Window, transform as wtransform
    if not enabled:
        return dem
    H, W = dem.shape; r = abs(T.a)
    holes = list(holes) if holes is not None else [None] * len(tees)
    real = []   # (hole, polygon, deck height) of the tees that are real 2018 decks
    for p, hn in zip(tees, holes):
        if hn is None or p.area > max_area:
            continue
        x0, y0, x1, y1 = p.buffer(2).bounds
        c0 = max(0, int((x0 - T.c) / T.a)); c1 = min(W, int((x1 - T.c) / T.a) + 1)
        r0 = max(0, int((T.f - y1) / r)); r1 = min(H, int((T.f - y0) / r) + 1)
        if c1 <= c0 or r1 <= r0:
            continue
        sub = dem[r0:r1, c0:c1]
        m = rasterize([(p, 1)], out_shape=sub.shape, transform=wtransform(Window(c0, r0, c1 - c0, r1 - r0), T)).astype(bool)
        if m.sum() >= 20 and _is_real_deck(sub, m, r, deck_tol, deck_slope, flat_frac):
            real.append((hn, p, float(sub[m].mean())))
    for p, hn in zip(tees, holes):
        if p.area > max_area:
            print(f"level_tees: {p.area:.0f} m2 tee polygon at {p.centroid.x:.0f},{p.centroid.y:.0f} left alone (too big)",
                  flush=True)
            continue
        x0, y0, x1, y1 = p.buffer(max_feather + 1).bounds
        c0 = max(0, int((x0 - T.c) / T.a)); c1 = min(W, int((x1 - T.c) / T.a) + 1)
        r0 = max(0, int((T.f - y1) / r)); r1 = min(H, int((T.f - y0) / r) + 1)
        if c1 <= c0 or r1 <= r0:
            continue
        tw = wtransform(Window(c0, r0, c1 - c0, r1 - r0), T)
        inside = rasterize([(p, 1)], out_shape=(r1 - r0, c1 - c0), transform=tw).astype(bool)
        if inside.sum() < 20:
            continue
        sub = dem[r0:r1, c0:c1]
        if _is_real_deck(sub, inside, r, deck_tol, deck_slope, flat_frac):
            continue  # a real deck (or real decks with a step between them)
        yy, xx = np.nonzero(inside)
        A = np.c_[xx * r, yy * r, np.ones(len(xx))]
        coef, *_ = np.linalg.lstsq(A, sub[inside], rcond=None)
        g = np.array([coef[0], coef[1]]); s = np.hypot(*g)
        if s > max_slope:
            g *= max_slope / s
        cy, cx = yy.mean(), xx.mean()
        YY, XX = np.mgrid[0:r1 - r0, 0:c1 - c0]
        level = sub[inside].mean()
        near = [(p.distance(q), z) for h2, q, z in real if h2 == hn and hn is not None and q is not p and p.distance(q) <= neighbour_m]
        rim = (ndimage.distance_transform_edt(~inside) * r <= 3.0) & ~inside
        cut = float(sub[rim].max() - level) if rim.any() else 0.0      # how far the deck at the mean sits below the slope
        if near and cut > 0.3:
            z = min(near)[1]
            if level < z <= level + max_lift:
                print(f"level_tees: hole {hn} tee at {p.centroid.x:.0f},{p.centroid.y:.0f} cut {cut:.1f} m into the slope: "
                      f"built up to its neighbouring deck ({level:.2f} -> {z:.2f} m)", flush=True)
                level = z
        plane = level + g[0] * (XX - cx) * r + g[1] * (YY - cy) * r
        feather = float(np.clip(1.5 * np.abs(plane - sub)[inside].max() / bank, 1.0, max_feather))
        d = ndimage.distance_transform_edt(~inside) * r
        w = np.clip(1 - d / feather, 0, 1); w = w * w * (3 - 2 * w)   # smoothstep feather
        w = np.maximum(ndimage.gaussian_filter(w, 0.35 / r, truncate=2.0), inside)   # no radial streaks (distance transform)
        if protect is not None:
            pr = protect[r0:r1, c0:c1]
            w[pr & ~inside] = 0.0
            # the cells beside a protected one carry the bank's change in height; the protected cell keeps its own
            edge = ~pr & ndimage.binary_dilation(pr)
            step = float((np.abs(plane - sub) * w)[edge].max()) if edge.any() else 0.0
            if step > warn_step:
                print(f"level_tees: {'hole ' + str(hn) + ' ' if hn is not None else ''}tee at {p.centroid.x:.0f},"
                      f"{p.centroid.y:.0f}: its synthetic deck ends in a {step:.2f} m step where it meets a path, green, "
                      f"bunker, road, building or water (they keep their height). Check the tee outline in the QA "
                      f"images (one that takes in a bank is cut and filled); a course whose LiDAR was flown after every "
                      f"tee was built needs no synthetic decks: [tuning.level_tees] enabled = false in course.toml",
                      flush=True)
        dem[r0:r1, c0:c1] = sub * (1 - w) + plane * w
    return dem


def _is_real_deck(sub, m, r, deck_tol, deck_slope, flat_frac):
    """level_tees' test for a tee (mask m on the DEM window sub) that already is a deck in the LiDAR: one plane within
    deck_tol and deck_slope, or locally flat cells (real decks with a step between them)."""
    yy, xx = np.nonzero(m)
    A = np.c_[xx * r, yy * r, np.ones(len(xx))]
    coef, *_ = np.linalg.lstsq(A, sub[m], rcond=None)
    if np.std(sub[m] - A @ coef) < deck_tol and np.hypot(coef[0], coef[1]) <= deck_slope:
        return True
    core = ndimage.binary_erosion(m, iterations=max(1, int(1.0 / r)))
    if core.sum() >= 20:
        gy, gx = np.gradient(ndimage.gaussian_filter(sub, 0.5 / r), r)
        return bool(np.mean(np.hypot(gx, gy)[core] <= deck_slope) >= flat_frac)
    return False


def blended_dem(dem, T, feats):
    """Extra smoothing on putting surfaces, tees and paths (LiDAR noise would read as bumps), blended smoothly.

    Inside a surface the DEM is replaced by a masked (normalised) Gaussian smooth, so the edge does not pull in outside
    heights (a bunker hollow next to a green). A masked smooth is biased toward the interior near the edge on a slope;
    that bias is removed by smoothing the residual from a large-scale, unmasked trend (exact for planes). Outside the
    surface only the smoothing *correction* is carried on, fading continuously, so banks keep their own shape and there
    is no step where the smooth ends (QA round 2: 6-8 cm rings ~1.5 m outside the fringes)."""
    from rasterio.features import rasterize
    H, W = dem.shape; r = T.a
    def mask(names):
        gs = [g for g, s, _ in feats if s in names]
        return rasterize([(g, 1) for g in gs], out_shape=(H, W), transform=T, fill=0, dtype="uint8").astype(np.float64) if gs else np.zeros((H, W))
    trend = ndimage.gaussian_filter(dem, 1.5 / r)
    resid = dem - trend
    out = dem.copy()
    for names, sigma_m, feather in ((("green", "fringe"), 0.45, 1.0), (("tee",), 0.6, 0.75), (("cartpath",), 0.6, 0.5),
                                     (("bunker",), 0.35, 0.3)):
        m = mask(names)
        if not m.any():
            continue
        inside = m > 0
        den = ndimage.gaussian_filter(m, sigma_m / r)
        delta = ndimage.gaussian_filter(resid * m, sigma_m / r) / np.maximum(den, 1e-6) - resid  # smooth - dem
        delta[~inside] = 0.0
        gm = ndimage.gaussian_filter(m, feather / r)
        # outside: the edge correction spread out and decaying to 0 (max(.., 0.5) keeps it continuous at the edge)
        ext = ndimage.gaussian_filter(delta, feather / r) / np.maximum(gm, 0.5)
        corr = np.where(inside, delta, ext)
        w = np.clip(2.0 * gm, 0, 1)  # 1 inside and on the edge, fades outside
        out = out * (1 - w) + (dem + corr) * w
        del den, delta, gm, ext, corr, w
    # tees with no LiDAR deck (built after the 2018 survey) get a synthetic one
    out = level_tees(out, T, [g for g, s, _ in feats if s == "tee"], holes=[h for g, s, h in feats if s == "tee"],
                     protect=mask(("cartpath", "road", "building", "green", "fringe", "bunker", "water")) > 0,
                     **C.tuning("level_tees", {}))
    # water: a flat water level per body (lowest ~20 % of the shoreline); under it a shelving bed (OPCD Water_Base),
    # and the banks inside the WaterPlane's outset kept above the water
    import edges
    for p, level, _ in edges.water_levels(feats, dem, T):
        edges.carve_water(out, T, p, level)
    return out


def main(features_path=None):
    features_path = features_path or (C.FEATURES / "course_surfaces.geojson")
    import edges
    feats0 = load_features(features_path)
    aoi = box(C.CORE["xmin"], C.CORE["ymin"], C.CORE["xmax"], C.CORE["ymax"])
    zone = detail_zone(feats0)
    zone2 = detail_zone(feats0, SCENERY_HOLES, 25.0).difference(zone)
    # OPCD edge rings (bunker lips, water edge bands) are meshed as their own surfaces
    feats, rings = edges.derive_rings(feats0, zone)
    print("features", len(feats), "edge rings", len(rings), "detail zone area", round(zone.area), "scenery zone", round(zone2.area))
    grids = (0.01, 0.03, 0.06)
    V2, S = build_pslg(feats, aoi, zone, zone2=zone2, grid=grids[0])
    print("pslg vertices", len(V2), "segments", len(S), flush=True)

    # regions: one seed per (polygon, zone-side) piece
    regions = []
    meta = []
    for g, s, h in feats:
        for p in getattr(g, "geoms", [g]):
            rest = p.difference(zone)
            for piece, factor in ((p.intersection(zone), 1.0), (rest.intersection(zone2), SCENERY), (rest.difference(zone2), COARSE)):
                for q in getattr(piece, "geoms", [piece]):
                    if q.is_empty or q.geom_type != "Polygon" or q.area < 0.5 or q.buffer(-0.35).is_empty:
                        continue  # slivers may collapse during edge simplification; their seed would leak
                    rp = seed_point(q)
                    a = MAX_AREA.get(s, 1.0) * factor
                    regions.append([rp.x - C.ORIGIN_E, rp.y - C.ORIGIN_N, len(meta), a])
                    meta.append((SID.get(s, 0), h))
    regions = np.array(regions, np.float64)
    print("regions", len(regions), flush=True)
    for gi, grid in enumerate(grids):
        try:
            tri = triangle.triangulate({"vertices": V2, "segments": S, "regions": regions}, "pq25Aan")
            break
        except RuntimeError as ex:
            if gi == len(grids) - 1:
                raise
            # pathological near-coincident boundaries: snap-round on a coarser grid and retry
            print(f"triangulation failed on a {grid * 100:.0f} cm grid ({ex}); retrying on {grids[gi + 1] * 100:.0f} cm", flush=True)
            V2, S = build_pslg(feats, aoi, zone, zone2=zone2, grid=grids[gi + 1])
    Vt = tri["vertices"]; Ft = tri["triangles"].astype(np.int32)
    surf, hole = label_faces(Vt, Ft, tri["neighbors"], tri["segments"], feats)
    surf, hole = edges.label_rings(Vt[Ft].mean(1) + [C.ORIGIN_E, C.ORIGIN_N], surf, hole, rings, SID)
    print("triangles", len(Ft), "vertices", len(Vt), flush=True)

    dem, T = height_field()
    demb = blended_dem(dem, T, feats0)
    # water planes (flat, outset under the banks) for the export
    planes = [{"hole": int(h), "level": round(lv, 3), "polygon_utm": [[round(x, 2), round(y, 2)] for x, y in
               edges.water_plane_polygon(p, demb, T, lv).exterior.coords]}
              for p, lv, h in edges.water_levels(feats0, dem, T) if p.area >= 20]
    json.dump(planes, open(C.BUILD / "water_planes.json", "w"))
    print("water planes", len(planes), flush=True)
    # the surface the meshes are built from (extra smoothing on greens/tees/paths) -> used by maps, heightmap, hole data
    with rasterio.open(C.BUILD / "dem.tif") as src:
        prof = src.profile
    with rasterio.open(C.BUILD / "dem_final.tif", "w", **prof) as dst:
        dst.write((demb - edges.lip_drop_raster(rings, T, demb.shape)).astype(np.float32), 1)
    H, W = dem.shape
    xs = T.c + (np.arange(W) + 0.5) * T.a - C.ORIGIN_E
    ys = T.f + (np.arange(H) + 0.5) * T.e - C.ORIGIN_N
    interp = RegularGridInterpolator((ys[::-1], xs), demb[::-1], bounds_error=False, fill_value=None)
    z = interp(np.c_[Vt[:, 1], Vt[:, 0]])
    # bunker lips: the sand drops LIP_DEPTH across the 10 cm lip (exact at the vertices; the raster gets it too)
    z -= edges.lip_drop(Vt + [C.ORIGIN_E, C.ORIGIN_N], rings)
    V = np.c_[Vt[:, 0] + C.ORIGIN_E, Vt[:, 1] + C.ORIGIN_N, z]
    np.savez_compressed(C.BUILD / "terrain_mesh.npz", V=V, F=Ft, surf=surf, hole=hole, surfaces=np.array(SURFACES))
    from collections import Counter
    cnt = Counter(SURFACES[s] for s in surf)
    print({k: v for k, v in cnt.most_common()})


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
