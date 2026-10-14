"""config.py: the course loader (courses/<slug>/course.toml, chosen with COURSE=<slug>), on fresh trees and on Westmount."""
import json, os, shutil, subprocess, sys

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN = json.load(open(ROOT / "tests/fixtures/westmount_config_df7ac03.json"))

DUMP = """
import sys, json, types; sys.path.insert(0, 'scripts'); import config as C
from pathlib import Path
out = {}
for k, v in vars(C).items():
    if k.startswith('_') or isinstance(v, (types.ModuleType, types.FunctionType, type)) or k in ('os', 'tomllib'):
        continue
    if isinstance(v, Path):
        out[k] = 'PATH:' + v.relative_to(C.ROOT).as_posix()
    elif k == 'LIDAR_TILES':
        out[k] = repr([p.relative_to(C.ROOT).as_posix() for p in v])
    else:
        out[k] = repr(v)
out['course_hole'] = repr([C.course_hole(r) for r in ('1', '9', '18', '19', '0', 'x', None, 7, '07')])
out['to_model'] = repr(C.to_model(537600.5, 4810900.25, 350.0))
print(json.dumps(out))
"""

MINIMAL = """
[course]
name = "{name}"
[frame]
crs = "EPSG:2958"
origin = [500000.0, 4800000.0]
base_h = 300.0
core = {{ xmin = 499000.0, ymin = 4799000.0, xmax = 501000.0, ymax = 4801000.0 }}
terrain = {{ xmin = 498976.0, ymin = 4798976.0, xmax = 501024.0, ymax = 4801024.0 }}
[holes]
playable = "1-9"
"""


def load(root, course=None, profile="course"):
    env = {k: v for k, v in os.environ.items() if k not in ("COURSE", "MG_PROFILE")}
    env["MG_PROFILE"] = profile
    if course is not None:
        env["COURSE"] = course
    r = subprocess.run([sys.executable, "-c", DUMP], cwd=root, env=env, capture_output=True, text=True)
    return r


def tree(tmp_path, *courses):
    (tmp_path / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts/config.py", tmp_path / "scripts/config.py")
    for c in courses:
        (tmp_path / "courses" / c).mkdir(parents=True)
        (tmp_path / "courses" / c / "course.toml").write_text(MINIMAL.format(name=c.title()))
    return tmp_path


def test_westmount_loads_exactly_the_values_of_the_old_config_py():
    """course.toml carries config.py's values over unchanged, types included (tuples, floats): the build must not
    change. Only the folders move: data/, build/, output/ per course; generated features in build/<slug>/features."""
    moved = {"course": {"DATA": "data/westmount", "BUILD": "build/westmount", "FEATURES": "build/westmount/features",
                        "OUTPUT": "output/westmount"},
             "test": {"DATA": "data/westmount", "BUILD": "build/westmount-test",
                      "FEATURES": "build/westmount-test/features", "OUTPUT": "build/westmount-test/output"}}
    for profile in ("course", "test"):
        r = load(ROOT, "westmount", profile)
        assert r.returncode == 0, r.stderr
        new, old = json.loads(r.stdout), FROZEN[profile]
        for k, v in old.items():
            if k in moved[profile]:
                assert new[k] == "PATH:" + moved[profile][k], (profile, k)
            elif k in ("IMAGERY_RAW", "IMAGERY"):
                assert new[k] == v.replace("PATH:data/", "PATH:data/westmount/"), (profile, k)
            else:
                assert new.get(k) == v, (profile, k, new.get(k), v)
        assert new["COURSE_DIR"] == "PATH:courses/westmount"
        assert new["SOURCES"] == "PATH:courses/westmount/features"
        assert new["RESEARCH"] == "PATH:courses/westmount/research"
        assert new["TEST_HOLES"] == "(1, 2)"


def test_config_creates_the_build_and_output_dirs(tmp_path):
    root = tree(tmp_path, "alpha")
    r = load(root)
    assert r.returncode == 0, r.stderr
    for d in ("build/alpha", "build/alpha/features", "output/alpha"):
        assert (root / d).is_dir(), d
    assert not (root / "build/alpha-test").exists()
    r = load(root, profile="test")
    assert r.returncode == 0, r.stderr
    for d in ("build/alpha-test", "build/alpha-test/features", "build/alpha-test/output"):
        assert (root / d).is_dir(), d


def test_lidar_tiles_are_the_sorted_laz_files_of_the_course(tmp_path):
    root = tree(tmp_path, "alpha", "bravo")
    for c, names in (("alpha", ("b.laz", "a.laz", "notes.txt")), ("bravo", ("c.laz",))):
        (root / "data" / c / "lidar").mkdir(parents=True)
        for n in names:
            (root / "data" / c / "lidar" / n).write_bytes(b"")
    assert json.loads(load(root, "alpha").stdout)["LIDAR_TILES"] == repr(["data/alpha/lidar/a.laz", "data/alpha/lidar/b.laz"])


def test_two_courses_build_side_by_side_without_sharing_a_folder(tmp_path):
    root = tree(tmp_path, "alpha", "bravo")
    paths = {}
    for c in ("alpha", "bravo"):
        for profile in ("course", "test"):
            r = load(root, c, profile)
            assert r.returncode == 0, r.stderr
            v = json.loads(r.stdout)
            paths[c, profile] = {k: Path(p[5:]) for k, p in v.items() if p.startswith("PATH:") and k != "ROOT"}
    for (c, profile), ps in paths.items():
        other = "bravo" if c == "alpha" else "alpha"
        for k, p in ps.items():
            assert p.parts[1] in (c, f"{c}-test"), (c, profile, k, p)   # data/alpha, build/alpha-test, ...
            for q in [*paths[other, "course"].values(), *paths[other, "test"].values()]:
                assert not (p == q or p in q.parents or q in p.parents), (k, p, q)
    a, t = paths["alpha", "course"], paths["alpha", "test"]
    for k in ("BUILD", "FEATURES", "OUTPUT"):        # the test profile has its own build folders, the same sources
        assert a[k] != t[k] and a["BUILD"] not in t[k].parents
    for k in ("DATA", "SOURCES", "RESEARCH", "COURSE_DIR"):
        assert a[k] == t[k]


def test_the_course_must_be_named_when_there_are_several(tmp_path):
    root = tree(tmp_path, "alpha", "bravo")
    for course in (None, ""):                       # COURSE= (empty, e.g. an unset CI input) is the same as unset
        r = load(root, course)
        assert r.returncode != 0 and "COURSE" in r.stderr and "alpha" in r.stderr and "bravo" in r.stderr
    one = tree(tmp_path / "one", "alpha")
    for course in (None, ""):
        assert json.loads(load(one, course).stdout)["SLUG"] == "'alpha'"
    r = load(tree(tmp_path / "none"))
    assert r.returncode != 0 and "courses/<slug>/course.toml" in r.stderr


def test_course_slugs_cannot_collide_with_a_test_profile_folder(tmp_path):
    """build/<slug>-test is the test profile's folder: a course called alpha-test would share it with alpha's."""
    root = tree(tmp_path, "alpha", "alpha-test")
    for c in ("alpha", "alpha-test"):
        r = load(root, c)
        assert r.returncode != 0 and "alpha-test" in r.stderr and "-test" in r.stderr
    root = tree(tmp_path / "caps", "Bravo")
    r = load(root)
    assert r.returncode != 0 and "Bravo" in r.stderr


def test_a_broken_course_file_names_the_file_and_the_problem(tmp_path):
    root = tree(tmp_path, "alpha")
    toml = root / "courses/alpha/course.toml"
    toml.write_text(MINIMAL.format(name="Alpha").replace("[frame]", "[frame"))
    r = load(root)
    assert r.returncode != 0 and "courses/alpha/course.toml" in r.stderr and "Traceback" not in r.stderr
    toml.write_text(MINIMAL.format(name="Alpha").replace("base_h = 300.0", ""))
    r = load(root)
    assert r.returncode != 0 and "courses/alpha/course.toml" in r.stderr and "base_h" in r.stderr and "Traceback" not in r.stderr


def test_course_files_are_read_as_utf8_whatever_the_locale(tmp_path):
    root = tree(tmp_path, "alpha")
    toml = root / "courses/alpha/course.toml"
    toml.write_bytes(MINIMAL.format(name="Club de golf Montréal").encode("utf-8"))
    env = {k: v for k, v in os.environ.items() if k not in ("COURSE", "MG_PROFILE")}
    env.update(LC_ALL="en_US.ISO8859-1", LANG="en_US.ISO8859-1", PYTHONUTF8="0")
    probe = subprocess.run([sys.executable, "-c", "import locale; print(locale.getencoding())"], env=env,
                           capture_output=True, text=True).stdout.strip()
    if probe.replace("-", "").upper() not in ("ISO88591", "LATIN1"):
        pytest.skip(f"no ISO-8859-1 locale here ({probe})")
    r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); import config as C; "
                        "print(ascii(C.COURSE_NAME))"], cwd=root, env=env, capture_output=True, text=True)
    assert r.stdout.strip() == ascii("Club de golf Montréal"), r.stdout + r.stderr


def test_osm_refs_are_matched_as_numbers(tmp_path):
    root = tree(tmp_path, "alpha")
    toml = root / "courses/alpha/course.toml"
    toml.write_text(MINIMAL.format(name="Alpha").replace('playable = "1-9"', 'playable = "1-18"\nosm_ref = { 7 = 12, 12 = 7 }'))
    code = ("import sys; sys.path.insert(0, 'scripts'); import config as C; "
            "print(repr([C.course_hole(r) for r in ('7', '07', ' 7', 7, 7.0, '12', ' 12', 12, '3', 'x', None)]))")
    env = {k: v for k, v in os.environ.items() if k not in ("COURSE", "MG_PROFILE")}
    r = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True)
    assert r.stdout.strip() == repr([12, 12, 12, 12, 12, 7, 7, 7, 3, 99, 99]), r.stderr


def test_downloads_cover_the_course_extent_in_both_profiles(tmp_path):
    """data/<slug>/ is shared by the two profiles: a test-profile fetch on a fresh course must not leave a
    test-extent photo or OSM snapshot behind for the course build."""
    root = tree(tmp_path, "alpha")
    toml = root / "courses/alpha/course.toml"
    toml.write_text(MINIMAL.format(name="Alpha") + "[test_profile]\ncore = { xmin = 499500.0, ymin = 4799500.0, xmax = 500000.0, ymax = 4800000.0 }\n")
    c, t = (json.loads(load(root, profile=p).stdout) for p in ("course", "test"))
    assert t["CORE"] != c["CORE"] and t["FETCH_CORE"] == c["FETCH_CORE"] == c["CORE"]


def test_an_unknown_course_is_an_error(tmp_path):
    root = tree(tmp_path, "alpha")
    r = load(root, "charlie")
    assert r.returncode != 0 and "charlie" in r.stderr and "alpha" in r.stderr


def test_a_minimal_course_file_gets_the_engine_defaults(tmp_path):
    v = json.loads(load(tree(tmp_path, "alpha")).stdout)
    assert v["MODEL_NAME"] == "'alpha'" and v["COURSE_SHORT"] == "'Alpha'" and v["LAYOUT"] == "'9 holes'"
    assert v["TILE"] == "256.0" and v["DEM_RES"] == "0.25" and v["CRS_LABEL"] == "'EPSG:2958'"
    assert v["PLAYABLE"] == repr(tuple(range(1, 10))) and v["SCENERY_HOLES"] == "()"
    assert v["NINE"] == repr({h: "Front" for h in range(1, 10)})
    assert v["IMAGERY_SHIFT"] == "(0.0, 0.0)" and v["TURF_TINT"] == "None" and v["SCORECARD"] == "{}"
    assert v["TEST_HOLES"] == v["PLAYABLE"]
    assert v["course_hole"] == repr([1, 9, 99, 99, 99, 99, 99, 7, 7])
