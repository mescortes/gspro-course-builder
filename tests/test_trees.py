"""Unit tests for LiDAR tree detection on synthetic canopy height models (leaf-off speckle) and archetype rules."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import detect_trees as D  # noqa: E402

RES = 0.5


def dome(n, cy, cx, radius_m, height, rng, holes=0.0):
    yy, xx = np.mgrid[:n, :n]
    d = np.hypot(yy - cy, xx - cx) * RES
    z = np.where(d < radius_m, height * np.sqrt(np.clip(1 - (d / radius_m) ** 2, 0, 1)) ** 0.6, 0.0)
    if holes:
        z = np.where(rng.random(z.shape) < holes, 0.0, z)   # leaf-off: many first returns reach the ground
    return z.astype(np.float32)


def test_one_big_leaf_off_crown_is_one_tree():
    rng = np.random.default_rng(1)
    chm = dome(120, 60, 60, 7.0, 21.0, rng, holes=0.45)
    tops, lab = D.segment_crowns(chm, RES, leaf_off=True)
    assert len(tops[0]) == 1, f"{len(tops[0])} tops for one crown"
    area = (lab == 1).sum() * RES * RES
    assert 0.7 * np.pi * 7 ** 2 < area < 1.3 * np.pi * 7 ** 2


def test_two_neighbouring_crowns_stay_two():
    rng = np.random.default_rng(2)
    chm = np.maximum(dome(140, 70, 40, 6.0, 18.0, rng, 0.3), dome(140, 70, 100, 6.0, 20.0, rng, 0.3))
    tops, _ = D.segment_crowns(chm, RES, leaf_off=True)
    assert len(tops[0]) == 2


def test_archetype_rules_separate_conifers_from_bare_hardwoods():
    rows = []
    rng = np.random.default_rng(3)
    for k in range(60):   # leaf-off hardwoods: open (high penetration), sparse CHM, low crown NDVI (bare branches over litter)
        rows.append(dict(height=rng.uniform(12, 24), crown_r=rng.uniform(4, 7), crown_base=rng.uniform(3, 6), sharpness=rng.uniform(0.6, 1.4),
                         penetration=rng.uniform(0.35, 0.6), L=rng.uniform(32, 42), A=1.0, B=8.0, ndvi=rng.uniform(0.05, 0.2), solidity=rng.uniform(0.3, 0.55)))
    for k in range(8):    # spruces: dense, solid, green, narrow, peaked, branches to the ground
        rows.append(dict(height=rng.uniform(14, 20), crown_r=rng.uniform(2.2, 3.2), crown_base=rng.uniform(0.5, 1.5), sharpness=rng.uniform(2.5, 4),
                         penetration=rng.uniform(0.05, 0.15), L=rng.uniform(24, 29), A=-6.0, B=6.0, ndvi=rng.uniform(0.35, 0.5), solidity=rng.uniform(0.85, 0.98)))
    for k in range(5):    # white pines: tall, green, solid-ish, high crown base, flatter top
        rows.append(dict(height=rng.uniform(22, 28), crown_r=rng.uniform(4, 6), crown_base=rng.uniform(10, 14), sharpness=rng.uniform(0.8, 1.6),
                         penetration=rng.uniform(0.15, 0.25), L=rng.uniform(26, 31), A=-5.0, B=7.0, ndvi=rng.uniform(0.3, 0.45), solidity=rng.uniform(0.7, 0.9)))
    rows.append(dict(height=3.5, crown_r=1.2, crown_base=1.0, sharpness=0.7, penetration=0.4, L=35, A=0, B=7, ndvi=0.2, solidity=0.6))
    feats = [{"properties": dict(r)} for r in rows]
    D.assign_archetypes(feats)
    got = [f["properties"]["archetype"] for f in feats]
    assert all(a in ("maple", "oak") for a in got[:60]), got[:60]
    assert got[60:68].count("spruce") >= 7, got[60:68]
    assert got[68:73].count("pine") >= 4, got[68:73]
    assert got[73] == "shrub"
    assert 0.2 < got[:60].count("oak") / 60 < 0.8      # both hardwood groups are used


def test_trees_are_moved_off_tees_greens_and_bunkers():
    """Final renders: LiDAR tree positions are crown tops, so a leaning tree beside a tee lands on it, and the 2018 trees
    stand where later tees were built (hole 8). A tree within max_shift of the edge moves just outside it; deeper
    inside, it was cleared for the tee and is dropped."""
    from shapely.geometry import box, Point
    import detect_trees as DT
    tee = box(0, 0, 20, 10)
    feats = [{"geometry": {"type": "Point", "coordinates": c}, "properties": {"id": i}}
             for i, c in enumerate([(19.0, 5.0), (10.0, 5.0), (30.0, 5.0)])]
    out = DT.off_surfaces(feats, [tee], max_shift=4.0, clearance=0.75)
    ids = [f["properties"]["id"] for f in out]
    assert ids == [0, 2]
    p = Point(out[0]["geometry"]["coordinates"])
    assert not tee.contains(p) and abs(p.x - 20.75) < 0.05 and abs(p.y - 5.0) < 0.05
    assert out[1]["geometry"]["coordinates"] == (30.0, 5.0)


def test_trees_cleared_after_the_lidar_are_dropped():
    """Hole 5's 2023 Blue tee: 2018 LiDAR trees stood on its mound and in the line of play (one on the cart path), but
    the 2025 photo shows them gone. Trees within `radius` m of a reviewed clearance point are dropped, others kept."""
    pts = [(10.0, 10.0), (50.0, 50.0)]
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": c}, "properties": {"id": i}}
             for i, c in enumerate([(10.6, 10.4), (13.0, 10.0), (49.0, 50.5), (80.0, 80.0)])]
    kept = D.drop_cleared(feats, pts, radius=1.5)
    assert [f["properties"]["id"] for f in kept] == [1, 3]


def test_cleared_tree_list_is_reviewed_and_local():
    """Every clearance point carries its evidence (photo note) and sits near a post-2018 tee: hole 5 / 8 Blue."""
    import json
    from shapely.geometry import shape
    fc = json.load(open(D.C.SOURCES / "trees_cleared.geojson"))
    assert fc["features"]
    for f in fc["features"]:
        p = f["properties"]
        assert p.get("note") and p.get("hole") in (5, 8) and f["geometry"]["type"] == "Point"


def test_leaf_on_woodland_rules_separate_oaks_and_pines():
    """Northern California oak woodland (Brambles: leaf-on LiDAR, Sept 2023): gray pines are tall, narrow and open
    (the pulses pass their sparse needles), valley oaks big and broad, live oaks smaller dense rounded crowns."""
    rng = np.random.default_rng(5)
    rows = []
    for k in range(30):   # valley oaks
        rows.append(dict(height=rng.uniform(13, 20), crown_r=rng.uniform(6, 10), crown_base=rng.uniform(2, 4), sharpness=1.0,
                         penetration=rng.uniform(0.15, 0.3)))
    for k in range(30):   # live oaks
        rows.append(dict(height=rng.uniform(6, 11), crown_r=rng.uniform(3, 5), crown_base=rng.uniform(1, 2), sharpness=1.0,
                         penetration=rng.uniform(0.05, 0.15)))
    for k in range(10):   # gray pines
        rows.append(dict(height=rng.uniform(13, 22), crown_r=rng.uniform(2, 3.5), crown_base=rng.uniform(4, 8), sharpness=1.8,
                         penetration=rng.uniform(0.4, 0.6)))
    rows.append(dict(height=3.0, crown_r=1.5, crown_base=0.5, sharpness=0.7, penetration=0.2))
    P = {k: np.array([r[k] for r in rows], float) for k in rows[0]}
    prm = dict(shrub_h=4.5, pine_min_h=10.0, pine_max_ratio=0.22, pine_min_pen=0.35, big_h=12.0,
               names=dict(shrub="shrub", pine="gray_pine", big="valley_oak", other="live_oak"))
    got = D.leaf_on_woodland(P, np.full(len(rows), -1.0), prm)
    assert got[:30].count("valley_oak") >= 28 and got[30:60].count("live_oak") >= 28
    assert got[60:70].count("gray_pine") >= 9 and got[70] == "shrub"
    assert "leaf_on_woodland" in D.CLASSIFIERS


def _mountaingate(P):
    """The MountainGate build's species rule (detect_trees.assign_archetypes at git b694bd4), as it was."""
    big = P["height"] > 6
    def z(v):
        med = np.median(v[big]); mad = np.median(np.abs(v[big] - med)) * 1.4826 + 1e-6
        return (v - med) / mad
    ratio = P["crown_r"] / np.maximum(P["height"], 1)
    pine = z(P["sharpness"]) + z(P["penetration"]) + 0.5 * z(P["crown_base"]) - 0.5 * z(ratio)
    oak = -z(P["penetration"]) + z(ratio) - 0.5 * z(P["crown_base"])
    syc = z(P["L"]) + 0.7 * z(P["A"]) + 0.3 * z(P["B"])
    out = []
    for i in range(len(P["height"])):
        h = P["height"][i]
        if h < 4.5:
            out.append("shrub")
        elif h > 19 and ratio[i] < 0.3 and P["penetration"][i] > 0.3:
            out.append("eucalyptus")
        elif syc[i] > 1.6 and h > 6:
            out.append("sycamore")
        elif pine[i] > oak[i] + 0.3:
            out.append("pine")
        else:
            out.append("oak")
    return out


def test_southern_california_sorts_trees_as_mountaingate_did():
    """regions/southern_california.toml's classifier is MountainGate's z-score rule (crown structure from the LiDAR,
    crown colour from the photo), its thresholds in [trees.leaf_on_suburban_socal]: the same trees get the same
    species, under the region's names."""
    import tomllib
    prm = tomllib.load(open(ROOT / "regions/southern_california.toml", "rb"))["trees"]["leaf_on_suburban_socal"]
    rng = np.random.default_rng(11)
    n = 800
    h = rng.uniform(2, 28, n)
    P = dict(height=h, crown_r=h * rng.uniform(0.15, 0.6, n), crown_base=h * rng.uniform(0.1, 0.6, n),
             sharpness=rng.normal(0.5, 0.3, n), penetration=rng.uniform(0.05, 0.6, n), L=rng.normal(40, 6, n),
             A=rng.normal(-12, 3, n), B=rng.normal(20, 4, n))
    got = D.leaf_on_suburban_socal(P, np.full(n, -1.0), prm)
    assert got == [prm["names"][a] for a in _mountaingate(P)]
    assert {a: got.count(a) > 10 for a in prm["names"].values()} == {a: True for a in prm["names"].values()}
    # no tree over z_min_h (a course of young plantings): the z-scores are taken over every tree, not over none
    small = {k: v[h < 6] for k, v in P.items()}
    assert len(D.leaf_on_suburban_socal(small, np.full(len(small["height"]), -1.0), prm)) == len(small["height"])
    # no crown colour (NaN): never a sycamore
    nocol = dict(P, L=np.full(n, np.nan))
    assert "sycamore" not in D.leaf_on_suburban_socal(nocol, np.full(n, -1.0), prm)


def test_trees_in_a_cleared_area_are_dropped():
    """Whistle Bear: a ~70 x 65 m conifer grove the 2017 LiDAR has was stripped between 2022 and 2025. A reviewed
    clearance polygon drops every tree inside it; points still drop trees within the radius."""
    from shapely.geometry import box
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": c}, "properties": {"id": i}}
             for i, c in enumerate([(10.0, 10.0), (60.0, 40.0), (75.0, 40.0), (200.0, 200.0)])]
    kept = D.drop_cleared(feats, [(200.4, 200.0)], radius=1.5, areas=[box(0, 0, 70, 65)])
    assert [f["properties"]["id"] for f in kept] == [2]


def _one_crown_tile(tmp_path, monkeypatch, veg_cls):
    """One 4 m crown (label 1, 0.5 m grid) on flat ground (DEM 0): ground returns (class 2) every 0.5 m, and 400
    returns 3-12 m up inside the crown with the classes `veg_cls` (cycled)."""
    import laspy, rasterio
    from rasterio.transform import from_origin
    x0, y1 = 537000.0, 4810040.0
    monkeypatch.setattr(D.C, "CORE", dict(xmin=x0, ymin=y1 - 40, xmax=x0 + 40, ymax=y1))
    monkeypatch.setattr(D.C, "BUILD", tmp_path)
    with rasterio.open(tmp_path / "dem.tif", "w", driver="GTiff", width=160, height=160, count=1, dtype="float32",
                       crs="EPSG:2958", transform=from_origin(x0, y1, 0.25, 0.25)) as d:
        d.write(np.zeros((1, 160, 160), np.float32))
    yy, xx = np.mgrid[:80, :80]
    lab = (np.hypot(yy - 40, xx - 40) * RES < 4.0).astype(np.int32)
    rng = np.random.default_rng(3)
    gx, gy = (a.ravel() for a in np.meshgrid(np.arange(x0 + 0.1, x0 + 40, 0.5), np.arange(y1 - 39.9, y1, 0.5)))
    r, t = 3.0 * np.sqrt(rng.random(400)), rng.uniform(0, 2 * np.pi, 400)
    las = laspy.LasData(laspy.LasHeader(point_format=1, version="1.2"))
    las.x = np.r_[gx, x0 + 20.25 + r * np.cos(t)]; las.y = np.r_[gy, y1 - 20.25 + r * np.sin(t)]
    las.z = np.r_[np.zeros(len(gx)), rng.uniform(3.0, 12.0, 400)]
    las.classification = np.r_[np.full(len(gx), 2), np.resize(veg_cls, 400)].astype(np.uint8)
    las.write(tmp_path / "t.las")
    monkeypatch.setattr(D.C, "LIDAR_TILES", [tmp_path / "t.las"])
    return lab, from_origin(x0, y1, RES, RES)


def test_vegetation_classes_3_to_5_are_tree_returns(tmp_path, monkeypatch):
    """LiDAR that classifies its vegetation 3 / 4 / 5 (low / medium / high vegetation: Spain PNOA, Denmark, many 3DEP
    QL1 projects) rather than 1 crashed detect_trees (no class-1 returns), or with a few stray class-1 returns gave
    every crown penetration ~1 and the default crown base."""
    lab, T = _one_crown_tile(tmp_path, monkeypatch, [1])
    base1, pen1 = D.crown_base(lab, T, 1)
    assert 3.4 < base1[0] < 4.2 and 0.2 < pen1[0] < 0.5
    lab, T = _one_crown_tile(tmp_path, monkeypatch, [3, 4, 5])
    base, pen = D.crown_base(lab, T, 1)
    assert base.tolist() == base1.tolist() and pen.tolist() == pen1.tolist()


def test_trees_in_classes_the_engine_does_not_read_stop_with_the_classes_found(tmp_path, monkeypatch):
    """A tile whose trees are in a class the engine does not read (here 6, then 0 with 3 stray class-1 returns): every
    crown's penetration came out ~1 and its base the default, so the classifier found no conifers (leaf-off) or made
    every tall narrow tree a pine (leaf-on). The warning fired only without a single vegetation return and said the
    archetypes rested on the canopy shape. It now stops, names the classes found and the setting, with a way out for
    sparse LiDAR."""
    # the example to paste is the classes in force plus those found that are not ground, buildings, noise, water or
    # bridges: it used to be [1, 3, 4, 5], the default, so pasting it gave the same stop
    for cls, found, example in (([0] * 397 + [1] * 3, "0: 397", "lidar_vegetation_classes = [0, 1, 3, 4, 5]"),
                                ([1] * 3 + [25] * 397, "25: 397", "lidar_vegetation_classes = [1, 3, 4, 5, 25]")):
        lab, T = _one_crown_tile(tmp_path, monkeypatch, cls)
        with pytest.raises(SystemExit) as e:
            D.crown_base(lab, T, 1)
        msg = str(e.value)
        assert found in msg and "2: 6400" in msg and example in msg and "inside the build extent ([frame] core)" in msg
        assert "penetration" in msg and "build_all.py trees" in msg and "lidar_vegetation_min_share = 0" in msg
        assert "CORE" not in msg
    # trees in a class that is not vegetation (6, buildings): no list to paste, and never the one in force
    lab, T = _one_crown_tile(tmp_path, monkeypatch, [6])
    with pytest.raises(SystemExit) as e:
        D.crown_base(lab, T, 1)
    msg = str(e.value)
    assert "6: 400" in msg and "lidar_vegetation_classes = [1, 3, 4, 5]" not in msg
    assert "None of the other classes found is a vegetation class" in msg and "classification report" in msg
    monkeypatch.setattr(D.C, "tuning", lambda k, d: 0.0 if k == "lidar_vegetation_min_share" else d)
    base, pen = D.crown_base(lab, T, 1)                        # sparse LiDAR, classes right: the default crown bases
    assert np.isnan(base).all() and pen[0] > 0.95


def test_a_share_of_crowns_without_vegetation_returns_is_what_stops():
    """Small or sparse crowns may miss the 8 returns a crown base needs (Westmount: 3 %); the stop is for the build
    whose vegetation classes miss most crowns."""
    seen = np.bincount([1, 2, 2], minlength=256)
    D.require_vegetation(np.array([True, True, False, False]), seen)            # half: built
    D.require_vegetation(np.array([], bool), seen)                              # no crown at all
    with pytest.raises(SystemExit, match=r"only 1 of the 4 crowns \(25%\)"):
        D.require_vegetation(np.array([True, False, False, False]), seen)
