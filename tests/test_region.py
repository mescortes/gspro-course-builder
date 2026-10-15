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


SOCAL = """
import sys, json; sys.path.insert(0, 'scripts')
import config as C, region_spec, check_course as K, detect_trees as D, make_trees as M, make_foliage as F
import add_vegetation as A, fetch_textures as X, export_course as E
feats = [{"properties": dict(height=h, crown_r=r, crown_base=b, sharpness=s, penetration=p, L=40.0 + l, A=-12.0, B=20.0)}
         for h, r, b, s, p, l in ((3, 1.5, 1, 0.3, 0.2, 0), (24, 4, 9, 0.4, 0.45, 0), (10, 4, 3, 0.3, 0.2, 14)) + tuple(
             (8 + k % 9, 3 + k % 4, 2 + k % 3, 0.2 + 0.05 * (k % 5), 0.15 + 0.02 * (k % 7), (k % 11) - 5) for k in range(60))]
D.assign_archetypes(feats)
tris = {a: M.build(a, 0, "lo")[0] for a in C.TREE_ARCHETYPES}
print(json.dumps({"problems": region_spec.problems(C.REGION, scaffold=False), "report": K.course_report(),
                  "cards": {a: F.card_kind(a, F.SPEC[a]) for a in C.TREE_ARCHETYPES}, "tris": tris,
                  "bark": {a: A.BARK[a] in X.IDS for a in C.TREE_ARCHETYPES},
                  "tint": sorted(E.viewer_config()["species_tint"]), "found": sorted({f["properties"]["archetype"] for f in feats})}))
"""


def test_southern_california_reaches_every_script_that_reads_a_region(tmp_path):
    """A region for the courses round Los Angeles and San Diego (MountainGate's species: coast live oak, Aleppo pine,
    sycamore, eucalyptus, shrub). A course on it loads, check_course finds nothing missing for leaf-on data, its
    classifier sorts trees into every archetype, each archetype's tree model builds, Aleppo pine gets needle cards
    and every bark set is in fetch_textures' list."""
    shutil.copytree(ROOT / "scripts", tmp_path / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "regions").mkdir()
    shutil.copy(ROOT / "regions/southern_california.toml", tmp_path / "regions")
    (tmp_path / "courses/alpha").mkdir(parents=True)
    (tmp_path / "courses/alpha/course.toml").write_text("""
[course]
name = "Alpha"
region = "southern_california"
[frame]
crs = "EPSG:6340"
origin = [362650.0, 3775300.0]
base_h = 350.0
core = { xmin = 362394.0, ymin = 3775044.0, xmax = 362906.0, ymax = 3775556.0 }
terrain = { xmin = 361626.0, ymin = 3774276.0, xmax = 363674.0, ymax = 3776324.0 }
[lidar]
leaf_off = false
[imagery]
leaf_off = false
[holes]
playable = "1"
[[tees]]
key = "blue"
name = "Blue"
colour = "#2050c0"
gkd_slot = "Blue"
[scorecard]
1 = [4, 400]
[stroke_index]
men = [1]
women = "same"
[ratings]
blue = { men = [72.0, 130], women = [74.0, 132], yards = 400 }
[sources.lidar]
provider = "usgs_3dep"
[sources.imagery]
provider = "arcgis_imageserver"
[sources.backdrop]
provider = "cog_dem"
dtm = ["u"]
[osm]
outline = ["way/1"]
""")
    env = {k: v for k, v in os.environ.items() if k not in ("COURSE", "MG_PROFILE")}
    r = subprocess.run([sys.executable, "-c", SOCAL], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    v = json.loads(r.stdout.splitlines()[-1])
    arch = ["coast_live_oak", "aleppo_pine", "sycamore", "eucalyptus", "shrub"]
    assert v["problems"] == [] and not [x for x in v["report"] if "leaf_off" in x or "region" in x], v["report"]
    assert v["found"] == sorted(arch), v["found"]
    assert all(v["tris"][a] > 100 for a in arch) and v["bark"] == {a: True for a in arch} and v["tint"] == sorted(arch)
    assert v["cards"] == {a: "pine" if a == "aleppo_pine" else "sprites" for a in arch}


def test_southern_california_flags_leaf_off_data_and_frames_the_course_in_utm_11n():
    """The region's tree rule reads leaf-on LiDAR and a summer photo (3DEP and NAIP are both); a course flown leaf-off
    is told so. new_course frames a Los Angeles course in NAD83(2011) / UTM zone 11N."""
    import tomllib
    import check_course as K, new_course as N
    r = tomllib.load(open(ROOT / "regions/southern_california.toml", "rb"))
    class Course:
        REGION_NAME = "southern_california"; REGION = {k: v for k, v in r.items() if k in C.REGION_TABLES}
        LEAF_OFF_UNSET = (); LIDAR_LEAF_OFF = False; IMAGERY_LEAF_OFF = False
    assert K._leaf_problems(Course) == []
    Course.LIDAR_LEAF_OFF, Course.IMAGERY_LEAF_OFF = True, True
    p = K._leaf_problems(Course)
    assert len(p) == 2 and all("leaf_on_suburban_socal" in x and "regions/southern_california.toml" in x for x in p)
    assert not r["scaffold"]["lidar_leaf_off"] and not r["scaffold"]["imagery_leaf_off"]
    assert N.utm_crs(-118.49, 34.08, r["scaffold"]["datum"]) == "EPSG:6340"
