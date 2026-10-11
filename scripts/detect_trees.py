"""Individual tree detection from the LiDAR canopy height model.

Tree tops = local maxima of the smoothed CHM with height-dependent non-maximum suppression; crowns = marker-controlled
watershed. Crown base and shape statistics come from the point cloud. Output: features/trees.geojson (UTM points)
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


def main():
    with rasterio.open(C.BUILD / "chm.tif") as ds:
        chm = ds.read(1); T = ds.transform
    H, W = chm.shape; r = T.a
    G = osm_geoms()
    bmask = rasterize([(g.buffer(0.75), 1) for _, t, g in G if "building" in t and g.geom_type == "Polygon"],
                      out_shape=(H, W), transform=T, fill=0, dtype="uint8").astype(bool)
    chm = np.where(bmask, 0, chm)
    sm = ndimage.gaussian_filter(chm, 0.8)
    # candidate maxima
    mx = (sm == ndimage.maximum_filter(sm, size=3)) & (sm > MIN_H)
    cy, cx = np.nonzero(mx)
    hv = sm[cy, cx]
    order = np.argsort(-hv)
    cy, cx, hv = cy[order], cx[order], hv[order]
    # height-dependent suppression radius (m): small trees close together, big crowns far apart
    rad = np.clip(0.8 + 0.20 * hv, 1.5, 5.0) / r
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
    canopy = sm > 1.5
    lab = watershed(-sm, markers, mask=canopy)
    n = len(cy)
    area = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1)) * r * r
    meanh = ndimage.mean(sm, lab, range(1, n + 1))
    # crown centroid (more robust than the apex for leaning/irregular crowns)
    com = ndimage.center_of_mass(np.ones_like(lab), lab, range(1, n + 1))
    # crown base from vegetation returns
    cb, pen = crown_base(lab, T, n)
    # imagery colour of the crown
    col = crown_colour(lab, T, n, W, H)
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
                                     "B": round(float(B), 1)}})
    assign_archetypes(feats)
    json.dump({"type": "FeatureCollection", "features": feats}, open(C.FEATURES / "trees.geojson", "w"))
    from collections import Counter
    print("trees", len(feats), Counter(f["properties"]["archetype"] for f in feats))
    with rasterio.open(C.BUILD / "crowns.tif", "w", driver="GTiff", width=W, height=H, count=1, dtype="int32",
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
    e = C.CORE
    with rasterio.open(C.IMAGERY) as ds:
        a = ds.read([1, 2, 3], window=from_bounds(e["xmin"], e["ymin"], e["xmax"], e["ymax"], transform=ds.transform),
                    out_shape=(3, H, W), resampling=Resampling.average)
    Lab = rgb2lab(np.moveaxis(a, 0, -1).astype(np.float32) / 255)
    out = np.zeros((n, 3))
    for c in range(3):
        out[:, c] = ndimage.mean(Lab[..., c], lab, range(1, n + 1))
    return out


def assign_archetypes(feats):
    """Species group from crown structure (LiDAR) + colour (imagery), using robust z-scores over the site.
    Aleppo pine: open (high pulse penetration), peaked, high crown base. Coast live oak: dense, broad, low crown.
    Sycamore / deciduous: lighter, yellower crowns. Eucalyptus: very tall and narrow."""
    if not feats:
        return
    K = ("height", "crown_r", "crown_base", "sharpness", "penetration", "L", "A", "B")
    P = {k: np.array([f["properties"][k] for f in feats], float) for k in K}
    big = P["height"] > 6
    def z(v):
        med = np.median(v[big]); mad = np.median(np.abs(v[big] - med)) * 1.4826 + 1e-6
        return (v - med) / mad
    ratio = P["crown_r"] / np.maximum(P["height"], 1)
    pine = z(P["sharpness"]) + z(P["penetration"]) + 0.5 * z(P["crown_base"]) - 0.5 * z(ratio)
    oak = -z(P["penetration"]) + z(ratio) - 0.5 * z(P["crown_base"])
    syc = z(P["L"]) + 0.7 * z(P["A"]) + 0.3 * z(P["B"])
    for i, f in enumerate(feats):
        h = P["height"][i]
        if h < 4.5:
            a = "shrub"
        elif h > 19 and ratio[i] < 0.3 and P["penetration"][i] > 0.3:
            a = "eucalyptus"
        elif syc[i] > 1.6 and h > 6:
            a = "sycamore"
        elif pine[i] > oak[i] + 0.3:
            a = "pine"
        else:
            a = "oak"
        f["properties"]["archetype"] = a


if __name__ == "__main__":
    main()
