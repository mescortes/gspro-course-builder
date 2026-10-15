"""Built-course tests: data alignment, surface partition, per-hole data vs the scorecard, mesh integrity, glTF and the
GSPro/OPCD package. `pytest --course <slug> tests/test_course.py` tests courses/<slug>'s build (default Westmount);
MG_PROFILE=test checks the small test-profile build. Course-dependent limits come from course.toml [tests] (LIMITS
below); the reference course's own regressions (marked WESTMOUNT) end the file."""
import json, math, struct, sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from shapely.geometry import shape, box, Point, Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config as C  # noqa: E402

SURF = C.FEATURES / "course_surfaces.geojson"
MESH = C.BUILD / "terrain_mesh.npz"
GLB = C.OUTPUT / f"{C.MODEL_NAME}.glb"
HOLES = C.OUTPUT / "holes.json"
GSPRO = C.OUTPUT / "gspro"
FULL = C.PROFILE == "course"
PLAYABLE = list(C.PLAYABLE) if FULL else list(C.TEST_HOLES)
# course.toml [tests] overrides these. known_tee_gaps: {"<hole>.<tee key>" = max |measured - card| yards}, for
# documented mismatches between the card and the real tee boxes (say why in research/NOTES.md).
LIMITS = dict(green_area=[120.0, 1300.0], fairway_min_area=1500.0, min_bunkers=40, bunker_hollow_frac=0.85,
              green_slope_max=[7.0, 14.0], tee_gap=6.0, known_tee_gaps={})
LIMITS.update(C.TESTS)
KNOWN_TEE_GAPS = {(int(k.split(".")[0]), k.split(".")[1]): float(v) for k, v in LIMITS["known_tee_gaps"].items()}
# the reference course's own regressions (end of this file), skipped for any other course
WESTMOUNT = pytest.mark.skipif(C.SLUG != "westmount", reason="Westmount's own regressions")


@pytest.fixture(scope="module")
def feats():
    return [(shape(f["geometry"]), f["properties"]) for f in json.load(open(SURF))["features"]]


@pytest.fixture(scope="module")
def holes():
    return {h["hole"]: h for h in json.load(open(HOLES))["holes"]}


@pytest.fixture(scope="module")
def dem():
    with rasterio.open(C.BUILD / "dem_final.tif") as ds:
        return ds.read(1), ds.transform


# ---------------------------------------------------------------- surfaces
def test_partition_covers_aoi_without_overlap(feats):
    aoi = box(C.CORE["xmin"], C.CORE["ymin"], C.CORE["xmax"], C.CORE["ymax"])
    assert all(g.is_valid for g, _ in feats)
    total = sum(g.area for g, _ in feats)
    union = unary_union([g for g, _ in feats])
    assert abs(union.area - aoi.area) < 2.0, "surfaces must tile the whole build area"
    assert abs(total - union.area) < 5.0, "surfaces must not overlap"


@pytest.mark.parametrize("hn", PLAYABLE)
def test_hole_has_green_tees_fairway(feats, hn):
    hf = [(g, p) for g, p in feats if p["hole"] == hn]
    greens = [g for g, p in hf if p["surface"] == "green"]
    assert len(greens) >= 1, f"hole {hn}: no green"
    lo, hi = LIMITS["green_area"]
    assert lo < max(g.area for g in greens) < hi, f"hole {hn}: implausible green size {max(g.area for g in greens):.0f} m2"
    assert any(p["surface"] == "tee" and g.area > 15 for g, p in hf), f"hole {hn}: no tee pad"
    if C.SCORECARD[hn][0] > 3:
        assert sum(g.area for g, p in hf if p["surface"] == "fairway") > LIMITS["fairway_min_area"], f"hole {hn}: no fairway"



def test_bunkers_are_depressions_in_lidar(feats, dem):
    """Imagery-derived bunkers must coincide with LiDAR hollows (checks imagery/LiDAR co-registration)."""
    from rasterio.features import geometry_mask
    z, T = dem
    def mean_h(g):
        m = ~geometry_mask([g], out_shape=z.shape, transform=T)
        return z[m].mean()
    res = []
    for g, p in feats:
        if p["surface"] == "bunker" and p["hole"] in PLAYABLE and g.area > 20:
            ring = g.buffer(2.5).difference(g.buffer(0.5))
            res.append(mean_h(g) < mean_h(ring))
    assert len(res) >= (LIMITS["min_bunkers"] if FULL else 3)
    assert np.mean(res) > LIMITS["bunker_hollow_frac"], f"only {np.mean(res):.0%} of bunkers sit in LiDAR hollows"


def test_bunker_edges_are_sand_not_grass_faces(feats):
    """QA round 2: greenside bunkers spilled 1-2 m onto the grass faces. The outer 1 m of the automatic bunkers must be
    mostly sand in the (registered) photo: clearly green pixels (Lab a* < -14, or NDVI > 0.25 with a NIR band: the spring
    photo's turf is rarely that green) outside tree canopy stay a minority."""
    from rasterio.mask import mask as rmask
    from shapely.geometry import mapping
    from skimage.color import rgb2lab
    edges = [g.difference(g.buffer(-1.0)) for g, p in feats
             if p["surface"] == "bunker" and p["hole"] in PLAYABLE and p.get("source") != "override" and g.area > 40]
    assert len(edges) >= (LIMITS["min_bunkers"] if FULL else 3)
    flagged = total = 0
    with rasterio.open(C.IMAGERY) as ds, rasterio.open(C.BUILD / "chm.tif") as ch:
        for e in edges:
            a, t = rmask(ds, [mapping(e)], crop=True, filled=False)
            m = ~a.mask[0]
            x0, y0 = t * (0, 0)
            x1, y1 = t * (a.shape[2], a.shape[1])
            chm = ch.read(1, window=rasterio.windows.from_bounds(x0, y1, x1, y0, ch.transform),
                          out_shape=m.shape, boundless=True, fill_value=0)
            m &= chm < 2.0
            lab = rgb2lab(np.moveaxis(a.data[:3], 0, -1))
            turf = lab[..., 1] < -14
            if a.shape[0] >= 4:
                r, n = a.data[0].astype(float), a.data[3].astype(float)
                turf |= (n - r) / (n + r + 1e-3) > 0.25
            flagged += int(turf[m].sum()); total += int(m.sum())
    frac = flagged / total
    assert frac < 0.30, f"{frac:.0%} of the bunker edge strip is grass-coloured"


def test_no_height_step_around_greens(feats):
    """QA round 2: the green smoothing ended in a 6-8 cm step ~1.5 m outside the fringe. Around every green the
    smoothing correction (dem_final - dem) must change by less than 1 cm between neighbouring cells."""
    from rasterio.features import rasterize
    with rasterio.open(C.BUILD / "dem.tif") as a, rasterio.open(C.BUILD / "dem_final.tif") as b:
        d = b.read(1).astype(np.float64) - a.read(1); T = a.transform
    gf = unary_union([g for g, p in feats if p["surface"] in ("green", "fringe") and p["hole"] in PLAYABLE])
    others = unary_union([g for g, p in feats if p["surface"] in ("bunker", "tee", "cartpath", "water")]).buffer(2.0)
    ring = rasterize([(gf.buffer(3.0).difference(gf.buffer(0.5)).difference(others), 1)], out_shape=d.shape,
                     transform=T).astype(bool)
    j = np.maximum(np.pad(np.abs(np.diff(d, axis=1)), ((0, 0), (0, 1))), np.pad(np.abs(np.diff(d, axis=0)), ((0, 1), (0, 0))))
    assert ring.sum() > 1000
    assert j[ring].max() < 0.01, f"step of {j[ring].max() * 100:.1f} cm around a green"


def test_no_orphan_tees(feats):
    """QA round 2: flat lawns, terraces and court aprons passed the 'raised flat deck' test and became tee surface that
    belongs to no hole. A tee surface must belong to a hole or be a mapped OSM tee (e.g. the driving range)."""
    from surface_classify import osm_geoms
    osm_t = unary_union([g for _, t, g in osm_geoms() if t.get("golf") == "tee" and g.geom_type == "Polygon"]).buffer(2.0)
    orphans = [(round(g.area), round(g.centroid.x), round(g.centroid.y)) for g, p in feats
               if p["surface"] == "tee" and p["hole"] == 99 and g.area > 2 and g.intersection(osm_t).area < 0.25 * g.area]
    assert not orphans, f"{len(orphans)} tee patches belong to no hole: {orphans[:8]}"



# ---------------------------------------------------------------- hole data vs scorecard
def test_scorecard_is_consistent():
    """Every hole has a par and one yardage per tee; the stroke indexes are permutations of the playable holes."""
    for h in PLAYABLE:
        assert len(C.SCORECARD[h]) == 1 + len(C.TEE_KEYS), f"hole {h}: card {C.SCORECARD[h]}"
    n = len(C.PLAYABLE)
    assert sorted(C.HANDICAP.values()) == list(range(1, n + 1))
    if C.HANDICAP_WOMEN:
        assert sorted(C.HANDICAP_WOMEN.values()) == list(range(1, n + 1))


@pytest.mark.parametrize("hn", PLAYABLE)
def test_tee_yardages_match_scorecard(holes, hn):
    h = holes[hn]
    assert len(h["tees"]) == len(C.TEES)
    for t in h["tees"]:
        allowed = KNOWN_TEE_GAPS.get((hn, t["key"]), LIMITS["tee_gap"])
        assert abs(t["yards"] - t["scorecard_yards"]) <= allowed, f"hole {hn} {t['key']}: {t['yards']} vs card {t['scorecard_yards']}"


@pytest.mark.parametrize("hn", PLAYABLE)
def test_tees_ordered(holes, hn):
    ys = [{t["key"]: t["yards"] for t in holes[hn]["tees"]}[k] for k in C.TEE_KEYS]
    assert all(a >= b - 0.5 for a, b in zip(ys[:-1], ys[1:])), f"hole {hn}: tees out of order {ys}"


@pytest.mark.parametrize("hn", PLAYABLE)
def test_pins_on_green(holes, hn):
    h = holes[hn]
    green = Polygon(h["green"]["polygon_utm"])
    for pin in h["pins"]:
        assert green.buffer(0.01).contains(Point(pin["utm"][:2])), f"hole {hn} pin {pin['name']} off the green"
    pins = {p["name"]: np.asarray(p["utm"][:2]) for p in h["pins"]}
    approach_from = np.asarray(h["centerline_utm"][-2])
    v = np.asarray(h["green"]["centre_utm"][:2]) - approach_from; v /= np.linalg.norm(v)
    left = np.array([-v[1], v[0]])
    assert (pins["left"] - pins["right"]) @ left > 0, f"hole {hn}: left pin is not on the player's left"
    assert (pins["back"] - pins["front"]) @ v > 0, f"hole {hn}: back pin is not behind the front pin"


@pytest.mark.parametrize("hn", PLAYABLE)
def test_green_surface_is_smooth(holes, hn):
    """The model's putting surface follows the LiDAR and is never steeper than it (smoothing only removes noise).
    The absolute cap catches banks drawn into a green (Thompson greens tilt, but none averages 7 % on the LiDAR)."""
    from hole_data import green_analysis
    from types import SimpleNamespace
    s = holes[hn]["green"]["slope_pct"]
    green = Polygon(holes[hn]["green"]["polygon_utm"])
    with rasterio.open(C.BUILD / "dem.tif") as ds:
        win = rasterio.windows.from_bounds(*green.buffer(5).bounds, transform=ds.transform).round_offsets().round_lengths()
        raw = SimpleNamespace(z=ds.read(1, window=win), T=ds.window_transform(win))
    _, _, _, slope, inside, *_ = green_analysis(green, raw)
    raw_mean, raw_p95 = slope[inside].mean(), np.percentile(slope[inside], 95)
    assert s["mean"] <= raw_mean + 0.15 and s["p95"] <= raw_p95 + 0.3, f"hole {hn}: model {s} vs LiDAR {raw_mean:.2f}/{raw_p95:.2f}"
    assert s["mean"] < LIMITS["green_slope_max"][0] and s["p95"] < LIMITS["green_slope_max"][1], f"hole {hn} green slope {s}"




# ---------------------------------------------------------------- mesh
@pytest.fixture(scope="module")
def mesh():
    d = np.load(MESH)
    return d["V"], d["F"], d["surf"], d["hole"], [str(s) for s in d["surfaces"]]


def test_mesh_is_watertight_manifold(mesh):
    V, F, *_ = mesh
    e = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), 1)
    key = e[:, 0].astype(np.int64) * len(V) + e[:, 1]
    u, counts = np.unique(key, return_counts=True)
    assert counts.max() == 2, "non-manifold edges"
    bnd = e[np.isin(key, u[counts == 1])]
    P = V[bnd.ravel(), :2]
    on_edge = (np.isclose(P[:, 0], C.CORE["xmin"], atol=0.01) | np.isclose(P[:, 0], C.CORE["xmax"], atol=0.01) |
               np.isclose(P[:, 1], C.CORE["ymin"], atol=0.01) | np.isclose(P[:, 1], C.CORE["ymax"], atol=0.01))
    assert on_edge.all(), "open edges inside the build area (cracks)"


def test_mesh_faces_up_and_not_degenerate(mesh):
    V, F, *_ = mesh
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    area = 0.5 * np.linalg.norm(n, axis=1)
    # Triangle can leave a few mm-scale triangles where two constraint edges meet at a very sharp angle;
    # they are harmless (finite normals) but zero-area faces are not
    assert (area > 1e-8).all()
    assert (area < 1e-5).sum() < 0.003 * len(F)
    assert np.isfinite(n / np.linalg.norm(n, axis=1, keepdims=True)).all()
    assert (n[:, 2] > 0).all(), "all terrain triangles must face up (counter-clockwise from above)"


def test_mesh_surface_labels_match_polygons(mesh, feats):
    import shapely
    V, F, surf, hole, names = mesh
    cent = V[F][:, :, :2].mean(1)
    fg = [(g, p["surface"]) for g, p in feats if p["surface"] != "rough"]
    tree = shapely.STRtree([g for g, _ in fg])
    ip, ig = tree.query(shapely.points(cent), predicate="within")
    truth = np.full(len(F), "rough", object); truth[ip] = np.array([s for _, s in fg], object)[ig]
    e1 = V[F[:, 1], :2] - V[F[:, 0], :2]; e2 = V[F[:, 2], :2] - V[F[:, 0], :2]
    a = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    parent = {"bunkerlip": "bunker", "wateredge": "water"}  # OPCD edge rings are parts of their polygon
    got = np.array([parent.get(n, n) for n in names], object)[surf]
    mism = truth != got
    assert a[mism].sum() / a.sum() < 0.001


@pytest.mark.parametrize("hn", PLAYABLE)
def test_green_mesh_resolution(mesh, hn):
    V, F, surf, hole, names = mesh
    sel = (np.array(names)[surf] == "green") & (hole == hn)
    assert sel.any(), f"hole {hn}: no green triangles"
    e = np.linalg.norm(V[F[sel][:, 0]] - V[F[sel][:, 1]], axis=1)
    assert np.median(e) < 0.35, "putting surface needs a fine mesh"


def test_bunker_lips_in_mesh(mesh, feats):
    """OPCD Bunker_Lip: a ~10 cm band around every bunker on the playable holes, and the sand sits below it."""
    import edges
    V, F, surf, hole, names = mesh
    nm = np.array(names)[surf]
    e1 = V[F[:, 1], :2] - V[F[:, 0], :2]; e2 = V[F[:, 2], :2] - V[F[:, 0], :2]
    a = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    for hn in PLAYABLE:
        per = sum(g.length for g, p in feats if p["surface"] == "bunker" and p["hole"] == hn)
        if per == 0:
            continue
        lip_a = a[(nm == "bunkerlip") & (hole == hn)].sum()
        assert 0.5 * edges.LIP_W < lip_a / per < 1.5 * edges.LIP_W, f"hole {hn}: lip band {lip_a / per:.3f} m"
    # vertices shared by lip and sand faces sit below those shared by lip and turf
    lipv = np.unique(F[nm == "bunkerlip"])
    sandv = np.intersect1d(lipv, np.unique(F[nm == "bunker"]))
    outer = np.setdiff1d(lipv, np.unique(F[nm == "bunker"]))
    from scipy.spatial import cKDTree
    t = cKDTree(V[outer, :2]); d, j = t.query(V[sandv, :2])
    ok = d < 0.2
    assert ok.mean() > 0.8
    drop = V[outer[j[ok]], 2] - V[sandv[ok], 2]
    assert np.median(drop) > 0.8 * edges.LIP_DEPTH, f"median sand drop {np.median(drop) * 100:.1f} cm"


# ---------------------------------------------------------------- glTF
def read_glb(path):
    b = path.read_bytes()
    magic, ver, length = struct.unpack("<III", b[:12])
    assert magic == 0x46546C67 and ver == 2 and length == len(b)
    jl, jt = struct.unpack("<II", b[12:20])
    return json.loads(b[20:20 + jl]), b, 20 + jl + 8


@pytest.fixture(scope="module")
def glb():
    return read_glb(GLB)


def test_glb_structure_and_opcd_names(glb):
    g, _, _ = glb
    names = {n.get("name") for n in g["nodes"]}
    for hn in PLAYABLE:
        for s in ("Green", "Tee", "Flagstick"):
            assert f"Hole{hn:02d}_{s}" in names, f"Hole{hn:02d}_{s}"
    for required in ("Hole98_Concrete", "Vegetation", "VegetationLOD1", "Backdrop_Terrain"):
        assert required in names, required
    assert any(n.startswith("Hole99_Rough_t") for n in names), "course-wide rough is tiled (Hole99_Rough_tII_JJ)"
    mats = {m["name"] for m in g["materials"]}
    assert {"Green", "GreenFringe", "Fairway", "Tee", "Rough", "SemiRough", "Bunker", "Concrete"} <= mats
    assert "EXT_mesh_gpu_instancing" in g.get("extensionsUsed", [])
    assert len(g["scenes"]) == 2, "scene 0 = course + detailed trees, scene 1 = light tree LOD"
    for m in g["meshes"]:
        for p in m["primitives"]:
            assert "NORMAL" in p["attributes"] and "TEXCOORD_0" in p["attributes"]


def test_glb_opcd_edges_and_water(glb, feats):
    """OPCD objects: Hole##_Bunker_Lip; Water_Base with material slots [Water_Base, Water_Edge]; a flat WaterPlane per
    water body (its collider is the water hazard in GSPro), above the bed."""
    g, b, binoff = glb
    names = {n.get("name") for n in g["nodes"]}
    for hn in PLAYABLE:
        if any(p["surface"] == "bunker" and p["hole"] == hn for _, p in feats):
            assert f"Hole{hn:02d}_Bunker_Lip" in names, hn
    mats = [m["name"] for m in g["materials"]]
    planes = [n for n in g["nodes"] if n.get("name", "").split("_WaterPlane")[0] != n.get("name") and "mesh" in n]
    if not any(p["surface"] == "water" for _, p in feats):
        pytest.skip("no water in this build")
    assert planes, "no WaterPlane objects"
    for n in planes:
        m = g["meshes"][n["mesh"]]
        y = np.concatenate([_glb_accessor(b, g, binoff, p["attributes"]["POSITION"])[:, 1] for p in m["primitives"]])
        assert np.ptp(y) < 1e-3, f"{n['name']} is not flat"
        assert mats[m["primitives"][0]["material"]] == "WaterPlane"
    edged = [m for m in g["meshes"] if m["name"].endswith("_Water_Base") and len(m["primitives"]) == 2]
    assert edged, "no Water_Base object with an edge band"
    for m in edged:
        assert [mats[p["material"]] for p in m["primitives"]] == ["Water_Base", "Water_Edge"]


def test_water_plane_does_not_spill(dem):
    """Land inside a WaterPlane's outset (outside the water body) must stay above the water level."""
    import edges
    from rasterio.features import rasterize
    planes = json.load(open(C.BUILD / "water_planes.json"))
    feats_w = [shape(f["geometry"]) for f in json.load(open(SURF))["features"] if f["properties"]["surface"] == "water"]
    water = unary_union(feats_w).buffer(0.35) if feats_w else Polygon()
    with rasterio.open(C.BUILD / "dem_final.tif") as ds:
        z = ds.read(1); T = ds.transform
    for w in planes:
        ring = Polygon(w["polygon_utm"]).difference(water)
        if ring.is_empty:
            continue
        m = rasterize([(ring, 1)], out_shape=z.shape, transform=T, fill=0, dtype="uint8").astype(bool)
        if m.any():
            assert z[m].min() >= w["level"] - 0.005, f"water plane at {w['level']:.2f} spills over land at {z[m].min():.2f}"


def _glb_accessor(b, g, binoff, i):
    a = g["accessors"][i]; v = g["bufferViews"][a["bufferView"]]
    dt = {5126: np.float32, 5125: np.uint32, 5121: np.uint8, 5123: np.uint16}[a["componentType"]]
    n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    arr = np.frombuffer(b, dtype=dt, count=a["count"] * n, offset=binoff + v["byteOffset"]).reshape(a["count"], n)
    return arr / 255.0 if a.get("normalized") else arr


@pytest.mark.parametrize("node", ["Hole01_Fairway", "Hole01_Green", "Hole99_Rough", "Hole99_SemiRough"])
def test_turf_vertex_colours_are_near_neutral(glb, node):
    """Turf textures are recoloured to the photo's median colour, so COLOR_0 must only carry brightness variation;
    a strongly tinted COLOR_0 turns thatch/dry blades purple (regression)."""
    g, b, binoff = glb
    meshes = [m for m in g["meshes"] if m["name"] == node or m["name"].startswith(node + "_t")]
    assert meshes, node
    cols = np.concatenate([_glb_accessor(b, g, binoff, p["attributes"]["COLOR_0"])[:, :3] for m in meshes for p in m["primitives"]])
    m = cols.mean(0)
    assert m.max() / m.min() < 1.35, m


# ---------------------------------------------------------------- GSPro / OPCD package
def test_heightmap_roundtrip(dem):
    meta = json.load(open(GSPRO / "terrain.json"))
    n = meta["resolution"]
    q = np.fromfile(GSPRO / meta["heightmap"], dtype="<u2").reshape(n, n)
    lo, hi = meta["height_range_m"]
    h = lo + q.astype(float) / 65535 * (hi - lo)
    z, T = dem
    te = meta["utm_extent"]; e = C.CORE
    rng = np.random.default_rng(0)
    for _ in range(200):  # random samples well inside the build extent
        x = rng.uniform(e["xmin"] + 40, e["xmax"] - 40); y = rng.uniform(e["ymin"] + 40, e["ymax"] - 40)
        i = int(round((te["ymax"] - y) / (te["ymax"] - te["ymin"]) * (n - 1)))
        j = int(round((x - te["xmin"]) / (te["xmax"] - te["xmin"]) * (n - 1)))
        xs = te["xmin"] + j * (te["xmax"] - te["xmin"]) / (n - 1); ys = te["ymax"] - i * (te["ymax"] - te["ymin"]) / (n - 1)
        r, c = rasterio.transform.rowcol(T, xs, ys)
        assert abs(h[i, j] + meta.get("terrain_sunk_below_meshes_m", 0) - z[r, c]) < 0.3
    assert (hi - lo) / 65535 < 0.005, "16-bit quantisation step must stay below 5 mm"


def test_outer_terrain_plot():
    """OPCD 'Plot (Outer)': 4097^2 heightmap over twice the inner size, matching the backdrop DEM outside the inner
    square and sunk below the inner terrain inside it; 8192 px overlay."""
    meta = json.load(open(GSPRO / "terrain.json"))["outer"]
    n = meta["resolution"]
    q = np.fromfile(GSPRO / meta["heightmap"], dtype="<u2").reshape(n, n)
    lo, hi = meta["height_range_m"]
    h = lo + q.astype(float) / 65535 * (hi - lo)
    oe, te = meta["utm_extent"], C.TERRAIN
    assert abs((oe["xmax"] - oe["xmin"]) - 2 * (te["xmax"] - te["xmin"])) < 1e-6
    from scipy import ndimage
    with rasterio.open(C.DATA / "dem/backdrop_dem.tif") as ds:
        zb = ds.read(1).astype(np.float64); Tb = ds.transform
    def dem_at(x, y):   # bilinear, like the export (nearest-pixel differs by ~1 m on steep slopes)
        return float(ndimage.map_coordinates(zb, [[(y - Tb.f) / Tb.e - 0.5], [(x - Tb.c) / Tb.a - 0.5]], order=1)[0])
    rng = np.random.default_rng(1)
    for _ in range(200):
        i, j = rng.integers(0, n, 2)
        x = oe["xmin"] + j * (oe["xmax"] - oe["xmin"]) / (n - 1); y = oe["ymax"] - i * (oe["ymax"] - oe["ymin"]) / (n - 1)
        inside = te["xmin"] + 15 < x < te["xmax"] - 15 and te["ymin"] + 15 < y < te["ymax"] - 15
        outside = not (te["xmin"] - 1 < x < te["xmax"] + 1 and te["ymin"] - 1 < y < te["ymax"] + 1)
        if outside:
            assert abs(h[i, j] - dem_at(x, y)) < 0.05
        elif inside:
            assert abs(h[i, j] - (dem_at(x, y) - meta["sunk_inside_inner_m"])) < 0.05
    from PIL import Image as _I
    assert _I.open(GSPRO / meta["overlay"]).size == (8192, 8192)


def test_opcd_svg_layers_and_palette():
    import xml.etree.ElementTree as ET
    r = ET.parse(GSPRO / "course_opcd.svg").getroot()
    ns = {"svg": "http://www.w3.org/2000/svg"}
    INK = "{http://www.inkscape.org/namespaces/inkscape}label"
    te = C.TERRAIN
    assert r.get("width") == f"{te['xmax'] - te['xmin']}mm"
    labels = {g.get(INK) for g in r.findall("svg:g", ns)}
    assert {f"Hole{h:02d}" for h in PLAYABLE} | {"Hole98", "Hole99", "image"} <= labels
    h1 = next(g for g in r.findall("svg:g", ns) if g.get(INK) == "Hole01")
    order = [p.get("style").split(";")[0].split(":")[1] for p in h1.findall("svg:path", ns)]
    assert {"#BCE5A4", "#43E561", "#A0E5B8", "#E5E5AA", "#A4C88F"} <= set(order)  # green, fairway, tee, bunker, fringe
    assert order.index("#BCE5A4") > order.index("#A4C88F") > order.index("#43E561")  # OPCD stacking


def test_greenkeeper_covers_all_holes():
    gk = json.load(open(GSPRO / "greenkeeper.json"))
    got = [h["hole"] for h in gk["holes"]]
    if FULL:
        assert got == list(range(1, 19))
    else:
        assert set(PLAYABLE) <= set(got)
    for h in gk["holes"]:
        assert len(h["tees"]) == len(C.TEES) and len(h["pins"]) >= 4


def test_greenkeeper_gkd_hints():
    """greenkeeper.json speaks GreenKeeper's GKD vocabulary (research/GSPRO_COSMETICS.md 5): tee slots (course.toml
    gkd_slot), 'rating/slope' strings, four day pins on the green, an OB ring (pOOB) on the ground around the property, 3D water
    hazards, and the distance GreenKeeper will compute from the geometry (tee -> aim points -> green centre)."""
    gk = json.load(open(GSPRO / "greenkeeper.json"))
    g = gk["gkd"]
    from export_gspro import gkd_ratings
    assert g["tee_slots"] == dict(C.TEE_GKD)
    assert g["ratings"] == gkd_ratings(C.RATINGS, dict(C.TEE_GKD))
    ring = np.asarray(g["pOOB"]["coords"])
    assert ring.shape[1] == 3 and len(ring) > 50 and np.linalg.norm(ring[0] - ring[-1]) < 8
    te = C.TERRAIN
    assert (ring[:, 0] >= 0).all() and (ring[:, 0] <= te["xmax"] - te["xmin"]).all() and (ring[:, 2] >= 0).all()  # on the terrain (a clipped ring runs along its edge)
    meta = json.load(open(GSPRO / "terrain.json"))
    assert (ring[:, 1] >= -0.5).all() and (ring[:, 1] <= meta["terrain_size_m"]["height_y"] + 0.5).all()
    for h in gk["holes"]:
        days = {p["day"] for p in h["gkd"]["pins"]}
        assert days == {"Thursday", "Friday", "Saturday", "Sunday"}, h["hole"]
        for t in h["gkd"]["tees"]:
            assert abs(t["distance_m"] / 0.9144 - t["yards"]) < 1.0, (h["hole"], t)
    hz = [z for h in gk["holes"] for z in h["gkd"]["hazards"]]
    assert all(len(z["coords"][0]) == 3 for z in hz)
    if FULL:
        assert any(z["type"] == "water" for z in hz)


def test_tree_prefabs_and_placements():
    """Unity tree prefabs: one object per archetype x variant with _LOD0/_LOD1/_LOD2 children (Unity builds the LOD
    Group from these names); trees.csv says which prefab, yaw and scale each LiDAR tree uses (same as the viewer)."""
    import csv
    g, _, _ = read_glb(GSPRO / "tree_prefabs.glb")
    nodes = g["nodes"]
    by_name = {n["name"]: n for n in nodes}
    meta = json.load(open(GSPRO / "tree_prefabs.json"))
    assert {p["archetype"] for p in meta["prefabs"]} == set(C.TREE_ARCHETYPES)
    for p in meta["prefabs"]:
        n = by_name[p["name"]]
        kids = sorted(nodes[i]["name"] for i in n.get("children", []))
        assert kids == [f"{p['name']}_LOD{k}" for k in range(3)], kids
        assert p["ref_height_m"] > 0 and p["ref_crown_radius_m"] > 0 and p["trunk_radius_m"] > 0
    rows = list(csv.DictReader(open(GSPRO / "trees.csv")))
    assert {"prefab", "yaw_deg", "scale_xz", "scale_y"} <= set(rows[0])
    names = {p["name"] for p in meta["prefabs"]}
    ref = {p["name"]: p for p in meta["prefabs"]}
    for r in rows[::997]:
        assert r["prefab"] in names
        p = ref[r["prefab"]]
        assert abs(float(r["scale_y"]) * p["ref_height_m"] - float(r["height_m"])) < 0.05
        assert 0 <= float(r["yaw_deg"]) < 360
    assert (GSPRO / "tree_prefabs.fbx").exists() and (GSPRO / "tree_prefabs.fbx").stat().st_size > 10000


def test_3dg_grass_masks(glb):
    """COLOR_1 = 3DG vertex density masks: grass surfaces mostly 1, nothing on fairway/green; spec file present."""
    g, b, binoff = glb
    def mask(name):
        ms = [m for m in g["meshes"] if m["name"] == name or m["name"].startswith(name + "_t")]
        return np.concatenate([_glb_accessor(b, g, binoff, p["attributes"]["COLOR_1"]) for m in ms for p in m["primitives"]])
    r = mask("Hole99_Rough")[:, 0]
    assert 0.6 < r.mean() <= 1.0 and r.min() == 0.0      # mostly grass, cleared at sand / path edges
    assert mask("Hole01_Fairway")[:, :3].max() == 0.0
    spec = json.load(open(GSPRO / "grass_3dg.json"))
    assert {"SemiRough", "Rough", "DeepRough"} <= set(spec["3dg"]) and spec["3dg"]["common"]["Density Mode"] == "Vertex density"


def test_fbx_manifest_opcd_objects():
    """The FBX hand-off: course meshes carry one colour layer 'Col' (3DG masks); Water_Base has 2 material slots;
    lips and water planes are there; no flagsticks / tee markers (GSPro draws those at runtime)."""
    man = json.load(open(GSPRO / "fbx_manifest.json"))
    course = {o["name"].split(".")[0]: o for o in man["course_meshes.fbx"]}
    assert any(n.endswith("_Bunker_Lip") for n in course) and any("_WaterPlane" in n for n in course)
    for n, o in course.items():
        if "_WaterPlane" not in n:
            assert o["colour_layers"] == ["Col"], (n, o["colour_layers"])
    wb = [o for n, o in course.items() if n.endswith("_Water_Base") and len(o["materials"]) == 2]
    assert wb and all(o["materials"][:2] == ["Water_Base", "Water_Edge"] for o in wb)
    structures = [o["name"] for o in man["structures.fbx"]]
    assert not [n for n in structures if "Flag" in n or "TeeMarker" in n or "Furniture" in n]


def test_unity_editor_script_ships_and_parses():
    """The Unity helpers (Westmount menu) travel with the package; we cannot compile them without Unity, but they
    must at least be valid C# (tree-sitter parse) and use only Unity 2018.2 APIs we rely on."""
    src = (GSPRO / "unity/Editor" / C.UNITY_SCRIPT).read_bytes()
    assert b"SplatPrototype" in src and b"TerrainLayer" not in src.split(b"// Unity 2018.2")[0]  # 2018.2: no TerrainLayer
    # TerrainLayer (2018.3+) only behind the version guard; SplatPrototype is obsolete from 2018.3
    code = src.split(b"#if UNITY_2018_3_OR_NEWER")
    assert len(code) == 2 and b"TerrainLayer" not in code[0].split(b"\n", 3)[-1] and b"#else" in code[1]
    assert b"BatchingStatic" not in src, "static batching disables GPU instancing on the trees"
    ts = pytest.importorskip("tree_sitter"); tscs = pytest.importorskip("tree_sitter_c_sharp")
    tree = ts.Parser(ts.Language(tscs.language())).parse(src)
    bad = []
    def walk(n):
        if n.type == "ERROR" or n.is_missing:
            bad.append(n.start_point)
        for c in n.children:
            walk(c)
    walk(tree.root_node)
    assert not bad, f"C# syntax errors at {bad[:5]}"


def test_opcd_object_names_carry_one_surface_token(glb):
    """SetMeshMaterial.cs assigns materials / physics by substring of the object name (first match wins, case
    sensitive): every course object must carry exactly one surface token, Water_Base objects need two material slots
    (the script writes sharedMaterials[1]), no two materials may share a name (Blender renames them .001), and no
    single course mesh should be a 900k-vertex course-wide object (3DG / culling work per mesh)."""
    g, _, _ = glb
    tokens = ["_Tee", "_Fairway", "_GreenFringe", "_Green", "_SemiRough", "_DeepRough", "_Rough", "_Concrete", "_Bunker_Lip",
              "_WaterPlane", "_Pinestraw", "_Bunker", "_Water_Base", "Custom1", "Custom2"]
    covered = {"_GreenFringe": ["_Green"], "_SemiRough": ["_Rough"], "_DeepRough": ["_Rough"], "_Bunker_Lip": ["_Bunker"]}
    terrain = next(n for n in g["nodes"] if n.get("name") == "Terrain")
    for i in terrain["children"]:
        name = g["nodes"][i]["name"]
        hit = [t for t in tokens if t in name]
        hit = [t for t in hit if not any(t in covered.get(o, []) for o in hit)]
        assert len(hit) == 1, (name, hit)
    mats = [m["name"] for m in g["materials"]]
    assert len(mats) == len(set(mats)), sorted(m for m in mats if mats.count(m) > 1)
    for m in g["meshes"]:
        if m["name"].endswith("_Water_Base"):
            assert [mats[p["material"]] for p in m["primitives"]] == ["Water_Base", "Water_Edge"], m["name"]
    big = [(m["name"], sum(g["accessors"][p["attributes"]["POSITION"]]["count"] for p in m["primitives"])) for m in g["meshes"]
           if m["name"].startswith("Hole")]
    assert max(v for _, v in big) < 400_000, sorted(big, key=lambda t: -t[1])[:3]


def test_fbx_outputs_exist():
    for f in ("course_meshes.fbx", "structures.fbx", "backdrop.fbx", "trees.csv", "greenkeeper.json"):
        assert (GSPRO / f).exists() and (GSPRO / f).stat().st_size > 1000, f


def test_view_presets_are_not_inside_buildings():
    """Final renders: the clubhouse preset sat 70 m from the clubhouse centroid, i.e. on its roof (the Westmount
    clubhouse is bigger than MountainGate's). No preset camera may be inside a building footprint."""
    from surface_classify import osm_geoms
    from shapely.geometry import Point
    views = json.load(open(C.OUTPUT / "views.json"))
    blds = [g for _, t, g in osm_geoms() if "building" in t and g.geom_type == "Polygon"]
    for name, v in views.items():
        e, n = v["pos"][0] + C.ORIGIN_E, -v["pos"][2] + C.ORIGIN_N
        assert not any(g.buffer(2.0).contains(Point(e, n)) for g in blds), f"{name} camera inside a building"


# ---------------------------------------------------------------- Westmount's own regressions
@WESTMOUNT
def test_hole1_features(feats):
    """Westmount #1 (par 5): a ~675 m2 green ringed by four bunkers, plus two fairway bunkers down the right."""
    h1 = [(g, p) for g, p in feats if p["hole"] == 1]
    green = max((g for g, p in h1 if p["surface"] == "green"), key=lambda g: g.area)
    assert 450 < green.area < 900, f"hole 1 green {green.area:.0f} m2"
    near_bunkers = [g for g, p in h1 if p["surface"] == "bunker" and g.distance(green) < 6]
    assert len(near_bunkers) == 4, f"{len(near_bunkers)} greenside bunkers"
    assert all(50 < b.area < 220 for b in near_bunkers), "bunker polygons should hug the sand"
    assert len([g for g, p in h1 if p["surface"] == "bunker"]) >= 6


@WESTMOUNT
def test_water_hazard_on_hole3(holes):
    if not FULL:
        pytest.skip("hole 3 not in the test extent")
    assert any(z["type"] == "water" for z in holes[3]["hazards"]), "the pond right of the 3rd (OSM 918946248) must be a water hazard"


@WESTMOUNT
def test_hole1_regression(holes):
    h = holes[1]
    ys = {t["key"]: t["yards"] for t in h["tees"]}
    for k, card in zip(C.TEE_KEYS, C.SCORECARD[1][1:]):
        assert abs(ys[k] - card) <= 4, f"hole 1 {k}: {ys[k]} vs {card}"
    assert -8 < h["elevation_change_m"] < -3, "the 1st tee by the clubhouse sits ~6 m above the green"


@WESTMOUNT
def test_scorecard_totals():
    """Golf Canada card: par 73 (37 out / 36 in); each tee's holes add up to its published total; SI permutations."""
    assert sum(v[0] for v in C.SCORECARD.values()) == 73
    assert sum(C.SCORECARD[h][0] for h in range(1, 10)) == 37
    for i, k in enumerate(C.TEE_KEYS):
        assert sum(v[1 + i] for v in C.SCORECARD.values()) == C.RATINGS[k][4], k
    assert [C.RATINGS[k][4] for k in C.TEE_KEYS] == [7018, 6550, 6143, 5432]
    assert sorted(C.HANDICAP.values()) == list(range(1, 19))
    assert sorted(C.HANDICAP_WOMEN.values()) == list(range(1, 19))
