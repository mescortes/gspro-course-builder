"""Per-pixel surface classification on the CORE grid (DEM_RES) using imagery + LiDAR, trained on OSM labels.

Writes build/stack.npz (feature stack), build/labels_osm.tif, build/classes.tif, build/proba.npz.
"""
import sys, json
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.windows import from_bounds
from scipy import ndimage
from shapely.geometry import shape, Polygon, LineString, Point, mapping
from shapely.ops import unary_union
from pyproj import Transformer
from skimage.color import rgb2lab
from sklearn.ensemble import RandomForestClassifier

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C

CLASSES = ["unknown", "green", "fairway", "tee", "bunker", "cartpath", "rough", "tree", "building", "road", "native", "water"]
CID = {n: i for i, n in enumerate(CLASSES)}


def grid():
    e = C.CORE; r = C.DEM_RES
    W = int(round((e["xmax"] - e["xmin"]) / r)); H = int(round((e["ymax"] - e["ymin"]) / r))
    T = rasterio.transform.from_origin(e["xmin"], e["ymax"], r, r)
    return W, H, T


def read_on_grid(path, bands, W, H, resampling=Resampling.bilinear):
    e = C.CORE
    with rasterio.open(path) as ds:
        w = from_bounds(e["xmin"], e["ymin"], e["xmax"], e["ymax"], transform=ds.transform)
        a = ds.read(bands, window=w, out_shape=(len(bands), H, W) if isinstance(bands, list) else (H, W),
                    resampling=resampling, boundless=True, fill_value=0)
    return a.astype(np.float32)


_OSM_CACHE = {}


def osm_geoms():
    """All tagged OSM ways/relations/nodes in research/osm_all.json as (id, tags, shapely geometry in UTM).
    Golf features come from research/osm_golf.json as well (wider query); cart-path centre lines traced from the photo
    (research/paths_detected.geojson, trace_paths.py) are appended as golf=cartpath lines (tag source=trace_paths), and
    QA-curated structures OSM lacks (features/structures.geojson: shelters, with building / height / roof tags).
    Cached per process and on disk."""
    import pickle, os
    src = [C.ROOT / "research/osm_all.json", C.ROOT / "research/osm_golf.json", C.ROOT / "research/paths_detected.geojson",
           C.FEATURES / "structures.geojson"]
    stamp = tuple(int(os.path.getmtime(p)) if p.exists() else 0 for p in src)
    cache = C.BUILD / "osm_geoms.pkl"
    if stamp in _OSM_CACHE:
        return _OSM_CACHE[stamp]
    if cache.exists():
        try:
            st, out = pickle.load(open(cache, "rb"))
            if st == stamp:
                _OSM_CACHE[stamp] = out
                return out
        except Exception:
            pass
    tr = Transformer.from_crs("EPSG:4326", C.CRS, always_xy=True)
    def proj(geom):
        lon = np.array([p["lon"] for p in geom if p]); lat = np.array([p["lat"] for p in geom if p])
        x, y = tr.transform(lon, lat)
        return list(zip(x, y))
    elements = {}
    for p in src[:2]:
        if p.exists():
            for e in json.load(open(p))["elements"]:
                elements[(e["type"], e["id"])] = e
    out = []
    for (typ, oid), e in elements.items():
        t = e.get("tags", {})
        if not t:
            continue
        if typ == "node":
            x, y = tr.transform(e["lon"], e["lat"])
            out.append((oid, t, Point(x, y)))
            continue
        if typ == "relation":
            if t.get("type") != "multipolygon":
                continue
            outers = [m for m in e.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
            inners = [m for m in e.get("members", []) if m.get("role") == "inner" and m.get("geometry")]
            try:
                # outer members may be split ways: merge them into rings
                from shapely.ops import polygonize, linemerge
                def rings(ms):
                    lines = [LineString(proj(m["geometry"])) for m in ms if len(m["geometry"]) > 1]
                    return list(polygonize(linemerge(lines))) if lines else []
                og = unary_union(rings(outers))
                ig = unary_union(rings(inners)) if inners else None
                g = og.difference(ig) if ig is not None and not ig.is_empty else og
                if not g.is_empty:
                    out.append((oid, t, g))
            except Exception as ex:
                print("relation fail", oid, ex)
            continue
        if "geometry" not in e:
            continue
        pts = proj(e["geometry"])
        if len(pts) < 2:
            continue
        closed = len(pts) > 3 and pts[0] == pts[-1]
        g = Polygon(pts) if closed else LineString(pts)
        if not g.is_valid:
            g = g.buffer(0)
        out.append((oid, t, g))
    if src[2].exists():
        for i, f in enumerate(json.load(open(src[2]))["features"]):
            out.append((9_000_000_000 + i, dict(f["properties"]), shape(f["geometry"])))
    if src[3].exists():
        for i, f in enumerate(json.load(open(src[3]))["features"]):
            out.append((8_000_000_000 + i, dict(f["properties"], source="qa"), shape(f["geometry"])))
    pickle.dump((stamp, out), open(cache, "wb"))
    _OSM_CACHE[stamp] = out
    return out


def osm_label_raster(W, H, T, chm):
    G = osm_geoms()
    def polys(pred, buf=0.0):
        r = []
        for _, t, g in G:
            if pred(t):
                gg = g.buffer(buf) if buf else g
                if not gg.is_empty and gg.area > 0:
                    r.append(gg)
        return r
    lab = np.zeros((H, W), np.uint8)
    def burn(geoms, cid, erode_m=0.0):
        if not geoms:
            return
        m = rasterize([(g, 1) for g in geoms], out_shape=(H, W), transform=T, fill=0, dtype="uint8").astype(bool)
        if erode_m > 0:
            m = ndimage.binary_erosion(m, iterations=max(1, int(erode_m / C.DEM_RES)))
        lab[m] = cid
    course = polys(lambda t: t.get("leisure") == "golf_course")
    course_m = rasterize([(g, 1) for g in course], out_shape=(H, W), transform=T, fill=0, dtype="uint8").astype(bool) if course else np.ones((H, W), bool)
    feats = polys(lambda t: t.get("golf") in ("green", "fairway", "tee", "bunker", "water_hazard") or t.get("natural") == "water")
    feat_m = rasterize([(g, 1) for g in feats], out_shape=(H, W), transform=T, fill=0, dtype="uint8").astype(bool) if feats else np.zeros((H, W), bool)
    # unlabelled bands where the real edge of a path/road is unknown (OSM gives centre lines only)
    lines = polys(lambda t: t.get("golf") == "cartpath" or t.get("highway") in ("path", "footway"), 1.8) + \
        polys(lambda t: t.get("highway") in ("service", "residential", "tertiary", "secondary", "unclassified", "secondary_link", "motorway"), 6.0)
    line_m = rasterize([(g, 1) for g in lines], out_shape=(H, W), transform=T, fill=0, dtype="uint8").astype(bool) if lines else np.zeros((H, W), bool)
    rough = course_m & ~ndimage.binary_dilation(feat_m, iterations=int(4 / C.DEM_RES)) & ~line_m & (chm < 0.5)
    lab[rough] = CID["rough"]
    burn(polys(lambda t: t.get("golf") == "fairway"), CID["fairway"], 1.5)
    burn(polys(lambda t: t.get("golf") == "tee"), CID["tee"], 0.75)
    burn(polys(lambda t: t.get("golf") == "green"), CID["green"], 0.75)
    burn(polys(lambda t: t.get("golf") == "bunker"), CID["bunker"], 0.5)
    burn(polys(lambda t: t.get("golf") == "water_hazard" or t.get("natural") == "water"), CID["water"], 1.0)
    burn(polys(lambda t: t.get("golf") == "cartpath" or t.get("highway") in ("path", "footway"), 0.6), CID["cartpath"], 0)
    burn(polys(lambda t: t.get("highway") in ("service", "residential", "tertiary", "secondary", "unclassified", "secondary_link", "motorway"), 2.5), CID["road"], 0)
    burn(polys(lambda t: t.get("amenity") == "parking"), CID["road"], 1.0)
    burn(polys(lambda t: "building" in t), CID["building"], 1.0)
    lab[(chm > 3.0) & ~np.isin(lab, [CID["building"]])] = CID["tree"]
    return lab, G


def add_native_seeds(lab, X, names):
    """Brown/dry native & mulch areas are not mapped in OSM: seed them from colour (reddish-brown, low canopy)."""
    f = {n: X[..., i] for i, n in enumerate(names)}
    seed = (f["A4"] > 3.0) & (f["B4"] > 11.0) & (f["L4"] < 55) & (f["chmmax"] < 1.2) & \
           np.isin(lab, [CID["unknown"], CID["rough"]])
    if "NDVI4" in f:  # spring photo: dormant turf is brown too, but still far greener in NIR than mulch or bare soil
        seed &= f["NDVI4"] < 0.18
    seed = ndimage.binary_opening(seed, iterations=2)
    lab[seed] = CID["native"]
    return lab


NAMES_BASE = ["L", "A", "B", "L4", "A4", "B4", "L12", "A12", "B12", "Lstd2", "Lstd6", "Astd3", "I1", "I2", "Id",
              "slope", "slope4", "demrough", "micro", "chm", "chmmax", "gcount"]
# with a 4-band (R, G, B, NIR) photo such as SWOOP: NIR, NDVI and their context (live turf vs dormant / covered greens,
# sand, paths, water and roofs separate far better in NIR than in Lab)
NAMES_NIR = ["N", "NDVI", "NDVI4", "NDVI12", "Nstd3"]


def has_nir():
    with rasterio.open(C.IMAGERY) as ds:
        return ds.count >= 4


def feature_names():
    return NAMES_BASE + (NAMES_NIR if has_nir() else [])


NAMES = NAMES_BASE  # (kept for importers; main() uses feature_names())
TILE_PX = 1024
PAD = 64  # px of context around each tile (largest filter: gaussian sigma 12 px)


def tile_windows(W, H):
    for r0 in range(0, H, TILE_PX):
        for c0 in range(0, W, TILE_PX):
            r1, c1 = min(r0 + TILE_PX, H), min(c0 + TILE_PX, W)
            yield (r0, r1, c0, c1), (r0 - PAD, r1 + PAD, c0 - PAD, c1 + PAD)


def read_window(path, pr0, pr1, pc0, pc1, scale=1, fill=0.0):
    """Read a (possibly out-of-bounds) pixel window of a build raster on the DEM grid; scale=2 for 0.5 m rasters."""
    from rasterio.windows import Window
    with rasterio.open(path) as ds:
        if scale == 1:
            a = ds.read(1, window=Window(pc0, pr0, pc1 - pc0, pr1 - pr0), boundless=True, fill_value=fill)
        else:
            q0, q1 = pr0 // scale, -(-pr1 // scale); k0, k1 = pc0 // scale, -(-pc1 // scale)
            a = ds.read(1, window=Window(k0, q0, k1 - k0, q1 - q0), boundless=True, fill_value=fill)
            a = np.kron(a, np.ones((scale, scale), a.dtype))
            a = a[pr0 - q0 * scale:pr0 - q0 * scale + (pr1 - pr0), pc0 - k0 * scale:pc0 - k0 * scale + (pc1 - pc0)]
    return a.astype(np.float32)


def read_imagery_window(T, pr0, pr1, pc0, pc1):
    x0 = T.c + pc0 * T.a; x1 = T.c + pc1 * T.a; y1 = T.f + pr0 * T.e; y0 = T.f + pr1 * T.e
    with rasterio.open(C.IMAGERY) as ds:
        a = ds.read([1, 2, 3], window=from_bounds(x0, y0, x1, y1, transform=ds.transform),
                    out_shape=(3, pr1 - pr0, pc1 - pc0), resampling=Resampling.average, boundless=True, fill_value=0)
    return a.astype(np.float32) / 255.0


def read_nir_window(T, pr0, pr1, pc0, pc1):
    """NIR band (0..1) on the DEM grid, or None for a 3-band photo."""
    x0 = T.c + pc0 * T.a; x1 = T.c + pc1 * T.a; y1 = T.f + pr0 * T.e; y0 = T.f + pr1 * T.e
    with rasterio.open(C.IMAGERY) as ds:
        if ds.count < 4:
            return None
        a = ds.read(4, window=from_bounds(x0, y0, x1, y1, transform=ds.transform), out_shape=(pr1 - pr0, pc1 - pc0),
                    resampling=Resampling.average, boundless=True, fill_value=0)
    return a.astype(np.float32) / 255.0


def features_window(T, pr0, pr1, pc0, pc1):
    rgb = read_imagery_window(T, pr0, pr1, pc0, pc1)
    lab = rgb2lab(np.moveaxis(rgb, 0, -1)).astype(np.float32)
    L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
    inten = read_window(C.BUILD / "intensity.tif", pr0, pr1, pc0, pc1, fill=np.nan)
    valid = np.isfinite(inten)
    def nsmooth(a, m, s):
        num = ndimage.gaussian_filter(np.where(m, a, 0), s); den = ndimage.gaussian_filter(m.astype(np.float32), s)
        return num / np.maximum(den, 1e-3)
    i1 = nsmooth(inten, valid, 2); i2 = nsmooth(inten, valid, 6)
    dem = read_window(C.BUILD / "dem.tif", pr0, pr1, pc0, pc1, fill=np.nan)
    dem = np.where(np.isfinite(dem), dem, np.nanmean(dem))
    gy, gx = np.gradient(dem, C.DEM_RES); slope = np.hypot(gx, gy)
    rough_dem = np.abs(dem - ndimage.gaussian_filter(dem, 4))
    raw = read_window(C.BUILD / "dem_raw.tif", pr0, pr1, pc0, pc1, fill=np.nan)
    raw = np.where(np.isfinite(raw), raw, dem)
    micro = ndimage.gaussian_filter(np.abs(raw - ndimage.gaussian_filter(raw, 1.5)), 2)
    chm = read_window(C.BUILD / "chm.tif", pr0, pr1, pc0, pc1, scale=2)
    cnt = read_window(C.BUILD / "ground_count.tif", pr0, pr1, pc0, pc1)
    cnt_s = ndimage.gaussian_filter(np.maximum(cnt, 0), 2)
    def loc_std(a, s):
        m = ndimage.gaussian_filter(a, s); m2 = ndimage.gaussian_filter(a * a, s)
        return np.sqrt(np.maximum(m2 - m * m, 0))
    F = [L, A, B,
         ndimage.gaussian_filter(L, 4), ndimage.gaussian_filter(A, 4), ndimage.gaussian_filter(B, 4),
         ndimage.gaussian_filter(L, 12), ndimage.gaussian_filter(A, 12), ndimage.gaussian_filter(B, 12),
         loc_std(L, 2), loc_std(L, 6), loc_std(A, 3),
         i1, i2, i1 - i2,
         slope, ndimage.gaussian_filter(slope, 4), rough_dem, micro,
         chm, ndimage.maximum_filter(chm, 5), cnt_s]
    nir = read_nir_window(T, pr0, pr1, pc0, pc1)
    if nir is not None:
        ndvi = (nir - rgb[0]) / (nir + rgb[0] + 1e-3)
        F += [nir, ndvi, ndimage.gaussian_filter(ndvi, 4), ndimage.gaussian_filter(ndvi, 12), loc_std(nir, 3)]
    return np.stack(F, -1).astype(np.float32)


def main():
    import time
    t0 = time.time()
    W, H, T = grid()
    with rasterio.open(C.BUILD / "chm.tif") as ds:
        chm = np.kron(ds.read(1), np.ones((2, 2), np.float32))[:H, :W]
    lab, _ = osm_label_raster(W, H, T, chm)
    del chm
    rng = np.random.default_rng(0)
    names = feature_names()
    PER_TILE = 6000
    samples_X, samples_y = [], []
    windows = list(tile_windows(W, H))
    # pass 1: native seeds + training samples, tile by tile
    for k, ((r0, r1, c0, c1), (pr0, pr1, pc0, pc1)) in enumerate(windows):
        X = features_window(T, pr0, pr1, pc0, pc1)
        Xi = X[PAD:PAD + (r1 - r0), PAD:PAD + (c1 - c0)]
        sub = lab[r0:r1, c0:c1]
        sub[:] = add_native_seeds(sub.copy(), Xi, names)
        yv = sub.ravel(); Xf = Xi.reshape(-1, Xi.shape[-1])
        for c in range(1, len(CLASSES)):
            p = np.flatnonzero(yv == c)
            if len(p):
                pick = rng.choice(p, min(len(p), PER_TILE), replace=False)
                samples_X.append(Xf[pick]); samples_y.append(yv[pick])
    with rasterio.open(C.BUILD / "labels_osm.tif", "w", driver="GTiff", width=W, height=H, count=1, dtype="uint8",
                       crs=C.CRS, transform=T, compress="deflate", tiled=True) as d:
        d.write(lab, 1)
    Xs = np.concatenate(samples_X); ys = np.concatenate(samples_y)
    idx = []
    for c in np.unique(ys):
        p = np.flatnonzero(ys == c)
        idx.append(rng.choice(p, min(len(p), 60000), replace=False))
        print(CLASSES[c], len(p))
    idx = np.concatenate(idx)
    clf = RandomForestClassifier(n_estimators=80, max_depth=22, min_samples_leaf=3, n_jobs=-1, random_state=0,
                                 class_weight="balanced_subsample")
    clf.fit(Xs[idx], ys[idx])
    imp = sorted(zip(clf.feature_importances_, names), reverse=True)
    print("importances", [(n, round(float(v), 3)) for v, n in imp[:10]], f"{time.time() - t0:.0f}s", flush=True)
    # pass 2: predict, store per-class probability as uint8 (0..255) in a (classes, H, W) memmap
    proba = np.lib.format.open_memmap(C.BUILD / "proba_u8.npy", mode="w+", dtype=np.uint8, shape=(len(CLASSES), H, W))
    cls = np.zeros((H, W), np.uint8)
    for k, ((r0, r1, c0, c1), (pr0, pr1, pc0, pc1)) in enumerate(windows):
        X = features_window(T, pr0, pr1, pc0, pc1)
        Xi = X[PAD:PAD + (r1 - r0), PAD:PAD + (c1 - c0)].reshape(-1, X.shape[-1])
        pr = clf.predict_proba(Xi)
        for j, c in enumerate(clf.classes_):
            proba[c, r0:r1, c0:c1] = np.round(pr[:, j] * 255).astype(np.uint8).reshape(r1 - r0, c1 - c0)
        cls[r0:r1, c0:c1] = clf.classes_[np.argmax(pr, 1)].reshape(r1 - r0, c1 - c0)
        if k % 8 == 0:
            print(f"  predicted tile {k + 1}/{len(windows)} ({time.time() - t0:.0f}s)", flush=True)
    proba.flush(); del proba
    with rasterio.open(C.BUILD / "classes.tif", "w", driver="GTiff", width=W, height=H, count=1, dtype="uint8",
                       crs=C.CRS, transform=T, compress="deflate", tiled=True) as d:
        d.write(cls, 1)
    print("done", np.bincount(cls.ravel(), minlength=len(CLASSES)), f"{time.time() - t0:.0f}s")


def load_proba(c):
    """Probability map (float32 0..1) for class index c."""
    P = np.load(C.BUILD / "proba_u8.npy", mmap_mode="r")
    return P[c].astype(np.float32) / 255.0


if __name__ == "__main__":
    main()
