"""fingerprint.py: the build fingerprint that every engine change is checked against (synthetic files only)."""
import json, sys, zipfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fingerprint as FP  # noqa: E402
from gltf_builder import GLB  # noqa: E402


def _tif(path, a, compress="deflate", origin=(537000.0, 4811000.0)):
    with rasterio.open(path, "w", driver="GTiff", width=a.shape[1], height=a.shape[0], count=1, dtype=a.dtype,
                       crs="EPSG:2958", transform=from_origin(*origin, 0.25, 0.25), nodata=np.nan,
                       compress=compress) as d:
        d.write(a, 1)


def test_raster_digest_is_the_pixels_and_georeference_not_the_encoding(tmp_path):
    a = np.arange(64 * 48, dtype=np.float32).reshape(48, 64)
    _tif(tmp_path / "a.tif", a, "deflate"); _tif(tmp_path / "b.tif", a, "lzw")
    assert (tmp_path / "a.tif").read_bytes() != (tmp_path / "b.tif").read_bytes()
    assert FP.digest(tmp_path / "a.tif")["sha256"] == FP.digest(tmp_path / "b.tif")["sha256"]
    b = a.copy(); b[3, 5] += 0.001
    _tif(tmp_path / "c.tif", b)
    assert FP.digest(tmp_path / "c.tif")["sha256"] != FP.digest(tmp_path / "a.tif")["sha256"]
    _tif(tmp_path / "d.tif", a, origin=(537000.25, 4811000.0))           # same pixels, shifted 25 cm
    assert FP.digest(tmp_path / "d.tif")["sha256"] != FP.digest(tmp_path / "a.tif")["sha256"]


def test_npz_digest_ignores_the_zip_timestamps(tmp_path):
    V = np.random.default_rng(0).normal(size=(100, 3)).astype(np.float32); F = np.arange(30, dtype=np.int32)
    np.savez_compressed(tmp_path / "a.npz", V=V, F=F)
    with zipfile.ZipFile(tmp_path / "a.npz") as zin, zipfile.ZipFile(tmp_path / "b.npz", "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():                                       # the same arrays, saved a year earlier
            info.date_time = (2025, 1, 2, 3, 4, 6)
            zout.writestr(info, zin.read(info.filename))
    assert (tmp_path / "a.npz").read_bytes() != (tmp_path / "b.npz").read_bytes()
    assert FP.digest(tmp_path / "a.npz")["sha256"] == FP.digest(tmp_path / "b.npz")["sha256"]
    np.savez_compressed(tmp_path / "c.npz", V=V, F=F[::-1].copy())
    assert FP.digest(tmp_path / "c.npz")["sha256"] != FP.digest(tmp_path / "a.npz")["sha256"]


def test_other_files_are_hashed_byte_for_byte(tmp_path):
    (tmp_path / "a.json").write_text('{"a": 1}'); (tmp_path / "b.json").write_text('{"a":1}')
    d = FP.digest(tmp_path / "a.json")
    assert d["bytes"] == 8 and d["sha256"] != FP.digest(tmp_path / "b.json")["sha256"]


def _glb(path, n_trees=3, material="Turf"):
    g = GLB()
    m = g.material(material)
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 0, 1], [1, 0, 1]], np.float32)
    terrain = g.mesh("terrain", [dict(pos=pos, idx=np.array([0, 1, 2, 1, 3, 2]), material=m)])
    g.node("Terrain", mesh=terrain)
    tree = g.mesh("tree", [dict(pos=pos[:3], idx=np.array([0, 1, 2])), dict(pos=pos[1:], idx=np.array([0, 1, 2]))])
    t = np.zeros((n_trees, 3), np.float32); r = np.tile([0, 0, 0, 1], (n_trees, 1)).astype(np.float32)
    g.node("Trees", mesh=tree, instances=(t, r, np.ones((n_trees, 3), np.float32)))
    g.save(path)


def test_gltf_stats_count_objects_vertices_triangles_and_instances(tmp_path):
    _glb(tmp_path / "a.glb")
    s = FP.gltf_stats(tmp_path / "a.glb")
    assert s["nodes"] == 2 and s["meshes"] == 2 and s["primitives"] == 3 and s["materials"] == 1
    assert s["vertices"] == 4 + 3 + 3 and s["triangles"] == 2 + 1 + 1 and s["instances"] == 3
    assert s["node_names"] == {"Terrain": 1, "Trees": 1}
    _glb(tmp_path / "b.glb", material="Grass")                          # metadata only: same binary chunk
    t = FP.gltf_stats(tmp_path / "b.glb")
    assert t["json_sha256"] != s["json_sha256"] and t["bin_sha256"] == s["bin_sha256"]
    _glb(tmp_path / "c.glb", n_trees=4)
    u = FP.gltf_stats(tmp_path / "c.glb")
    assert u["instances"] == 4 and u["bin_sha256"] != s["bin_sha256"]


def test_summaries_explain_what_changed(tmp_path):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"surface": "green", "area": 500.4}, "geometry": None},
        {"type": "Feature", "properties": {"surface": "green", "area": 400.2}, "geometry": None},
        {"type": "Feature", "properties": {"surface": "bunker", "area": 80.0}, "geometry": None}]}
    (tmp_path / "course_surfaces.geojson").write_text(json.dumps(fc))
    s = FP.summarise(tmp_path / "course_surfaces.geojson")
    assert s["features"] == 3 and s["by_surface"] == {"bunker": [1, 80], "green": [2, 901]}
    trees = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"archetype": a, "height": 10.0}, "geometry": None} for a in ("oak", "oak", "pine")]}
    (tmp_path / "trees.geojson").write_text(json.dumps(trees))
    assert FP.summarise(tmp_path / "trees.geojson")["by_archetype"] == {"oak": 2, "pine": 1}
    holes = {"holes": [{"hole": 1, "par": 5, "tees": [{"key": "blue", "yards": 559.4}, {"key": "white", "yards": 535.0}]}]}
    (tmp_path / "holes.json").write_text(json.dumps(holes))
    assert FP.summarise(tmp_path / "holes.json")["holes"] == {"1": [5, {"blue": 559, "white": 535}]}
    np.array([0, 1000, 65535], np.uint16).tofile(tmp_path / "heightmap_4097.raw")
    assert FP.summarise(tmp_path / "heightmap_4097.raw") == {"min": 0, "max": 65535, "mean": 22178.3}


def _tree(root):
    (root / "out").mkdir(parents=True, exist_ok=True)
    (root / "out/holes.json").write_text('{"holes": []}')
    (root / "out/trees.geojson").write_text('{"type": "FeatureCollection", "features": []}')
    (root / "out/course.fbx").write_bytes(b"FBX created 2026-10-14 10:00")
    return [FP.Artefact("OUTPUT/holes.json", root / "out/holes.json", core=True),
            FP.Artefact("FEATURES/trees.geojson", root / "out/trees.geojson", core=True),
            FP.Artefact("OUTPUT/gspro/course.fbx", root / "out/course.fbx", enforced=False)]


def test_compare_fails_on_changed_missing_or_new_artefacts_only(tmp_path):
    golden = FP.compute(_tree(tmp_path))
    golden["env"] = {"machine": "A"}
    same = FP.compute(_tree(tmp_path)); same["env"] = {"machine": "B"}
    fails, notes = FP.compare(golden, same)
    assert fails == [] and any("machine" in n for n in notes)            # another machine is a note, not a failure

    arts = _tree(tmp_path)
    (tmp_path / "out/course.fbx").write_bytes(b"FBX created 2026-10-15 11:00")  # not enforced: FBX carries a timestamp
    fails, notes = FP.compare(golden, FP.compute(arts))
    assert fails == [] and any("course.fbx" in n for n in notes)

    arts = _tree(tmp_path)
    (tmp_path / "out/holes.json").write_text('{"holes": [1]}')
    arts[1].path.unlink()
    arts.append(FP.Artefact("OUTPUT/extra.json", tmp_path / "out/holes.json"))
    fails, _ = FP.compare(golden, FP.compute(arts))
    assert len(fails) == 3
    assert any("OUTPUT/holes.json" in f and "changed" in f for f in fails)
    assert any("FEATURES/trees.geojson" in f and "missing" in f for f in fails)
    assert any("OUTPUT/extra.json" in f and "new" in f for f in fails)


def test_compute_is_repeatable(tmp_path):
    a = FP.compute(_tree(tmp_path)); b = FP.compute(_tree(tmp_path))
    assert json.dumps(a["artefacts"], sort_keys=True) == json.dumps(b["artefacts"], sort_keys=True)


def test_artefact_list_covers_the_planned_golden_files():
    keys = {a.key for a in FP.artefacts() if a.core}
    for k in ("OUTPUT/holes.json", "FEATURES/course_surfaces.geojson", "FEATURES/trees.geojson",
              "OUTPUT/gspro/heightmap_4097.raw", "OUTPUT/gspro/greenkeeper.json", "OUTPUT/westmount.glb"):
        assert k in keys, k


def test_artefact_list_ignores_files_of_other_profiles_and_manual_runs(tmp_path, monkeypatch):
    """A test-profile build writes its own backdrop photos into data/imagery (another extent in the name), and
    `detect_trees.py out.geojson` leaves crowns_tmp.tif in build/: neither is part of the course build."""
    import build_backdrop as BB
    for k in ("DATA", "BUILD", "FEATURES", "OUTPUT", "ROOT"):
        monkeypatch.setattr(FP.C, k, tmp_path / k.lower())
    img = tmp_path / "data/imagery"; img.mkdir(parents=True); (tmp_path / "build").mkdir()
    for name in (BB.NEAR_IMG.name, BB.FAR_IMG.name):
        stem = name[:-4]
        for suffix in (".tif", "_nir.tif", "_summer.tif", "_raw.jpg", ".jpg"):
            (img / (stem + suffix)).write_bytes(b"x")
    (img / "backdrop_near_1_2_3_4.jpg").write_bytes(b"x"); (img / "backdrop_near_1_2_3_4.tif").write_bytes(b"x")
    for name in ("dem.tif", "crowns.tif", "crowns_tmp.tif"):
        (tmp_path / "build" / name).write_bytes(b"x")
    keys = [a.key for a in FP.artefacts() if a.path.exists()]
    assert not any("backdrop_near_1_2_3_4" in k for k in keys)
    assert sum("backdrop_" in k for k in keys) == 10
    assert "BUILD/dem.tif" in keys and "BUILD/crowns.tif" in keys and "BUILD/crowns_tmp.tif" not in keys


def test_environment_records_machine_os_and_packages():
    env = FP.environment()
    for k in ("machine", "os", "python", "cpus", "ram_gb", "packages", "gdal", "proj"):
        assert k in env, k
    assert "numpy" in env["packages"] and "rasterio" in env["packages"]
