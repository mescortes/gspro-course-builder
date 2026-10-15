"""Memory of the mesh step (build_terrain_mesh.py, the build's peak: 15.2 GB on Whistle Bear before these). Each helper
made leaner must give bit for bit what it gave before: the pre-change code is kept here verbatim (`_*_before`) and
compared on synthetic data. Fast: synthetic data only."""
import sys
import tracemalloc
from pathlib import Path

import numpy as np
import shapely
from rasterio.transform import from_origin
from shapely.geometry import Point, Polygon, box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config as C  # noqa: E402
import edges  # noqa: E402
import build_terrain_mesh as B  # noqa: E402


# ---- the code before (verbatim, but for module prefixes)

def _lip_drop_before(pts, rings):
    pts = np.asarray(pts, np.float64)
    drop = np.zeros(len(pts))
    outers = [p for _, rs, _, p in rings if rs == "bunkerlip"]
    if not outers or not len(pts):
        return drop
    P = shapely.points(pts)
    tree = shapely.STRtree(outers)
    pi, gi = tree.query(P, predicate="intersects")
    if len(pi):
        bnd = np.array([outers[i].boundary for i in gi], object)
        d = shapely.distance(P[pi], bnd)
        t = np.clip(d / edges.LIP_W, 0.0, 1.0)
        drop[pi] = np.maximum(drop[pi], edges.LIP_DEPTH * (1.0 - (1.0 - t) ** 2))   # concave lip profile
    return drop


def _label_rings_before(cent, surf, hole, rings, sid):
    surf = np.array(surf, copy=True); hole = np.array(hole, copy=True)
    if not rings:
        return surf, hole
    geoms = [r for r, _, _, _ in rings]
    tree = shapely.STRtree(geoms)
    pi, gi = tree.query(shapely.points(np.asarray(cent)[:, :2]), predicate="within")
    surf[pi] = np.array([sid[rings[i][1]] for i in gi], surf.dtype)
    hole[pi] = np.array([rings[i][2] for i in gi], hole.dtype)
    return surf, hole


def _blended_dem_before(dem, T, feats):
    from rasterio.features import rasterize
    from scipy import ndimage
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
        ext = ndimage.gaussian_filter(delta, feather / r) / np.maximum(gm, 0.5)
        corr = np.where(inside, delta, ext)
        w = np.clip(2.0 * gm, 0, 1)  # 1 inside and on the edge, fades outside
        out = out * (1 - w) + (dem + corr) * w
        del den, delta, gm, ext, corr, w
    out = B.level_tees(out, T, [g for g, s, _ in feats if s == "tee"], holes=[h for g, s, h in feats if s == "tee"],
                       protect=mask(("cartpath", "road", "building", "green", "fringe", "bunker", "water")) > 0,
                       **C.tuning("level_tees", {}))
    for p, level, _ in edges.water_levels(feats, dem, T):
        edges.carve_water(out, T, p, level)
    return out


def _label_faces_before(Vt, Ft, nbr, segs, feats):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    import rasterio
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
    from rasterio.features import rasterize
    fg = [(g, s, h) for g, s, h in feats if s != "rough"]
    s_of = np.r_[B.SID["rough"], [B.SID.get(s, 0) for _, s, _ in fg]].astype(np.int64)
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
    e1 = Vt[Ft[:, 1]] - Vt[Ft[:, 0]]; e2 = Vt[Ft[:, 2]] - Vt[Ft[:, 0]]
    a = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    nf = roots.max() + 1; ns = len(B.SURFACES)
    w = np.bincount(roots * ns + tri_s, weights=a, minlength=nf * ns).reshape(nf, ns)
    face_s = np.argmax(w, 1)
    win = tri_s == face_s[roots]
    key = roots[win].astype(np.int64) * 128 + np.minimum(tri_h[win], 127)
    cnt = np.bincount(key, minlength=nf * 128).reshape(nf, 128)
    face_h = np.argmax(cnt, 1)
    face_h[cnt.max(1) == 0] = 99
    return face_s[roots].astype(np.int16), face_h[roots].astype(np.int16)


# ---- synthetic data

def _bunkers():
    """Four bunkers (holes 1-3): a round one with an island, a 60-point star, and two sharing the edge x = 30 (a point
    on it intersects both)."""
    round_ = Point(10, 10).buffer(4, quad_segs=32).difference(Point(11, 10).buffer(1))
    a = np.linspace(0, 2 * np.pi, 60, endpoint=False)
    rad = np.where(np.arange(60) % 2, 2.5, 4.0)
    star = Polygon(np.c_[24 + rad * np.cos(a), 11 + rad * np.sin(a)])
    feats = [(round_, "bunker", 1), (star, "bunker", 2), (box(28, 0, 30, 6), "bunker", 3), (box(30, 0, 34, 6), "bunker", 3)]
    return edges.derive_rings(feats, zone=box(-50, -50, 100, 100))


def _points(n=6000, seed=0):
    rng = np.random.default_rng(seed)
    _, rings = _bunkers()
    on_edges = np.concatenate([np.asarray(p.exterior.coords) for _, _, _, p in rings])
    shared = np.c_[np.full(25, 30.0), np.linspace(0, 6, 25)]
    return np.concatenate([rng.uniform([-2, -2], [40, 18], (n, 2)), on_edges, shared])


class _Spy:
    """Wraps a shapely function, recording each call's array sizes (and the distinct objects of its 2nd argument)."""
    def __init__(self, f):
        self.f, self.sizes, self.distinct = f, [], []

    def __call__(self, *a, **k):
        self.sizes.append(len(np.atleast_1d(a[0])))
        if len(a) > 1:
            self.distinct.append(len({id(g) for g in np.atleast_1d(a[1])}))
        return self.f(*a, **k)


# ---- edges.lip_drop

def test_lip_drop_is_bit_for_bit_as_before():
    _, rings = _bunkers()
    pts = _points()
    assert np.array_equal(edges.lip_drop(pts, rings), _lip_drop_before(pts, rings))
    assert (edges.lip_drop(pts, rings) > 0).sum() > 500


def test_lip_drop_measures_against_one_boundary_per_bunker(monkeypatch):
    """Whistle Bear: 270 k mesh vertices in 84 bunkers. A copy of the bunker's ~700-point boundary for each vertex in
    it was 7.5 GB, half the mesh step's 15.2 GB peak."""
    _, rings = _bunkers()
    spy = _Spy(shapely.distance)
    monkeypatch.setattr(shapely, "distance", spy)
    edges.lip_drop(_points(), rings)
    assert sum(spy.sizes) > 500
    assert max(spy.distinct) <= len(rings), f"{max(spy.distinct)} boundary geometries for {len(rings)} bunkers"


def test_lip_drop_makes_points_a_chunk_at_a_time(monkeypatch):
    _, rings = _bunkers()
    pts = _points()
    want = _lip_drop_before(pts, rings)
    monkeypatch.setattr(edges, "QUERY_CHUNK", 97, raising=False)
    spy = _Spy(shapely.points)
    monkeypatch.setattr(shapely, "points", spy)
    got = edges.lip_drop(pts, rings)
    assert max(spy.sizes) <= 97, f"{max(spy.sizes)} GEOS points at once"
    assert np.array_equal(got, want)


# ---- edges.label_rings

def _rings_and_centroids():
    feats, rings = _bunkers()
    pond = Point(60, 10).buffer(8, quad_segs=24)
    _, wrings = edges.derive_rings([(pond, "water", 99)], zone=box(-50, -50, 100, 100))
    rings = rings + wrings
    rng = np.random.default_rng(1)
    cent = np.concatenate([rng.uniform([-2, -2], [70, 20], (8000, 2)),
                           shapely.get_coordinates([r for r, _, _, _ in rings])])
    surf = rng.integers(0, 6, len(cent)).astype(np.int16); hole = rng.integers(1, 19, len(cent)).astype(np.int16)
    return cent, surf, hole, rings


def test_label_rings_is_bit_for_bit_as_before_a_chunk_at_a_time(monkeypatch):
    """A GEOS point for each of Whistle Bear's 5.3 M triangle centroids at once was ~0.9 GB."""
    cent, surf, hole, rings = _rings_and_centroids()
    want = _label_rings_before(cent, surf, hole, rings, B.SID)
    monkeypatch.setattr(edges, "QUERY_CHUNK", 101, raising=False)
    spy = _Spy(shapely.points)
    monkeypatch.setattr(shapely, "points", spy)
    got = edges.label_rings(cent, surf, hole, rings, B.SID)
    assert max(spy.sizes) <= 101, f"{max(spy.sizes)} GEOS points at once"
    for g, w in zip(got, want):
        assert g.dtype == w.dtype and np.array_equal(g, w)
    assert (got[0] != surf).sum() > 50                        # the rings did relabel triangles


def test_label_rings_without_rings_or_centroids():
    cent, surf, hole, rings = _rings_and_centroids()
    for args in ((cent, surf, hole, []), (cent[:0], surf[:0], hole[:0], rings)):
        got, want = edges.label_rings(*args, B.SID), _label_rings_before(*args, B.SID)
        assert all(g.dtype == w.dtype and np.array_equal(g, w) for g, w in zip(got, want))


# ---- build_terrain_mesh.blended_dem

RES = 0.25


def _course_dem(n=600):
    T = from_origin(0.0, n * RES, RES, RES)
    x = (np.arange(n) + 0.5) * RES
    X, Y = np.meshgrid(x, x[::-1])
    rng = np.random.default_rng(2)
    dem = 100 + 0.03 * X + 0.01 * Y + 0.2 * np.sin(X / 7) * np.cos(Y / 5) + rng.normal(0, 0.01, X.shape)
    feats = [(Point(40, 40).buffer(12), "green", 1),
             (Point(40, 40).buffer(15).difference(Point(40, 40).buffer(12)), "fringe", 1),
             (box(100, 100, 120, 110), "tee", 1), (box(10, 120, 140, 123), "cartpath", 1),
             (Point(70, 60).buffer(5), "bunker", 1), (Point(110, 40).buffer(14), "water", 99),
             (box(0, 140, 150, 146), "road", 99)]
    return dem, T, feats


def test_blended_dem_is_bit_for_bit_as_before():
    dem, T, feats = _course_dem()
    want = _blended_dem_before(dem, T, feats)
    got = B.blended_dem(dem, T, feats)
    assert got.dtype == want.dtype and np.array_equal(got.view(np.uint64), want.view(np.uint64))
    assert np.abs(got - dem).max() > 0.1                     # it did smooth, level and carve
    # a course with none of the smoothed or protected surfaces
    only = [(box(0, 0, 50, 50), "fairway", 1)]
    assert np.array_equal(B.blended_dem(dem, T, only).view(np.uint64), _blended_dem_before(dem, T, only).view(np.uint64))


def test_blended_dem_peak_memory():
    """Whistle Bear's DEM is 6144 x 6144: each full-grid float64 array is 0.3 GB. The blend held about 12 of them on
    top of its input (masks as float64, the trend, out-of-place arithmetic); now about 6."""
    dem, T, feats = _course_dem()
    tracemalloc.start()
    try:
        base = tracemalloc.get_traced_memory()[0]
        tracemalloc.reset_peak()
        B.blended_dem(dem, T, feats)
        peak = tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()
    assert peak <= 8 * dem.nbytes, f"blended_dem peaked at {peak / dem.nbytes:.1f} DEM-sized arrays"


# ---- build_terrain_mesh.label_faces

def test_label_dtype_is_the_smallest_that_holds_the_labels():
    """Labels are 0 (rough) and 1..n; rasterize needs about four times its output (0.6 GB int32 on Whistle Bear)."""
    assert [B.label_dtype(n) for n in (0, 255, 256, 65535, 65536)] == ["uint8", "uint8", "uint16", "uint16", "int32"]
    for n in (255, 65535):
        assert np.iinfo(B.label_dtype(n)).max >= n


def _label_scene(monkeypatch, n_side=(20, 15)):
    """300 small surfaces (more than a uint8 label holds) in rough, triangulated as the mesh step does."""
    import triangle
    e0, n0 = C.ORIGIN_E, C.ORIGIN_N
    monkeypatch.setattr(C, "CORE", {"xmin": e0 - 5, "ymin": n0 - 5, "xmax": e0 + 55, "ymax": n0 + 45})
    names = ["green", "fairway", "tee", "bunker", "fringe", "semirough", "cartpath"]
    feats = []
    for i in range(n_side[0]):
        for j in range(n_side[1]):
            k = i * n_side[1] + j
            x, y = e0 + i * 2.5, n0 + j * 2.5
            feats.append((box(x, y, x + 1.6, y + 1.6 + 0.3 * (k % 3)), names[k % len(names)], 1 + k % 18))
    aoi = box(C.CORE["xmin"], C.CORE["ymin"], C.CORE["xmax"], C.CORE["ymax"])
    V2, S = B.build_pslg(feats, aoi, Polygon())
    tri = triangle.triangulate({"vertices": V2, "segments": S}, "pq25a0.4n")
    return tri["vertices"], tri["triangles"].astype(np.int32), tri["neighbors"], tri["segments"], feats


def test_label_faces_is_bit_for_bit_as_before_with_a_uint16_label_raster(monkeypatch):
    import rasterio.features
    Vt, Ft, nbr, segs, feats = _label_scene(monkeypatch)
    want = _label_faces_before(Vt, Ft, nbr, segs, feats)
    dtypes = []
    rasterize = rasterio.features.rasterize

    def spy(*a, **k):
        dtypes.append(k.get("dtype"))
        return rasterize(*a, **k)
    monkeypatch.setattr(rasterio.features, "rasterize", spy)
    got = B.label_faces(Vt, Ft, nbr, segs, feats)
    assert dtypes == ["uint16"]
    for g, w in zip(got, want):
        assert g.dtype == w.dtype and np.array_equal(g, w)
    assert len(np.unique(got[1])) == 19                       # holes 1-18 and 99 (rough)
