"""Region presets (regions/<name>.toml) and course tuning: Westmount's region facts moved out of the engine unchanged."""
import json, os, shutil, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config as C  # noqa: E402

FROZEN = json.load(open(ROOT / "tests/fixtures/westmount_region_df7ac03.json"))["values"]


def test_southern_ontario_reproduces_the_old_engine_constants():
    """Species shapes, foliage, 3D grass, bark, palettes, parking, backdrop grade, GreenKeeper tee slots and turf tint
    were constants in the scripts; they now come from regions/southern_ontario.toml and Westmount's course.toml. Same
    values, same order, same number types (json.dumps tells 0 from 0.0 and keeps key order)."""
    import add_structures, add_vegetation, backdrop_objects, build_backdrop, export_course, export_gspro, grass_spec
    import make_foliage, make_trees
    now = {
        "make_trees.ARCH": make_trees.ARCH, "make_foliage.SPEC": make_foliage.SPEC, "grass_spec.SPEC": grass_spec.SPEC,
        "add_vegetation.BARK": add_vegetation.BARK, "add_structures.WALL_PALETTE": add_structures.WALL_PALETTE,
        "add_structures.PARKING_STALL": [add_structures.SLOT_W, add_structures.SLOT_L, add_structures.AISLE],
        "add_structures.PARKING": add_structures.PARKING, "backdrop_objects.ROOF_PALETTE": backdrop_objects.ROOF_PALETTE,
        "build_backdrop.SUMMER_GREEN": build_backdrop.SUMMER_GREEN,
        "build_backdrop.NDVI": [build_backdrop.NDVI_LO, build_backdrop.NDVI_HI],
        "export_gspro.GKD_TEE_SLOT": export_gspro.GKD_TEE_SLOT, "config.TURF_TINT": C.TURF_TINT,
        "config.TREE_ARCHETYPES": C.TREE_ARCHETYPES,
        "export_course.MATS.deeprough": str(export_course.MATS["deeprough"][1].relative_to(C.DATA)),
        "export_course.MATS.native": str(export_course.MATS["native"][1].relative_to(C.DATA)),
    }
    for k, v in FROZEN.items():
        assert json.dumps(now[k]) == json.dumps(v), k
    assert C.REGION_NAME == "southern_ontario"


DUMP = """
import sys, json; sys.path.insert(0, 'scripts'); import config as C
print(json.dumps({"region": C.REGION, "tint": C.TURF_TINT, "arch": C.TREE_ARCHETYPES,
                  "t": [C.tuning("a", 1.0), C.tuning("b", (1, 2)), C.tuning("c", "x"), C.tuning("d", 5)],
                  "types": [type(C.tuning("a", 1.0)).__name__, type(C.tuning("b", (1, 2))).__name__]}))
"""


def _tree(tmp_path, course_extra="", region_text=None):
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/config.py", tmp_path / "scripts/config.py")
    (tmp_path / "courses/alpha").mkdir(parents=True)
    (tmp_path / "courses/alpha/course.toml").write_text(f"""
[course]
name = "Alpha"
region = "plains"
[frame]
crs = "EPSG:2958"
origin = [500000.0, 4800000.0]
base_h = 300.0
core = {{ xmin = 499000.0, ymin = 4799000.0, xmax = 501000.0, ymax = 4801000.0 }}
terrain = {{ xmin = 498976.0, ymin = 4798976.0, xmax = 501024.0, ymax = 4801024.0 }}
{course_extra}""")
    if region_text is not None:
        (tmp_path / "regions").mkdir()
        (tmp_path / "regions/plains.toml").write_text(region_text)
    env = {k: v for k, v in os.environ.items() if k not in ("COURSE", "MG_PROFILE")}
    return subprocess.run([sys.executable, "-c", DUMP], cwd=tmp_path, env=env, capture_output=True, text=True)


REGION = """
[turf_tint]
green = [100, 120, 70]
rough = [80, 100, 60]
[trees]
archetypes = ["elm", "shrub"]
bark = { elm = "elm_bark", shrub = "bark_brown_01" }
[tuning]
a = 2
c = "region"
"""


def test_course_tables_override_the_region_key_by_key(tmp_path):
    r = _tree(tmp_path, '[turf_tint]\nrough = [1, 2, 3]\n[trees.bark]\nelm = "my_elm"\n', REGION)
    assert r.returncode == 0, r.stderr
    v = json.loads(r.stdout)
    assert v["tint"] == {"green": [100, 120, 70], "rough": [1, 2, 3]}
    assert v["arch"] == ["elm", "shrub"] and v["region"]["trees"]["bark"] == {"elm": "my_elm", "shrub": "bark_brown_01"}


def test_tuning_comes_from_the_course_then_the_region_then_the_engine_default(tmp_path):
    r = _tree(tmp_path, "[tuning]\nb = [3, 4]\nc = \"course\"\n", REGION)
    v = json.loads(r.stdout)
    assert v["t"] == [2.0, [3, 4], "course", 5]
    assert v["types"] == ["float", "tuple"]          # a TOML int for a float default stays a float; lists become tuples


def test_an_unknown_region_is_an_error(tmp_path):
    r = _tree(tmp_path)
    assert r.returncode != 0 and "plains" in r.stderr and "regions/" in r.stderr and "Traceback" not in r.stderr


def test_nine_legend_and_nine_hole_follow_the_course_nines():
    import hole_data, make_maps
    westmount = {h: "Front" if h <= 9 else "Back" for h in range(1, 19)}
    legend, colour = make_maps.nine_legend(westmount)
    assert legend == "1–9 blue · 10–18 red" and colour[3] == "#1f4fd1" and colour[12] == "#d1361f"
    three = {**{h: "North" for h in range(1, 10)}, **{h: "Lake" for h in range(10, 19)}, **{h: "South" for h in range(19, 28)}}
    legend, colour = make_maps.nine_legend(three)
    assert legend == "1–9 blue · 10–18 red · 19–27 green" and len(set(colour.values())) == 3
    assert [hole_data.nine_hole(h, westmount) for h in (1, 9, 10, 18)] == [1, 9, 1, 9]
    assert [hole_data.nine_hole(h, three) for h in (1, 19, 27)] == [1, 1, 9]
    nine = {h: "Front" for h in range(1, 10)}
    assert make_maps.nine_legend(nine)[0] == "1–9 blue" and hole_data.nine_hole(5, nine) == 5


def test_bunker_lips_cover_the_playable_holes(tmp_path):
    """edges.LIP_HOLES was range(1, 19): a 9-hole course must lip its own holes only."""
    r = _tree(tmp_path, '[holes]\nplayable = "1-9"\n', REGION)
    assert r.returncode == 0, r.stderr
    shutil.copy(ROOT / "scripts/edges.py", tmp_path / "scripts/edges.py")
    env = {k: v for k, v in os.environ.items() if k not in ("COURSE", "MG_PROFILE")}
    out = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); import edges; print(tuple(edges.LIP_HOLES))"],
                         cwd=tmp_path, env=env, capture_output=True, text=True)
    assert out.stdout.strip() == repr(tuple(range(1, 10))), out.stderr


def test_the_unity_helper_is_rendered_for_the_course():
    import export_gspro
    wm = export_gspro.unity_script()
    assert wm.startswith("// Westmount G&CC: Unity editor helpers") and "public class WestmountSetup : EditorWindow" in wm
    assert 'MenuItem("Westmount/Setup Window")' in wm and "<= 18)" in wm and "{{" not in wm
    other = export_gspro.unity_script(short="Whistle Bear GC", name="WhistleBear", last_hole=9)
    assert "Westmount" not in other and "public class WhistleBearSetup" in other and '"Assets/WhistleBear"' in other
    assert "<= 9)" in other and "{{" not in other
    ts = pytest.importorskip("tree_sitter"); tscs = pytest.importorskip("tree_sitter_c_sharp")
    tree = ts.Parser(ts.Language(tscs.language())).parse(other.encode())
    assert not tree.root_node.has_error


def test_the_viewer_gets_title_model_and_region_tints_from_a_generated_file():
    import export_course
    v = export_course.viewer_config()
    assert v["title"] == C.COURSE_SHORT and v["name"] == C.COURSE_NAME and v["model"] == f"{C.MODEL_NAME}.glb"
    assert set(v["species_tint"]) == set(C.TREE_ARCHETYPES) and v["sky"][0][0] == 0.0
    html = (ROOT / "viewer/index.html").read_text()
    assert "viewer.json" in html and "Westmount" not in html
