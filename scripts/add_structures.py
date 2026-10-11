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


def roof_mesh(poly, dsm, dem, h_tag):
    """Triangulate the footprint (1 m interior grid) and lift vertices to a de-noised LiDAR roof surface."""
    ring = np.asarray(poly.exterior.coords)[:-1]
    n = len(ring)
    pts = [ring]
    minx, miny, maxx, maxy = poly.bounds
    gx, gy = np.meshgrid(np.arange(minx + 0.5, maxx, 1.0), np.arange(miny + 0.5, maxy, 1.0))
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
    # roof heights: DSM sampled slightly inside the edge, clipped to a plausible band, median-smoothed
    c = np.asarray(poly.centroid.coords[0])
    inset = V2 + (c - V2) * np.clip(0.8 / (np.linalg.norm(c - V2, axis=1, keepdims=True) + 1e-6), 0, 0.5)
    z = dsm(inset[:, 0], inset[:, 1])
    top = ground + (h_tag if h_tag else float(np.median(z) - ground))
    # roofs are smooth planes at this scale: clamp to the tagged height band and low-pass along the mesh
    z = np.clip(z, top - 2.0, top + 0.6)
    from scipy.spatial import cKDTree
    kd = cKDTree(V2)
    nb = kd.query_ball_point(V2, 2.5)
    z = np.array([np.median(z[i]) for i in nb])
    return V2, F, z, ground


def add_buildings(glb, root):
    G = osm_geoms()
    dsm = Raster(C.BUILD / "dsm.tif"); dem = Raster(C.BUILD / "dem.tif")
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
        try:
            h_tag = float(t.get("height", "0") or 0)
        except ValueError:
            h_tag = 0
        V2, F, z, ground = roof_mesh(g, dsm, dem, h_tag)
        ring = np.asarray(g.exterior.coords)[:-1]; n = len(ring)
        # roof colour from imagery
        rows, cols = rasterio.transform.rowcol(img.transform, V2[:, 0], V2[:, 1])
        a = img.read([1, 2, 3], window=rasterio.windows.Window(min(cols), min(rows), max(cols) - min(cols) + 1, max(rows) - min(rows) + 1))
        col = a[:, np.array(rows) - min(rows), np.array(cols) - min(cols)].T.astype(np.float32) / 255
        col = ndimage.uniform_filter1d(col, 1, axis=0)
        lin = np.where(col <= 0.04045, col / 12.92, ((col + 0.055) / 1.055) ** 2.4)
        tint = np.clip(lin / 0.35, 0, 1)
        Pr = np.c_[V2, z]
        # orient roof triangles upward
        e1 = Pr[F[:, 1]] - Pr[F[:, 0]]; e2 = Pr[F[:, 2]] - Pr[F[:, 0]]
        up = (e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) > 0
        F = np.where(up[:, None], F, F[:, [0, 2, 1]])
        Nr = np.zeros_like(Pr)
        fn = np.cross(Pr[F[:, 1]] - Pr[F[:, 0]], Pr[F[:, 2]] - Pr[F[:, 0]])
        for k in range(3):
            np.add.at(Nr, F[:, k], fn)
        Nr /= np.linalg.norm(Nr, axis=1, keepdims=True) + 1e-9
        prims = [dict(pos=mm(Pr), nrm=model_vec(Nr), uv0=Pr[:, :2] / 3.0 - np.floor(Pr[:, :2].mean(0) / 3.0), idx=F, material=roof_m, col=tint)]
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
            if h_tag >= 5:  # facade tiles 4 m x 3.5 m (one storey of windows per 3.5 m)
                gb = min(g0, g1)
                UVw += [[0, -(g0 - gb) / 3.5], [L / 4, -(g1 - gb) / 3.5], [L / 4, -(z1 - gb) / 3.5], [0, -(z0 - gb) / 3.5]]
            else:
                UVw += [[0, g0 / 3], [L / 3, g1 / 3], [L / 3, z1 / 3], [0, z0 / 3]]
            Iw += [[b, b + 1, b + 2], [b, b + 2, b + 3]] if ccw else [[b, b + 2, b + 1], [b, b + 3, b + 2]]
        prims.append(dict(pos=mm(np.array(Pw)), nrm=model_vec(np.array(Nw)), uv0=np.array(UVw), idx=np.array(Iw),
                          material=facade_m if h_tag >= 5 else wall_m))
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


def _enc(path, kind, size):
    from export_course import encode
    return encode(path, kind, None, size)


def add(glb, root):
    _FURN_MATS.clear()
    for hole in json.load(open(C.OUTPUT / "holes.json"))["holes"]:
        if hole.get("pins") and hole.get("tees"):
            add_flag_and_markers(glb, root, hole)
    add_buildings(glb, root)
    add_bridges(glb, root)
