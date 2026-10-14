"""Individual tree detection from the LiDAR canopy height model.

Tree tops = local maxima of the smoothed CHM with height-dependent non-maximum suppression; crowns = marker-controlled
watershed. With leaf-off LiDAR (config.LIDAR_LEAF_OFF) the CHM is closed first so bare crowns are not split. Crown base and shape statistics come from the point cloud. Output: features/trees.geojson (UTM points)
with height, crown radius, crown base, archetype.
"""
import sys, json
import numpy as np
import rasterio
import laspy
from rasterio.features import rasterize
from scipy import ndimage
from skimage.segmentation import watershed
from shapely.geometry import Point, mapping
from skimage.color import rgb2lab
from rasterio.windows import from_bounds
from rasterio.enums import Resampling

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C
from surface_classify import osm_geoms

MIN_H = 2.5


def smooth_chm(chm, r, leaf_off=None):
    """CHM used for tops and crowns. Leaf-off LiDAR leaves many holes inside deciduous crowns (first returns from bare
    branches are sparse): a grey closing (1.25 m radius) restores the crown envelope before smoothing."""
    leaf_off = C.LIDAR_LEAF_OFF if leaf_off is None else leaf_off
    if leaf_off:
        k = int(round(1.25 / r))
        yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
        chm = ndimage.grey_closing(chm, footprint=(yy ** 2 + xx ** 2) <= k * k)
        return ndimage.gaussian_filter(chm, 0.5 / r)
    return ndimage.gaussian_filter(chm, 0.8)


def segment_crowns(chm, r, leaf_off=None):
    """((rows, cols, heights) of tree tops, watershed crown labels 1..n) on a CHM with cell size r."""
    leaf_off = C.LIDAR_LEAF_OFF if leaf_off is None else leaf_off
    H, W = chm.shape
    sm = smooth_chm(chm, r, leaf_off)
    # candidate maxima
    mx = (sm == ndimage.maximum_filter(sm, size=3)) & (sm > MIN_H)
    cy, cx = np.nonzero(mx)
    hv = sm[cy, cx]
    order = np.argsort(-hv)
    cy, cx, hv = cy[order], cx[order], hv[order]
    # height-dependent suppression radius (m): small trees close together, big crowns far apart (leaf-off crowns are
    # lumpy, so the radius grows faster with height)
    rad = (np.clip(1.0 + 0.25 * hv, 2.0, 7.0) if leaf_off else np.clip(0.8 + 0.20 * hv, 1.5, 5.0)) / r
    keep = np.ones(len(cy), bool)
    from scipy.spatial import cKDTree
    kd = cKDTree(np.c_[cy, cx])
    for i in range(len(cy)):
        if not keep[i]:
            continue
        for j in kd.query_ball_point([cy[i], cx[i]], rad[i]):
            if j > i:
                keep[j] = False
    cy, cx, hv = cy[keep], cx[keep], hv[keep]
    markers = np.zeros((H, W), np.int32)
    markers[cy, cx] = np.arange(1, len(cy) + 1)
    lab = watershed(-sm, markers, mask=sm > 1.5)
    return (cy, cx, hv), lab


NO_TREE = ("tee", "green", "bunker")


def off_surfaces(feats, polys, max_shift=4.0, clearance=0.75):
    """Trees on tees, greens or bunkers: LiDAR positions are crown tops, so a leaning tree beside a tee lands on it, and
    the 2018 trees stand where later tees were built (hole 8's 2025 back tee). A tree within `max_shift` m of the edge
    moves to `clearance` m outside it; one deeper inside was cleared for the surface and is dropped."""
    from shapely.strtree import STRtree
    from shapely.ops import nearest_points
    if not polys:
        return feats
    tree = STRtree(polys)
    out = []
    for f in feats:
        p = Point(f["geometry"]["coordinates"])
        hit = [polys[i] for i in tree.query(p) if polys[i].contains(p)]
        if not hit:
            out.append(f); continue
        g = hit[0]
        if g.exterior.distance(p) > max_shift:
            continue
        for _ in range(3):   # step outward along the edge normal, then re-check (a neighbouring surface may be hit)
            q = nearest_points(g.exterior, p)[0]
            v = np.array([q.x - p.x, q.y - p.y]); L = np.linalg.norm(v)
            p = Point(q.x + v[0] / max(L, 1e-9) * clearance, q.y + v[1] / max(L, 1e-9) * clearance)
            hit = [polys[i] for i in tree.query(p) if polys[i].contains(p)]
            if not hit:
                break
            g = hit[0]
        if hit:
            continue
        f = dict(f, geometry={"type": "Point", "coordinates": (round(p.x, 2), round(p.y, 2))})
        out.append(f)
    return out


CLEARED = C.ROOT / "features" / "trees_cleared.geojson"


def drop_cleared(feats, pts, radius=1.5):
    """Trees within `radius` m of a reviewed clearance point (features/trees_cleared.geojson): 2018 LiDAR
    trees the 2025 photo shows gone, cut down for the tees and paths built since (holes 5 and 8 Blue)."""
    if not len(pts):
        return feats
    from scipy.spatial import cKDTree
    xy = np.array([f["geometry"]["coordinates"][:2] for f in feats], float)
    d, _ = cKDTree(np.asarray(pts, float)).query(xy)
    return [f for f, di in zip(feats, d) if di > radius]


def main(out=None):
    with rasterio.open(C.BUILD / "chm.tif") as ds:
        chm = ds.read(1); T = ds.transform
    H, W = chm.shape; r = T.a
    G = osm_geoms()
    bmask = rasterize([(g.buffer(0.75), 1) for _, t, g in G if "building" in t and g.geom_type == "Polygon"],
                      out_shape=(H, W), transform=T, fill=0, dtype="uint8").astype(bool)
    chm = np.where(bmask, 0, chm)
    (cy, cx, hv), lab = segment_crowns(chm, r)
    sm = smooth_chm(chm, r)
    n = len(cy)
    area = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1)) * r * r
    meanh = ndimage.mean(sm, lab, range(1, n + 1))
    # crown centroid (more robust than the apex for leaning/irregular crowns)
    com = ndimage.center_of_mass(np.ones_like(lab), lab, range(1, n + 1))
    # crown base from vegetation returns
    cb, pen = crown_base(lab, T, n)
    # imagery colour of the crown (Lab + NDVI), and how solid the raw canopy is (leaf-off hardwoods are full of holes)
    col, ndvi = crown_colour(lab, T, n, W, H)
    solid = ndimage.mean((chm > 0.4 * sm).astype(np.float32), lab, range(1, n + 1))
    feats = []
    for i in range(n):
        if area[i] < 1.0:
            continue
        x_top = T.c + (cx[i] + 0.5) * r; y_top = T.f - (cy[i] + 0.5) * r
        x_c = T.c + (com[i][1] + 0.5) * r; y_c = T.f - (com[i][0] + 0.5) * r
        h = float(hv[i]); cr = float(np.sqrt(area[i] / np.pi))
        base = float(cb[i]) if np.isfinite(cb[i]) else 0.35 * h
        base = float(np.clip(base, 0.3, 0.8 * h))
        sharp = (h - meanh[i]) / max(cr, 0.5)
        L, A, B = col[i]
        feats.append({"type": "Feature", "geometry": mapping(Point(0.5 * (x_top + x_c), 0.5 * (y_top + y_c))),
                      "properties": {"id": i, "height": round(h, 2), "crown_r": round(cr, 2), "crown_base": round(base, 2),
                                     "sharpness": round(float(sharp), 3), "penetration": round(float(pen[i]), 3), "L": round(float(L), 1), "A": round(float(A), 1),
                                     "B": round(float(B), 1), "ndvi": round(float(ndvi[i]), 3), "solidity": round(float(solid[i]), 3)}})
    assign_archetypes(feats)
    surf_path = C.FEATURES / "course_surfaces.geojson"
    if surf_path.exists():
        from shapely.geometry import shape
        polys = [g for f in json.load(open(surf_path))["features"] if f["properties"]["surface"] in NO_TREE
                 for g in getattr(shape(f["geometry"]), "geoms", [shape(f["geometry"])])]
        n0 = len(feats); feats = off_surfaces(feats, polys)
        print(f"trees on tees / greens / bunkers: {n0 - len(feats)} dropped (cleared), the rest moved off the edge", flush=True)
    if CLEARED.exists():
        pts = [f["geometry"]["coordinates"][:2] for f in json.load(open(CLEARED))["features"]]
        n0 = len(feats); feats = drop_cleared(feats, pts)
        print(f"trees cleared since the LiDAR (trees_cleared.geojson): {n0 - len(feats)} dropped", flush=True)
    json.dump({"type": "FeatureCollection", "features": feats}, open(out or (C.FEATURES / "trees.geojson"), "w"))
    from collections import Counter
    print("trees", len(feats), Counter(f["properties"]["archetype"] for f in feats))
    with rasterio.open(C.BUILD / ("crowns.tif" if out is None else "crowns_tmp.tif"), "w", driver="GTiff", width=W, height=H, count=1, dtype="int32",
                       crs=C.CRS, transform=T, compress="deflate") as d:
        d.write(lab.astype(np.int32), 1)


def crown_base(lab, T, n):
    dem = rasterio.open(C.BUILD / "dem.tif")
    demA = dem.read(1); TD = dem.transform
    e = C.CORE
    hag_all = [[] for _ in range(n + 1)]
    out = np.full(n, np.nan)
    sums = []; gcount = []; acount = []
    for f in C.LIDAR_TILES:
        with laspy.open(f) as rr:
            h = rr.header
            for ch in rr.chunk_iterator(5_000_000):
                x = ch.x.array * h.scales[0] + h.offsets[0]; y = ch.y.array * h.scales[1] + h.offsets[1]
                m = (x > e["xmin"]) & (x < e["xmax"]) & (y > e["ymin"]) & (y < e["ymax"])
                cls = np.asarray(ch.classification)
                m &= (cls == 1) | (cls == 2)
                if not m.any():
                    continue
                isg = (cls[m] == 2)
                x, y = x[m], y[m]; z = (ch.z.array * h.scales[2] + h.offsets[2])[m]
                c = ((x - T.c) / T.a).astype(int); rw = ((y - T.f) / T.e).astype(int)
                cd = ((x - TD.c) / TD.a).astype(int); rd = ((y - TD.f) / TD.e).astype(int)
                ok = (c >= 0) & (c < lab.shape[1]) & (rw >= 0) & (rw < lab.shape[0])
                ok &= (cd >= 0) & (cd < demA.shape[1]) & (rd >= 0) & (rd < demA.shape[0])
                hag = z[ok] - demA[rd[ok], cd[ok]]
                L = lab[rw[ok], c[ok]]
                g_ = isg[ok]
                gcount.append(np.bincount(L[g_ | (hag < 0.3)], minlength=n + 1))
                acount.append(np.bincount(L, minlength=n + 1))
                sel = (L > 0) & (hag > 0.8) & ~g_
                sums.append(np.c_[L[sel], hag[sel]])
    S = np.concatenate(sums)
    S = S[np.argsort(S[:, 0])]
    ids = S[:, 0].astype(int)
    bounds = np.flatnonzero(np.r_[True, ids[1:] != ids[:-1], True])
    for k in range(len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        i = ids[a]
        if b - a >= 8:
            out[i - 1] = np.percentile(S[a:b, 1], 8)
    pen = np.sum(gcount, 0)[1:] / np.maximum(np.sum(acount, 0)[1:], 1)
    return out, pen


def crown_colour(lab, T, n, W, H):
    """Mean Lab colour and mean NDVI (NaN without a NIR band) of each crown in the photo."""
    e = C.CORE
    with rasterio.open(C.IMAGERY) as ds:
        bands = [1, 2, 3, 4] if ds.count >= 4 else [1, 2, 3]
        a = ds.read(bands, window=from_bounds(e["xmin"], e["ymin"], e["xmax"], e["ymax"], transform=ds.transform),
                    out_shape=(len(bands), H, W), resampling=Resampling.average).astype(np.float32) / 255
    Lab = rgb2lab(np.moveaxis(a[:3], 0, -1))
    out = np.zeros((n, 3))
    for c in range(3):
        out[:, c] = ndimage.mean(Lab[..., c], lab, range(1, n + 1))
    nd = np.full(n, np.nan)
    if len(bands) == 4:
        nd = ndimage.mean((a[3] - a[0]) / (a[3] + a[0] + 1e-3), lab, range(1, n + 1))
    return out, np.asarray(nd, float)


def assign_archetypes(feats):
    """Species group (config.TREE_ARCHETYPES) from crown structure (LiDAR) and the photo.

    The March 2018 LiDAR is leaf-off: evergreen crowns stop most pulses (low ground-return 'penetration'), bare
    hardwoods do not. In the leaf-off spring photo only evergreen crowns are green (crown NDVI), but the photo is not a
    true ortho - tall crowns lean several metres - so NDVI only supports the LiDAR, it does not decide alone.
      conifer  low penetration, or moderately low penetration with a green crown
      pine     (eastern white pine) a conifer carrying its crown high (crown base > 40 % of height) or tall and flat-topped
      spruce   the other conifers: dense cones with branches near the ground
      oak / maple  hardwoods: the broadest third of crowns for their height -> oak, the rest -> maple (leaf-off data
               cannot tell the species apart; maples dominate Westmount's tree lines)
      shrub    under 4.5 m"""
    if not feats:
        return
    K = ("height", "crown_r", "crown_base", "sharpness", "penetration")
    P = {k: np.array([f["properties"][k] for f in feats], float) for k in K}
    nd = np.array([f["properties"].get("ndvi", np.nan) for f in feats], float)
    nd = np.where(np.isfinite(nd), nd, -1.0)
    h, pen = P["height"], P["penetration"]
    ratio = P["crown_r"] / np.maximum(h, 1)
    base_f = P["crown_base"] / np.maximum(h, 1)
    conifer = (h >= 4.5) & ((pen < 0.24) | ((nd > 0.28) & (pen < 0.32)) | ((nd > 0.22) & (pen < 0.27)))
    pine = conifer & ((base_f > 0.4) | ((h > 20) & (P["sharpness"] < 2.0)))
    hard = (h >= 4.5) & ~conifer
    # broadest third of the hardwood crowns -> oak (reviews name maples as the dominant hardwood)
    cut = np.percentile(ratio[hard & (h > 6)], 65) if (hard & (h > 6)).any() else 0.35
    for i, f in enumerate(feats):
        if h[i] < 4.5:
            a = "shrub"
        elif pine[i]:
            a = "pine"
        elif conifer[i]:
            a = "spruce"
        elif ratio[i] > cut:
            a = "oak"
        else:
            a = "maple"
        f["properties"]["archetype"] = a


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
