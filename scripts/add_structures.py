"""Structures: flagstick + cup, tee markers, buildings (OSM footprints + LiDAR roofs), cart-path bridges."""
import sys, json, math
import numpy as np
import rasterio
import triangle
from shapely.geometry import Polygon, LineString, box, Point
from scipy import ndimage

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C
from surface_classify import osm_geoms

PH = C.DATA / "textures"


class Raster:
    def __init__(self, path):
        with rasterio.open(path) as ds:
            self.z = ds.read(1).astype(np.float64); self.T = ds.transform

    def __call__(self, e, n, order=1):
        e = np.atleast_1d(e); n = np.atleast_1d(n)
        c = (e - self.T.c) / self.T.a - 0.5; r = (n - self.T.f) / self.T.e - 0.5
        return ndimage.map_coordinates(self.z, [r, c], order=order, mode="nearest")


def mm(P):
    """UTM (e, n, h) -> model."""
    P = np.asarray(P, float)
    return np.c_[P[:, 0] - C.ORIGIN_E, P[:, 2] - C.BASE_H, -(P[:, 1] - C.ORIGIN_N)].astype(np.float32)


def cylinder(c0, c1, r0, r1, k=12, cap=True):
    d = np.asarray(c1, float) - np.asarray(c0, float); L = np.linalg.norm(d); d /= L
    u = np.cross(d, [1, 0, 0] if abs(d[0]) < 0.9 else [0, 0, 1]); u /= np.linalg.norm(u); v = np.cross(d, u)
    P, N, UV, I = [], [], [], []
    for j in range(k + 1):
        a = 2 * np.pi * j / k; nr = np.cos(a) * u + np.sin(a) * v
        P += [c0 + nr * r0, c1 + nr * r1]; N += [nr, nr]; UV += [[j / k, 0], [j / k, L]]
    for j in range(k):
        a0, b0, a1, b1 = 2 * j, 2 * j + 1, 2 * j + 2, 2 * j + 3
        I += [[a0, a1, b0], [b0, a1, b1]]
    if cap:
        b = len(P); P.append(c1); N.append(d); UV.append([0.5, 0.5])
        for j in range(k):
            I.append([2 * j + 1, 2 * j + 3, b])
    return np.array(P), np.array(N), np.array(UV), np.array(I)


def model_vec(N):
    N = np.asarray(N, float)
    return np.c_[N[:, 0], N[:, 2], -N[:, 1]].astype(np.float32)


_FURN_MATS = {}


def add_flag_and_markers(glb, root, hole):
    dem = Raster(C.BUILD / "dem_final.tif")  # the surface the terrain mesh was built from
    hn = int(hole["hole"])
    grp = glb.node(f"Hole{hn:02d}_Furniture", parent=root, extras={"hole": hn})
    if not _FURN_MATS:
        _FURN_MATS["white"] = glb.material("Flagstick", base_factor=(0.92, 0.92, 0.88, 1), rough=0.4)
        _FURN_MATS["flag"] = glb.material("Flag", base_factor=(0.05, 0.18, 0.75, 1), rough=0.8, double_sided=True)
        _FURN_MATS["cup"] = glb.material("Cup", base_factor=(0.02, 0.02, 0.02, 1), rough=0.9)
        for k, c in C.TEE_COLOURS.items():
            rgb = tuple(int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))
            _FURN_MATS[k] = glb.material(f"TeeMarker_{k}", base_factor=rgb + (1,), rough=0.35)
    white, flagm, cupm = _FURN_MATS["white"], _FURN_MATS["flag"], _FURN_MATS["cup"]
    pin = next(p for p in hole["pins"] if p["name"] == "middle")
    e, n = pin["utm"][:2]; h = float(dem(e, n)[0])
    # stick 2.13 m (7 ft), 12.5 mm radius
    P, N, UV, I = cylinder(np.array([e, n, h - 0.1]), np.array([e, n, h + 2.13]), 0.0125, 0.0125)
    prims = [dict(pos=mm(P), nrm=model_vec(N), uv0=UV, idx=I, material=white)]
    # flag: slightly waving quad strip, 50 x 35 cm, flying downwind (wind from the west)
    k = 8; Pf, Nf, UVf, If = [], [], [], []
    for i in range(k + 1):
        t = i / k; x = 0.5 * t
        wave = 0.04 * np.sin(t * np.pi * 1.5)
        for zz in (2.13 - 0.35, 2.13):
            Pf.append([e + x, n + wave, h + zz]); Nf.append([0, 1, 0]); UVf.append([t, (zz - 1.78) / 0.35])
    for i in range(k):
        a, b, c, d = 2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 3
        If += [[a, c, b], [b, c, d]]
    prims.append(dict(pos=mm(np.array(Pf)), nrm=model_vec(np.array(Nf)), uv0=np.array(UVf), idx=np.array(If), material=flagm))
    # cup: dark disc 108 mm, 3 mm above the green so it never z-fights
    ang = np.linspace(0, 2 * np.pi, 25)[:-1]
    Pc = [[e, n, h + 0.003]] + [[e + 0.054 * np.cos(a), n + 0.054 * np.sin(a), float(dem(e + 0.054 * np.cos(a), n + 0.054 * np.sin(a))[0]) + 0.003] for a in ang]
    Ic = [[0, 1 + i, 1 + (i + 1) % 24] for i in range(24)]
    prims.append(dict(pos=mm(np.array(Pc)), nrm=np.tile([0, 1, 0], (25, 1)).astype(np.float32), uv0=np.zeros((25, 2)), idx=np.array(Ic), material=cupm))
    glb.node(f"Hole{hn:02d}_Flagstick", mesh=glb.mesh(f"Flagstick_{hn:02d}", prims), parent=grp)
    # tee markers: two coloured spheres per tee, 4.5 m apart across the line of play; the tee position (where the
    # yardage is measured) is the midpoint between them
    for t in hole["tees"]:
        mat = _FURN_MATS[t["key"]]
        e, n = t["utm"][:2]; hd = math.radians(t["heading_deg"])
        fwd = np.array([math.sin(hd), math.cos(hd)]); side = np.array([fwd[1], -fwd[0]])
        prims = []
        for sgn in (-1, 1):
            p = np.array([e, n]) + side * 2.25 * sgn
            gh = float(dem(*p)[0])
            S, Ns, UVs, Is = sphere(np.array([p[0], p[1], gh + 0.07]), 0.07)
            prims.append(dict(pos=mm(S), nrm=model_vec(Ns), uv0=UVs, idx=Is, material=mat))
        glb.node(f"Hole{hn:02d}_TeeMarkers_{t['key']}", mesh=glb.mesh(f"TeeMarkers_{hn:02d}_{t['key']}", prims), parent=grp)


def sphere(c, r, k=12):
    P, N, UV, I = [], [], [], []
    for i in range(k + 1):
        th = np.pi * i / k
        for j in range(k + 1):
            ph = 2 * np.pi * j / k
            nrm = np.array([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)])
            P.append(c + r * nrm); N.append(nrm); UV.append([j / k, i / k])
    for i in range(k):
        for j in range(k):
            a = i * (k + 1) + j; b = a + k + 1
            I += [[a, a + 1, b], [b, a + 1, b + 1]]
    return np.array(P), np.array(N), np.array(UV), np.array(I)


def roof_mesh(poly, dsm, dem, h_tag, tags=None, bdsm=None):
    """Triangulate the footprint (1 m interior grid, 0.5 m with `bdsm`) and lift vertices to a de-noised LiDAR roof.

    bdsm: building-class (LiDAR class 6) DSM, NaN where a cell has no building return. Preferred over the first-return
    `dsm`, which carries the crowns of trees overhanging the roof: cells without building returns take the height of
    the nearest roof vertex that has one, and the roof is rebuilt from planes (planar_roof).

    roof:shape=hipped (with height and roof:height, OSM conventions) builds a synthetic pyramid / hip roof instead: for
    shelters newer than the 2018 LiDAR, whose DSM is the tree canopy that stood there."""
    tags = tags or {}
    ring = np.asarray(poly.exterior.coords)[:-1]
    n = len(ring)
    pts = [ring]
    minx, miny, maxx, maxy = poly.bounds
    step = 0.5 if bdsm is not None else 1.0
    gx, gy = np.meshgrid(np.arange(minx + step / 2, maxx, step), np.arange(miny + step / 2, maxy, step))
    inner = poly.buffer(-0.6)
    cand = np.c_[gx.ravel(), gy.ravel()]
    if not inner.is_empty:
        import shapely
        keep = shapely.contains_xy(inner, cand[:, 0], cand[:, 1])
        cand = cand[keep]
    else:
        cand = np.zeros((0, 2))
    P2 = np.concatenate([ring] + ([cand] if len(cand) else []))
    S = np.c_[np.arange(n), (np.arange(n) + 1) % n]
    tri = triangle.triangulate({"vertices": P2 - P2.mean(0), "segments": S}, "p")
    V2 = tri["vertices"] + P2.mean(0); F = tri["triangles"]
    ground = float(np.percentile(dem(ring[:, 0], ring[:, 1]), 10))
    if tags.get("roof:shape") == "hipped" and h_tag:
        import shapely
        rise = float(tags.get("roof:height", 0.4 * h_tag))
        d = shapely.distance(shapely.points(V2), poly.exterior)
        z = ground + h_tag - rise + rise * d / max(d.max(), 1e-6)
        return V2, F, z, ground
    # roof heights: DSM sampled slightly inside the edge, clipped to a plausible band, median-smoothed
    c = np.asarray(poly.centroid.coords[0])
    inset = V2 + (c - V2) * np.clip(0.8 / (np.linalg.norm(c - V2, axis=1, keepdims=True) + 1e-6), 0, 0.5)
    from scipy.spatial import cKDTree
    if bdsm is not None:
        # building returns are clean up to the edge: a 0.3 m inset only keeps eave samples off the wall line
        ins = V2 + (c - V2) * np.clip(0.3 / (np.linalg.norm(c - V2, axis=1, keepdims=True) + 1e-6), 0, 0.5)
        zb = np.asarray(bdsm(ins[:, 0], ins[:, 1], order=0), float)
        ok = np.isfinite(zb) & (zb > ground + 1.0)
        if ok.sum() >= max(3, 0.25 * len(zb)):
            if not ok.all():
                _, j = cKDTree(V2[ok]).query(V2[~ok])
                zb[~ok] = zb[ok][j]
            zb = np.minimum(zb, np.percentile(zb, 99) + 0.2)   # stray returns (antennas, birds)
            return V2, F, planar_roof(V2, zb, poly, inset=0.3), ground
    z = dsm(inset[:, 0], inset[:, 1])
    top = ground + (h_tag if h_tag else float(np.median(z) - ground))
    # roofs are smooth planes at this scale: clamp to the tagged height band and low-pass along the mesh
    z = np.clip(z, top - 2.0, top + 0.6)
    kd = cKDTree(V2)
    nb = kd.query_ball_point(V2, 2.5)
    z = np.array([np.median(z[i]) for i in nb])
    return V2, F, z, ground


def _plane_fit(d, zb, inset, fit_d):
    """Eave height e and pitch s of zb ~ e + s * (d + inset) over the samples within fit_d of the walls (trimmed least
    squares: rooftop units and noise dropped)."""
    m = d <= fit_d
    x, y = d[m] + inset, zb[m]
    keep = np.ones(len(x), bool)
    for _ in range(4):
        A = np.c_[np.ones(keep.sum()), x[keep]]
        (e, s), *_ = np.linalg.lstsq(A, y[keep], rcond=None)
        r = y - (e + s * x)
        mad = np.median(np.abs(r[keep])) + 1e-3
        keep = np.abs(r) < 3 * 1.4826 * mad
    return float(e), float(np.clip(s, 0.0, 1.5))


def planar_roof(V2, zb, poly, inset=0.0, fit_d=4.0):
    """Roof heights at V2 made of planes: eave + pitch * distance, capped at one roof-top height per building.

    zb are building-class LiDAR heights sampled `inset` m inside the wall line. Hip roof: the distance is to the wall
    line, so every face meets its neighbours in straight ridges and hips. Gable roof (near-rectangular footprints
    only): the distance is to the two long walls, so the ridge runs the full length and the end walls are triangular.
    The model whose result is closer to the LiDAR wins (mean absolute residual). One cap per building, the 95th
    percentile of zb, gives large roofs a flat top: a local cap followed rooftop units and tree-filled cells and left
    the clubhouse's patio wing lumpy."""
    import shapely
    d_hip = shapely.distance(shapely.points(V2), poly.exterior)
    if (d_hip <= fit_d).sum() < 6:
        return np.full(len(V2), float(np.median(zb)))
    cap = float(np.percentile(zb, 95)) + 0.1
    cands = [d_hip]
    rect = poly.minimum_rotated_rectangle
    if poly.area / max(rect.area, 1e-9) > 0.85:
        r = np.asarray(rect.exterior.coords)[:4]
        e1, e2 = r[1] - r[0], r[2] - r[1]
        short = e1 if np.linalg.norm(e1) < np.linalg.norm(e2) else e2
        ay = short / np.linalg.norm(short)
        v = (V2 - r.mean(0)) @ ay
        cands.append(np.clip(np.linalg.norm(short) / 2 - np.abs(v), 0, None))
    best = None
    for d in cands:
        e, s = _plane_fit(d, zb, inset, fit_d)
        if s < 0.05:                                      # flat roof: one plane at the median height
            z = np.full(len(V2), float(np.median(zb)))
        else:
            z = np.minimum(e + s * d, cap)
        err = float(np.mean(np.abs(zb - z)))              # the ends decide hip vs gable: a mean, not a median
        if best is None or err < best[0] - 0.02:          # a gable must fit clearly better to replace the hip
            best = (err, z)
    return best[1]


WALL_PALETTE = C.as_tuples(C.REGION["buildings"]["wall_palette"])  # multipliers on the white stucco texture


def wall_colour(oid):
    """Wall tint for building `oid`: one of WALL_PALETTE, picked by a stable hash so every build agrees."""
    import zlib
    return np.asarray(WALL_PALETTE[zlib.crc32(str(oid).encode()) % len(WALL_PALETTE)], np.float32)


def roof_uv(P, N, tile=3.0):
    """Roof texture coordinates in each vertex's slope frame (u along the contour, v up the slope, `tile` m per
    repeat): top-down UVs stretch the tiles into streaks on steep hips. Flat vertices fall back to plan x / y."""
    P = np.asarray(P, float); N = np.asarray(N, float)
    g = N[:, :2]; gl = np.linalg.norm(g, axis=1)
    up = -g / np.maximum(gl, 1e-9)[:, None]                       # horizontal uphill direction
    across = np.c_[-up[:, 1], up[:, 0]]
    cz = np.clip(np.abs(N[:, 2]), 0.2, 1.0)
    uv = np.c_[np.sum(P[:, :2] * across, 1), np.sum(P[:, :2] * up, 1) / cz] / tile
    flat = gl < 1e-3
    uv[flat] = P[flat, :2] / tile
    return uv - np.floor(uv.mean(0))


def roof_normals(V2, F, z, r=2.5):
    """Vertex shading normals of a roof (n, 3, UTM axes, pointing up) from the surface averaged over `r` m: the mesh
    keeps the LiDAR heights for its outline, but per-vertex normals of that noisy surface shaded it like rock."""
    from scipy.spatial import cKDTree
    zs = np.array([z[i].mean() for i in cKDTree(V2).query_ball_point(V2, r)])
    P = np.c_[V2, zs]
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    fn *= np.sign(fn[:, 2:3] + 1e-12)
    N = np.zeros_like(P)
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    return N / (np.linalg.norm(N, axis=1, keepdims=True) + 1e-9)


def roof_tint(col):
    """Vertex tint (n, 3) of a roof from its photo colours (sRGB 0-1): the median colour for every vertex, linearised
    and normalised like the tiles' albedo."""
    m = np.median(np.asarray(col, np.float32), 0)
    lin = np.where(m <= 0.04045, m / 12.92, ((m + 0.055) / 1.055) ** 2.4)
    return np.tile(np.clip(lin / 0.35, 0, 1), (len(col), 1))


def add_buildings(glb, root):
    G = osm_geoms()
    dsm = Raster(C.BUILD / "dsm.tif"); dem = Raster(C.BUILD / "dem.tif")
    bdsm = Raster(C.BUILD / "bdsm.tif") if (C.BUILD / "bdsm.tif").exists() else None
    core = box(C.CORE["xmin"] + 1, C.CORE["ymin"] + 1, C.CORE["xmax"] - 1, C.CORE["ymax"] - 1)
    wall_m = glb.material("Wall_Stucco", base_color=_enc(PH / "white_stucco/diffuse.jpg", "albedo", 1024),
                          normal=_enc(PH / "white_stucco/nor_gl.jpg", "normal", 1024), orm=_enc(PH / "white_stucco/arm.jpg", "orm", 1024))
    facade_m = glb.material("Wall_Facade", base_color=_enc(C.DATA / "textures_gen/facade/albedo.jpg", "albedo", 1024), rough=0.85)
    roof_m = glb.material("Roof", base_color=_enc(PH / "grey_roof_tiles/diffuse.jpg", "albedo", 1024),
                          normal=_enc(PH / "grey_roof_tiles/nor_gl.jpg", "normal", 1024), orm=_enc(PH / "grey_roof_tiles/arm.jpg", "orm", 1024))
    img = rasterio.open(C.IMAGERY)
    grp = glb.node("Structures", parent=root)
    nb = 0
    for oid, t, g in G:
        if "building" not in t or g.geom_type != "Polygon" or not g.within(core) or g.area < 6:
            continue
        g = g.buffer(0)
        if g.geom_type != "Polygon":
            continue
        g = Polygon(g.exterior.coords[::-1]) if g.exterior.is_ccw is False else g
        g = Polygon(g.exterior.segmentize(1.0))   # wall-line vertices every metre: gable end walls follow the roof
        try:
            h_tag = float(t.get("height", "0") or 0)
        except ValueError:
            h_tag = 0
        V2, F, z, ground = roof_mesh(g, dsm, dem, h_tag, t, bdsm=bdsm)
        ring = np.asarray(g.exterior.coords)[:-1]; n = len(ring)
        # storeys with windows from the tagged height, else from the LiDAR eaves (the untagged clubhouse is 5-9 m)
        tall = (h_tag if h_tag else float(np.median(z[:n])) - ground) >= 5
        # roof colour from imagery
        rows, cols = rasterio.transform.rowcol(img.transform, V2[:, 0], V2[:, 1])
        a = img.read([1, 2, 3], window=rasterio.windows.Window(min(cols), min(rows), max(cols) - min(cols) + 1, max(rows) - min(rows) + 1))
        col = a[:, np.array(rows) - min(rows), np.array(cols) - min(cols)].T.astype(np.float32) / 255
        tint = roof_tint(col)
        Pr = np.c_[V2, z]
        # orient roof triangles upward
        e1 = Pr[F[:, 1]] - Pr[F[:, 0]]; e2 = Pr[F[:, 2]] - Pr[F[:, 0]]
        up = (e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) > 0
        F = np.where(up[:, None], F, F[:, [0, 2, 1]])
        Nr = roof_normals(V2, F, z, r=0.6)   # planar faces: little smoothing, crisp ridges
        prims = [dict(pos=mm(Pr), nrm=model_vec(Nr), uv0=roof_uv(Pr, Nr), idx=F, material=roof_m, col=tint)]
        # walls: from below ground to the roof edge
        Pw, Nw, UVw, Iw = [], [], [], []
        ccw = Polygon(ring).exterior.is_ccw
        for i in range(n):
            p0, p1 = ring[i], ring[(i + 1) % n]
            z0, z1 = z[i], z[(i + 1) % n]
            g0 = float(dem(*p0)[0]) - 0.3; g1 = float(dem(*p1)[0]) - 0.3
            d = p1 - p0; L = np.linalg.norm(d)
            if L < 1e-3:
                continue
            nrm = np.array([d[1], -d[0], 0]) / L
            if not ccw:
                nrm = -nrm
            b = len(Pw)
            Pw += [[*p0, g0], [*p1, g1], [*p1, z1], [*p0, z0]]
            Nw += [nrm] * 4
            if tall:  # facade tiles 4 m x 3.5 m (one storey of windows per 3.5 m)
                gb = min(g0, g1)
                UVw += [[0, -(g0 - gb) / 3.5], [L / 4, -(g1 - gb) / 3.5], [L / 4, -(z1 - gb) / 3.5], [0, -(z0 - gb) / 3.5]]
            else:
                UVw += [[0, g0 / 3], [L / 3, g1 / 3], [L / 3, z1 / 3], [0, z0 / 3]]
            Iw += [[b, b + 1, b + 2], [b, b + 2, b + 3]] if ccw else [[b, b + 2, b + 1], [b, b + 3, b + 2]]
        prims.append(dict(pos=mm(np.array(Pw)), nrm=model_vec(np.array(Nw)), uv0=np.array(UVw), idx=np.array(Iw),
                          material=facade_m if tall else wall_m, col=np.tile(wall_colour(oid), (len(Pw), 1))))
        glb.node(f"Building_{oid}", mesh=glb.mesh(f"Building_{oid}", prims), parent=grp)
        nb += 1
    print("buildings", nb)


def add_bridges(glb, root):
    G = osm_geoms()
    dem = Raster(C.BUILD / "dem.tif")
    deck_m = glb.material("Bridge_Deck", base_color=_enc(PH / "concrete_floor_worn_001/diffuse.jpg", "albedo", 1024),
                          normal=_enc(PH / "concrete_floor_worn_001/nor_gl.jpg", "normal", 1024), orm=_enc(PH / "concrete_floor_worn_001/arm.jpg", "orm", 1024))
    rail_m = glb.material("Bridge_Rail", base_factor=(0.85, 0.85, 0.82, 1), rough=0.6)
    grp = glb.node("Bridges", parent=root)
    nbr = 0
    for oid, t, g in G:
        if t.get("bridge") != "yes" or g.geom_type != "LineString":
            continue
        if not g.within(box(C.CORE["xmin"] + 5, C.CORE["ymin"] + 5, C.CORE["xmax"] - 5, C.CORE["ymax"] - 5)):
            continue
        c = np.asarray(g.coords); d = c[-1] - c[0]; L = np.linalg.norm(d); d /= L
        a, b = c[0] - d * 1.5, c[-1] + d * 1.5  # deck overlaps the path on both banks
        za, zb = float(dem(*a)[0]), float(dem(*b)[0])
        side = np.array([d[1], -d[0]]); W = 1.45
        top = max(za, zb) + 0.12
        # three-span deck: ends follow the banks, middle level at the higher bank
        m1, m2 = a + d * 1.5, b - d * 1.5
        Pd = np.array([[*(a + side * W), za + 0.06], [*(m1 + side * W), top], [*(m2 + side * W), top], [*(b + side * W), zb + 0.06],
                       [*(b - side * W), zb + 0.06], [*(m2 - side * W), top], [*(m1 - side * W), top], [*(a - side * W), za + 0.06]])
        Id = np.array([[0, 7, 1], [1, 7, 6], [1, 6, 2], [2, 6, 5], [2, 5, 3], [3, 5, 4]])
        Id = Id[:, [0, 2, 1]]
        Nd = np.tile([0, 0, 1.0], (8, 1))
        prims = [dict(pos=mm(Pd), nrm=model_vec(Nd), uv0=Pd[:, :2] / 3.0 - np.floor(Pd[:, :2].mean(0) / 3), idx=Id, material=deck_m)]
        for sgn in (1, -1):
            r0 = np.array([*(m1 + side * (W - 0.05) * sgn), top + 0.9]); r1 = np.array([*(m2 + side * (W - 0.05) * sgn), top + 0.9])
            R = cylinder(r0, r1, 0.05, 0.05, 8, cap=False)
            prims.append(dict(pos=mm(R[0]), nrm=model_vec(R[1]), uv0=R[2], idx=R[3], material=rail_m))
            for q in np.linspace(0, 1, max(2, int(np.linalg.norm(m2 - m1) / 1.5) + 1)):
                pp = m1 + (m2 - m1) * q + side * (W - 0.05) * sgn
                R = cylinder(np.array([*pp, top]), np.array([*pp, top + 0.9]), 0.05, 0.05, 6, cap=False)
                prims.append(dict(pos=mm(R[0]), nrm=model_vec(R[1]), uv0=R[2], idx=R[3], material=rail_m))
        glb.node(f"Bridge_{oid}", mesh=glb.mesh(f"Bridge_{oid}", prims), parent=grp)
        nbr += 1
    print("bridges", nbr)


PATIOS = C.SOURCES / "patios.geojson"


def patio_tables(poly, spacing=4.0, margin=1.4):
    """Dining-table centres (n, 2): a staggered grid of `spacing` aligned with the patio's long side, kept `margin` m
    inside the paving (room for the chairs)."""
    import shapely
    inner = poly.buffer(-margin)
    if inner.is_empty:
        return np.zeros((0, 2))
    r = np.asarray(poly.minimum_rotated_rectangle.exterior.coords)[:3]
    e = [r[1] - r[0], r[2] - r[1]]
    ax = max(e, key=np.linalg.norm); ax = ax / np.linalg.norm(ax); ay = np.array([-ax[1], ax[0]])
    c = np.asarray(poly.centroid.coords[0]); R = np.linalg.norm(np.asarray(poly.bounds[2:]) - poly.bounds[:2])
    dy = spacing * np.sqrt(3) / 2
    best = np.zeros((0, 2))
    for ox in np.linspace(0, spacing, 4, endpoint=False):           # pick the grid phase that seats the most tables
        for oy in np.linspace(0, dy, 3, endpoint=False):
            P = [c + ax * (i * spacing + (j % 2) * spacing / 2 + ox) + ay * (j * dy + oy)
                 for j in range(-int(R / dy) - 1, int(R / dy) + 2) for i in range(-int(R / spacing) - 1, int(R / spacing) + 2)]
            P = np.array(P); P = P[shapely.contains_xy(inner, P[:, 0], P[:, 1])]
            if len(P) > len(best):
                best = P
    return best


def add_patios(glb, root):
    """Curated paved terraces (courses/<slug>/features/patios.geojson): a paving slab 10 cm proud of the terrain, and dining tables
    with chairs and umbrellas where tables=yes."""
    if not PATIOS.exists():
        return
    import shapely
    from shapely.geometry import shape
    dem = Raster(C.BUILD / "dem.tif")
    pave = glb.material("Patio_Paving", base_color=_enc(PH / "concrete_floor_worn_001/diffuse.jpg", "albedo", 1024),
                        normal=_enc(PH / "concrete_floor_worn_001/nor_gl.jpg", "normal", 1024),
                        orm=_enc(PH / "concrete_floor_worn_001/arm.jpg", "orm", 1024))
    metal = glb.material("Patio_Metal", base_factor=(0.22, 0.22, 0.21, 1), rough=0.5, metal=0.6)
    top_m = glb.material("Patio_TableTop", base_factor=(0.55, 0.52, 0.47, 1), rough=0.6)
    canvas = glb.material("Patio_Umbrella", base_factor=(0.86, 0.84, 0.78, 1), rough=0.9, double_sided=True)
    grp = glb.node("Patios", parent=root)
    for k, f in enumerate(json.load(open(PATIOS))["features"]):
        g = shape(f["geometry"]).buffer(0)
        g = Polygon(g.exterior.coords[::-1]) if not g.exterior.is_ccw else g
        ring = np.asarray(g.exterior.coords)[:-1]; n = len(ring)
        minx, miny, maxx, maxy = g.bounds
        gx, gy = np.meshgrid(np.arange(minx + 0.5, maxx, 1.0), np.arange(miny + 0.5, maxy, 1.0))
        cand = np.c_[gx.ravel(), gy.ravel()]; cand = cand[shapely.contains_xy(g.buffer(-0.3), cand[:, 0], cand[:, 1])]
        P2 = np.concatenate([ring, cand])
        tri = triangle.triangulate({"vertices": P2 - P2.mean(0), "segments": np.c_[np.arange(n), (np.arange(n) + 1) % n]}, "p")
        V2 = tri["vertices"] + P2.mean(0); F = tri["triangles"]
        # a level slab: the median ground plus 10 cm, never below the ground by more than the skirt shows
        zg = dem(V2[:, 0], V2[:, 1]); top = float(np.percentile(zg, 70)) + 0.10
        zs = np.maximum(top, zg + 0.03)
        Pr = np.c_[V2, zs]
        e1 = Pr[F[:, 1]] - Pr[F[:, 0]]; e2 = Pr[F[:, 2]] - Pr[F[:, 0]]
        F = np.where(((e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) > 0)[:, None], F, F[:, [0, 2, 1]])
        prims = [dict(pos=mm(Pr), nrm=model_vec(np.tile([0, 0, 1.0], (len(Pr), 1))), uv0=V2 / 2.0 - np.floor(V2.mean(0) / 2.0),
                      idx=F, material=pave)]
        Ps, Ns, Us, Is = [], [], [], []   # skirt down to the ground
        for i in range(n):
            p0, p1 = ring[i], ring[(i + 1) % n]; d = p1 - p0; L = np.linalg.norm(d)
            if L < 1e-3:
                continue
            nr = np.array([d[1], -d[0], 0]) / L; b = len(Ps)
            Ps += [[*p0, zg[i] - 0.2], [*p1, zg[(i + 1) % n] - 0.2], [*p1, zs[(i + 1) % n]], [*p0, zs[i]]]
            Ns += [nr] * 4; Us += [[0, 0], [L / 2, 0], [L / 2, 0.15], [0, 0.15]]
            Is += [[b, b + 1, b + 2], [b, b + 2, b + 3]]
        prims.append(dict(pos=mm(np.array(Ps)), nrm=model_vec(np.array(Ns)), uv0=np.array(Us), idx=np.array(Is), material=pave))
        if f["properties"].get("tables") == "yes":
            def part(c0, c1, r0, r1, mat, kk=12, cap=True):
                R = cylinder(np.asarray(c0, float), np.asarray(c1, float), r0, r1, kk, cap)
                prims.append(dict(pos=mm(R[0]), nrm=model_vec(R[1]), uv0=R[2], idx=R[3], material=mat))
            rng = np.random.default_rng(k)
            for (x, y) in patio_tables(g):
                z0 = float(np.maximum(top, dem(x, y)[0] + 0.03))
                part((x, y, z0), (x, y, z0 + 0.72), 0.04, 0.04, metal, 6, False)
                part((x, y, z0 + 0.72), (x, y, z0 + 0.75), 0.5, 0.5, top_m, 16)
                part((x, y, z0 + 0.75), (x, y, z0 + 2.25), 0.025, 0.025, metal, 6, False)
                part((x, y, z0 + 1.95), (x, y, z0 + 2.4), 1.25, 0.03, canvas, 12, False)
                a0 = rng.uniform(0, np.pi / 2)
                for a in a0 + np.arange(4) * np.pi / 2:          # four chairs round each table
                    cx, cy = x + 0.8 * np.cos(a), y + 0.8 * np.sin(a)
                    part((cx, cy, z0 + 0.4), (cx, cy, z0 + 0.45), 0.22, 0.22, metal, 4)      # seat
                    part((cx, cy, z0), (cx, cy, z0 + 0.4), 0.03, 0.03, metal, 4, False)        # leg
                    bx, by = x + 1.0 * np.cos(a), y + 1.0 * np.sin(a)
                    part((bx, by, z0 + 0.45), (bx, by, z0 + 0.9), 0.04, 0.04, metal, 4, False)  # back post
        glb.node(f"Patio_{k}", mesh=glb.mesh(f"Patio_{k}", prims), parent=grp)
    print("patios", k + 1)


FOUNTAINS = C.SOURCES / "fountains.geojson"


def water_level_at(pt, planes):
    """Water level of the pond (build/water_planes.json entries) whose plane contains `pt`, else None."""
    from shapely.geometry import Polygon as _P
    for w in planes:
        if _P(w["polygon_utm"]).contains(Point(pt)):
            return float(w["level"])
    return None


def fountain_parts(c, level, height=2.5):
    """Aerating fountain: a tapering jet from the water to `height`, 20 thin jets arcing back from its top, and a
    foam disc on the water as wide as the disturbed ring in the photo. {kind: (P, N, UV, I)} in UTM."""
    x, y = c
    parts = {}
    pieces = [cylinder(np.array([x, y, level]), np.array([x, y, level + height]), 0.2, 0.06, 10, False)]
    # the spray falls back as separate arcing jets (a closed umbrella read as a glass dome)
    for j in range(20):
        a = 2 * np.pi * (j + 0.5) / 20
        t = np.linspace(0, 1, 7)
        r = 0.1 + 2.5 * t
        pts = np.c_[x + r * np.cos(a), y + r * np.sin(a), level + 0.05 + (height - 0.05) * (1 - t ** 2)]
        for i in range(6):
            pieces.append(cylinder(pts[i], pts[i + 1], 0.025 + 0.06 * t[i], 0.025 + 0.06 * t[i + 1], 5, False))
    off = np.cumsum([0] + [len(p[0]) for p in pieces[:-1]])
    parts["spray"] = tuple(np.concatenate([p[k] for p in pieces]) for k in range(3)) + (
        np.concatenate([p[3] + o for p, o in zip(pieces, off)]),)
    a = np.linspace(0, 2 * np.pi, 33)[:-1]
    Pf = np.r_[[[x, y, level + 0.03]], np.c_[x + 3.8 * np.cos(a), y + 3.8 * np.sin(a), np.full(32, level + 0.03)]]
    If = np.array([[0, 1 + j, 1 + (j + 1) % 32] for j in range(32)])
    parts["foam"] = (Pf, np.tile([0, 0, 1.0], (33, 1)), np.r_[[[0.5, 0.5]], np.c_[0.5 + 0.5 * np.cos(a), 0.5 + 0.5 * np.sin(a)]], If)
    return parts


def add_fountains(glb, root):
    """Fountains (courses/<slug>/features/fountains.geojson points) on the pond they sit in; the jet height from the `height` tag."""
    wp = C.BUILD / "water_planes.json"
    if not (FOUNTAINS.exists() and wp.exists()):
        return
    planes = json.load(open(wp))
    spray = glb.material("Fountain_Spray", base_factor=(0.93, 0.95, 0.97, 0.45), rough=0.3, alpha_mode="BLEND", double_sided=True)
    foam = glb.material("Fountain_Foam", base_factor=(0.88, 0.9, 0.9, 0.3), rough=0.6, alpha_mode="BLEND")
    grp = glb.node("Fountains", parent=root)
    n = 0
    for k, f in enumerate(json.load(open(FOUNTAINS))["features"]):
        c = f["geometry"]["coordinates"][:2]
        lv = water_level_at(c, planes)
        if lv is None:
            print("fountain", k, "is not on a water plane, skipped")
            continue
        prims = [dict(pos=mm(P), nrm=model_vec(N), uv0=UV, idx=I, material=spray if kind == "spray" else foam)
                 for kind, (P, N, UV, I) in fountain_parts(c, lv, float(f["properties"].get("height", 2.5))).items()]
        glb.node(f"Fountain_{k}", mesh=glb.mesh(f"Fountain_{k}", prims), parent=grp)
        n += 1
    print("fountains", n)


SLOT_W, SLOT_L, AISLE = C.REGION["buildings"]["parking_stall"]  # stall width, length, aisle (m)
SUV_SHARE = C.REGION["buildings"]["suv_share"]
CAR_PAINT = ((0.85, 0.85, 0.84), (0.05, 0.05, 0.06), (0.55, 0.56, 0.57), (0.3, 0.31, 0.32), (0.08, 0.12, 0.25),
             (0.45, 0.06, 0.05), (0.7, 0.7, 0.72), (0.18, 0.2, 0.18))
PARKING = C.PARKING    # OSM amenity=parking lots by the clubhouse (course.toml [structures] parking)


def parking_slots(lot, w=SLOT_W, l=SLOT_L, aisle=AISLE, exclude=None):
    """Stall centres and yaws (n, 3): back-to-back rows of w x l stalls along the lot's long side, aisles between
    the double rows; yaw turns a car whose length is along +y into its stall. Stalls within 1 m of `exclude`
    (buildings standing in the mapped lot) are dropped."""
    import shapely
    inner = lot.buffer(-0.1)
    ex = exclude.buffer(1.0) if exclude is not None and not exclude.is_empty else None
    if inner.is_empty:
        return np.zeros((0, 3))
    r = np.asarray(lot.minimum_rotated_rectangle.exterior.coords)[:3]
    e = [r[1] - r[0], r[2] - r[1]]
    ax = max(e, key=np.linalg.norm); ax = ax / np.linalg.norm(ax); ay = np.array([-ax[1], ax[0]])
    B = np.asarray(lot.exterior.coords)
    u0, u1 = (B @ ax).min(), (B @ ax).max(); v0, v1 = (B @ ay).min(), (B @ ay).max()
    yaw = math.atan2(-ay[0], ay[1])
    hw, hl = w / 2, l / 2
    corners = np.array([[-hw, -hl], [hw, -hl], [hw, hl], [-hw, hl]])
    best = np.zeros((0, 3))
    for ou in np.linspace(0, w, 3, endpoint=False):
        for ov in np.linspace(0, 2 * l + aisle, 6, endpoint=False):
            out = []
            v = v0 - (2 * l + aisle) + ov
            while v < v1:
                for vm in (v + hl, v + l + hl):
                    for um in np.arange(u0 + hw + ou, u1, w):
                        q = np.outer(corners[:, 0] + um, ax) + np.outer(corners[:, 1] + vm, ay)   # stall corners
                        if np.all(shapely.contains_xy(inner, q[:, 0], q[:, 1])) and inner.contains(Polygon(q)) and \
                                (ex is None or not ex.intersects(Polygon(q))):
                            out.append([*(um * ax + vm * ay), yaw])
                v += 2 * l + aisle
            if len(out) > len(best):
                best = np.array(out)
    return best


def _hexa(C8):
    """Flat-shaded hexahedron from 8 corners (bottom ring ccw, then top ring ccw from above)."""
    faces = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
    P, N, UV, I = [], [], [], []
    for f in faces:
        q = C8[list(f)]; nr = np.cross(q[1] - q[0], q[2] - q[0]); nr /= np.linalg.norm(nr) + 1e-12
        b = len(P); P += list(q); N += [nr] * 4; UV += [[0, 0], [1, 0], [1, 1], [0, 1]]
        I += [[b, b + 1, b + 2], [b, b + 2, b + 3]]
    return np.array(P), np.array(N), np.array(UV), np.array(I)


def _loft(bot, top):
    """Flat-shaded prism between two rings of equal length (ccw from above): sides and a top cap (no bottom)."""
    bot = np.asarray(bot, float); top = np.asarray(top, float); m = len(bot)
    P, N, UV, I = [], [], [], []
    for i in range(m):
        q = np.array([bot[i], bot[(i + 1) % m], top[(i + 1) % m], top[i]])
        nr = np.cross(q[1] - q[0], q[2] - q[0]); nr /= np.linalg.norm(nr) + 1e-12
        k = len(P); P += list(q); N += [nr] * 4; UV += [[0, 0], [1, 0], [1, 1], [0, 1]]
        I += [[k, k + 1, k + 2], [k, k + 2, k + 3]]
    c = top.mean(0); k = len(P)
    P += [c] + list(top); N += [[0, 0, 1.0]] * (m + 1); UV += [[0.5, 0.5]] * (m + 1)
    I += [[k, k + 1 + i, k + 1 + (i + 1) % m] for i in range(m)]
    return np.array(P), np.array(N), np.array(UV), np.array(I)


def _chamfered(x0, x1, y0, y1, c, z):
    """Rectangle with 45-degree corner chamfers of `c` m, ccw from above, at height z."""
    return [[x0 + c, y0, z], [x1 - c, y0, z], [x1, y0 + c, z], [x1, y1 - c, z],
            [x1 - c, y1, z], [x0 + c, y1, z], [x0, y1 - c, z], [x0, y0 + c, z]]


def car_parts(x, y, z, yaw, seed=0):
    """A low-detail parked car: a body with chamfered corners that tucks in above the belt line, a glazed cabin
    (sedan or SUV), four tyres, head and tail lights. [(P, N, UV, I, kind)] in UTM, length along the yaw-turned
    +y axis (the bonnet at +y), standing on z."""
    rng = np.random.default_rng(seed)
    suv = rng.random() < SUV_SHARE
    W = rng.uniform(1.75, 1.9); L = rng.uniform(4.4, 4.9) if not suv else rng.uniform(4.5, 4.95)
    zb0, zb1 = z + 0.22, z + (0.95 if suv else 0.8)
    zc1 = z + (rng.uniform(1.62, 1.78) if suv else rng.uniform(1.42, 1.5))
    c, s = math.cos(yaw), math.sin(yaw)
    def place(uvz):
        uvz = np.asarray(uvz, float)
        return np.c_[x + c * uvz[:, 0] - s * uvz[:, 1], y + s * uvz[:, 0] + c * uvz[:, 1], uvz[:, 2]]
    def rot(N):
        return np.c_[c * N[:, 0] - s * N[:, 1], s * N[:, 0] + c * N[:, 1], N[:, 2]]
    hw, hl = W / 2, L / 2
    out = []
    P, N, UV, I = _loft(_chamfered(-hw, hw, -hl, hl, 0.3, zb0), _chamfered(-hw + 0.07, hw - 0.07, -hl + 0.12, hl - 0.12, 0.35, zb1))
    out.append((place(P), rot(N), UV, I, "paint"))
    cb0, cb1 = (-hl + 0.35, hl - 0.75) if suv else (-hl + 0.8, hl - 1.3)
    ct0, ct1 = (cb0 + 0.15, cb1 - 0.35) if suv else (cb0 + 0.45, cb1 - 0.5)
    cw = hw - 0.1; tw = hw - (0.14 if suv else 0.24)
    P, N, UV, I = _loft(_chamfered(-cw, cw, cb0, cb1, 0.12, zb1), _chamfered(-tw, tw, ct0, ct1, 0.1, zc1))
    out.append((place(P), rot(N), UV, I, "glass"))
    for sx in (-1, 1):
        for sy in (-1, 1):
            wy = sy * (hl - 0.85); wx = sx * (hw - 0.17)
            a, b = place([[wx - 0.12, wy, z + 0.33], [wx + 0.12, wy, z + 0.33]])
            P, N, UV, I = cylinder(a, b, 0.33, 0.33, 10, True)
            out.append((P, N, UV, I, "tyre"))
        for end, kind in ((1, "headlight"), (-1, "taillight")):    # one lamp per corner, on the body's end face
            xa, xb = sorted((sx * (hw - 0.48), sx * (hw - 0.16)))
            ya, yb = sorted((end * (hl - 0.1), end * (hl - 0.01)))
            za, zc = zb1 - 0.2, zb1 - 0.07
            box8 = np.array([[xa, ya, za], [xb, ya, za], [xb, yb, za], [xa, yb, za],
                             [xa, ya, zc], [xb, ya, zc], [xb, yb, zc], [xa, yb, zc]])
            P, N, UV, I = _hexa(box8)
            out.append((place(P), rot(N), UV, I, kind))
    return out


def add_cars(glb, root, fill=0.6):
    """Parked cars in the clubhouse lots (OSM amenity=parking, PARKING): `fill` of the stalls, clear of trees,
    planted beds and the lanes round buildings."""
    import shapely
    from shapely.ops import unary_union
    G = osm_geoms()
    lots = {oid: g for oid, t, g in G if oid in PARKING and g.geom_type == "Polygon"}
    blds = [g for oid, t, g in G if "building" in t and g.geom_type in ("Polygon", "MultiPolygon")]
    from shapely.geometry import shape
    beds = [shape(f["geometry"]) for f in json.load(open(C.FEATURES / "course_surfaces.geojson"))["features"]
            if f["properties"]["surface"] == "native"] if (C.FEATURES / "course_surfaces.geojson").exists() else []
    if not lots:
        return
    dem = Raster(C.BUILD / "dem.tif")
    trees = np.zeros((0, 2))
    tf = C.FEATURES / "trees.geojson"
    if tf.exists():
        trees = np.array([f["geometry"]["coordinates"][:2] for f in json.load(open(tf))["features"]]).reshape(-1, 2)
    paint = glb.material("Car_Paint", base_factor=(1, 1, 1, 1), rough=0.3, metal=0.5)
    glass = glb.material("Car_Glass", base_factor=(0.04, 0.05, 0.06, 1), rough=0.08, metal=0.2)
    tyre = glb.material("Car_Tyre", base_factor=(0.03, 0.03, 0.03, 1), rough=0.9)
    head = glb.material("Car_Headlight", base_factor=(0.92, 0.92, 0.88, 1), rough=0.1)
    tail = glb.material("Car_Taillight", base_factor=(0.55, 0.03, 0.03, 1), rough=0.2)
    mats = {"paint": paint, "glass": glass, "tyre": tyre, "headlight": head, "taillight": tail}
    grp = glb.node("Parked_Cars", parent=root)
    rng = np.random.default_rng(11)
    n = 0
    for oid, lot in sorted(lots.items()):
        # keep a 5 m drop-off lane round buildings standing in the lot, and off the planted beds and islands
        S = parking_slots(lot, exclude=unary_union([b.buffer(4.0) for b in blds if b.buffer(5).intersects(lot)] +
                                                   [g for g in beds if g.intersects(lot)]))
        if not len(S):
            continue
        keep = rng.random(len(S)) < fill
        if len(trees):
            from scipy.spatial import cKDTree
            keep &= cKDTree(trees).query(S[:, :2])[0] > 3.0
        acc = {k: [] for k in mats}
        for i in np.flatnonzero(keep):
            x, y, yaw = S[i]
            yaw += math.pi * (rng.random() < 0.5) + rng.normal(0, 0.03)
            z = float(dem(x, y)[0])
            col = np.asarray(CAR_PAINT[rng.integers(len(CAR_PAINT))])
            for P, N, UV, I, kind in car_parts(x, y, z, yaw, seed=int(oid) % 1000 + i):
                acc[kind].append((P, N, UV, I, col if kind == "paint" else None))
            n += 1
        prims = []
        for kind, parts in acc.items():
            if not parts:
                continue
            off = np.cumsum([0] + [len(p[0]) for p in parts[:-1]])
            d = dict(pos=mm(np.concatenate([p[0] for p in parts])), nrm=model_vec(np.concatenate([p[1] for p in parts])),
                     uv0=np.concatenate([p[2] for p in parts]), idx=np.concatenate([p[3] + o for p, o in zip(parts, off)]),
                     material=mats[kind])
            if kind == "paint":
                d["col"] = np.concatenate([np.tile(p[4], (len(p[0]), 1)) for p in parts]).astype(np.float32)
            prims.append(d)
        if prims:
            glb.node(f"Parked_Cars_{oid}", mesh=glb.mesh(f"Parked_Cars_{oid}", prims), parent=grp)
    print("parked cars", n)


def _enc(path, kind, size):
    from export_course import encode
    return encode(path, kind, None, size)


def add(glb, root):
    _FURN_MATS.clear()
    for hole in json.load(open(C.OUTPUT / "holes.json"))["holes"]:
        if hole.get("pins") and hole.get("tees"):
            add_flag_and_markers(glb, root, hole)
    add_buildings(glb, root)
    add_patios(glb, root)
    add_fountains(glb, root)
    add_cars(glb, root)
    add_bridges(glb, root)
