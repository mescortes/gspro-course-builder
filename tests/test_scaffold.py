"""Starting a course somewhere new: new_course.py, check_course.py, the course and region loaders, and the LiDAR /
photo CRS checks. Each test is a newcomer's failure that was silent or a bare traceback (synthetic data, no network)."""
import json, os, re, shutil, subprocess, sys, tomllib
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config as C  # noqa: E402
import check_course as K  # noqa: E402
import new_course as N  # noqa: E402
import region_spec  # noqa: E402

REGIONS = sorted((ROOT / "regions").glob("*.toml"))
TEMPLATE = ROOT / "regions/TEMPLATE.toml.example"
FRAME = dict(origin=[500000.0, 4800000.0], base_h=300.0,
             core=dict(xmin=499744.0, ymin=4799744.0, xmax=500256.0, ymax=4800256.0),
             terrain=dict(xmin=498976.0, ymin=4798976.0, xmax=501024.0, ymax=4801024.0))


def region(name):
    return tomllib.load(open(ROOT / "regions" / f"{name}.toml", "rb"))


def skeleton(region_name, **kw):
    args = dict(holes=list(range(1, 19)), lidar={"provider": "nrcan_copc", "zone": 17, "projects": []},
                backdrop={"provider": "cog_dem", "dtm": ["https://x/a-1m-dtm.tif"]})
    args.update(kw)
    return N.course_toml("Test Golf Club", region_name, region(region_name), "EPSG:2958", FRAME, **args)


class Card:
    """A complete course file (check_course.course_report reads these config attributes)."""
    PLAYABLE = (1, 2); SCENERY_HOLES = (); NINE = {1: "Front", 2: "Front"}
    TEES = (("blue", "Blue", "#00f"),); TEE_KEYS = ("blue",); TEE_GKD = {"blue": "Blue"}
    SCORECARD = {1: (4, 400), 2: (3, 150)}; HANDICAP = {1: 1, 2: 2}; HANDICAP_WOMEN = {1: 2, 2: 1}
    RATINGS = {"blue": (72.0, 130, None, None, 550)}
    REGION_NAME = "southern_ontario"; REGION = {k: v for k, v in region("southern_ontario").items() if k in C.REGION_TABLES}
    DATA_SOURCES = {"lidar": {"provider": "nrcan_copc", "zone": 17, "projects": [{"folder": "ON/A", "suffix": "A"}]},
                    "imagery": {"provider": "arcgis_imageserver"}, "backdrop": {"provider": "cog_dem", "dtm": ["u"]}}
    OSM_OUTLINE = (); LEAF_OFF_UNSET = (); LIDAR_LEAF_OFF = True; IMAGERY_LEAF_OFF = True
    UNITY_SCRIPT = "TestSetup.cs"; UNITY_NAME = "Test"


def test_the_complete_card_has_no_gaps():
    assert K.course_report(Card) == []


# ---- course loader (config.py), on course trees of their own
MINIMAL = """
[course]
name = "Alpha"
[frame]
crs = "EPSG:2958"
origin = [500000.0, 4800000.0]
base_h = 300.0
core = { xmin = 499000.0, ymin = 4799000.0, xmax = 501000.0, ymax = 4801000.0 }
terrain = { xmin = 498976.0, ymin = 4798976.0, xmax = 501024.0, ymax = 4801024.0 }
"""


def load(tmp_path, extra="", slug="alpha", code="print(repr(C.SCORECARD))"):
    (tmp_path / "scripts").mkdir(exist_ok=True)
    shutil.copy(ROOT / "scripts/config.py", tmp_path / "scripts/config.py")
    (tmp_path / "courses" / slug).mkdir(parents=True, exist_ok=True)
    (tmp_path / "courses" / slug / "course.toml").write_text(MINIMAL + extra)
    env = {k: v for k, v in os.environ.items() if k not in ("COURSE", "MG_PROFILE")}
    return subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); import config as C; " + code],
                          cwd=tmp_path, env=env, capture_output=True, text=True)


# ---- leaf state
def test_the_skeleton_writes_both_leaf_off_flags_to_check_against_the_dates():
    """The skeleton wrote no [lidar] / [imagery] leaf_off, so a Southern Ontario course on the region's leaf-off spring
    LiDAR and photo built with leaf-on rules (one oak became five trees, bunkers under bare branches were dropped)."""
    for name, want in (("southern_ontario", True), ("northern_california", False)):
        text = skeleton(name)
        t = tomllib.loads(text)
        assert t["lidar"]["leaf_off"] is want and t["imagery"]["leaf_off"] is want, name
        lidar_line = next(l for l in text.splitlines() if l.startswith("leaf_off") and "flight" in l)
        photo_line = next(l for l in text.splitlines() if l.startswith("leaf_off") and "photo" in l)
        assert lidar_line != photo_line


def test_the_loader_says_which_leaf_off_flags_the_course_leaves_out(tmp_path):
    assert C.LEAF_OFF_UNSET == ()                                         # Westmount sets both
    r = load(tmp_path, code="print(repr(C.LEAF_OFF_UNSET), C.LIDAR_LEAF_OFF, C.IMAGERY_LEAF_OFF)")
    assert r.stdout.split() == ["('lidar',", "'imagery')", "False", "False"], r.stderr
    r = load(tmp_path, "[lidar]\nleaf_off = true\n", code="print(repr(C.LEAF_OFF_UNSET), C.LIDAR_LEAF_OFF)")
    assert r.stdout.split() == ["('imagery',)", "True"], r.stderr


def test_a_missing_leaf_off_flag_is_reported():
    class NoFlags(Card):
        LEAF_OFF_UNSET = ("lidar", "imagery"); LIDAR_LEAF_OFF = False; IMAGERY_LEAF_OFF = False
        REGION = {k: v for k, v in region("northern_california").items() if k in C.REGION_TABLES}
    p = "\n".join(K.course_report(NoFlags))
    assert "[lidar] leaf_off" in p and "[imagery] leaf_off" in p and "flight" in p and "photo" in p


@pytest.mark.parametrize("name, lidar, imagery, flagged", [
    ("southern_ontario", True, True, ()), ("southern_ontario", False, True, ("lidar",)),
    ("southern_ontario", True, False, ("imagery",)), ("northern_california", False, False, ()),
    ("northern_california", True, False, ("lidar",))])
def test_a_tree_classifier_that_does_not_suit_the_leaf_state_is_reported(name, lidar, imagery, flagged):
    """leaf_off_parkland calls a tree a conifer when few pulses get through it: on leaf-on LiDAR nearly every hardwood
    became spruce or pine. leaf_on_woodland calls a tall open crown a pine: on leaf-off LiDAR every bare hardwood is
    one. The region file says which leaf state its classifier's rules were tuned on."""
    class Course(Card):
        REGION_NAME = name; REGION = {k: v for k, v in region(name).items() if k in C.REGION_TABLES}
        LIDAR_LEAF_OFF = lidar; IMAGERY_LEAF_OFF = imagery
    p = [x for x in K.course_report(Course) if "classifier" in x]
    assert len(p) == len(flagged), p
    for what, x in zip(flagged, p):
        assert f"[{what}] leaf_off" in x and Course.REGION["trees"]["classifier"] in x and f"regions/{name}.toml" in x


def test_a_region_says_which_leaf_state_its_classifier_is_tuned_on():
    """The classifier's lidar_leaf_off was optional in region_spec but required by a unit test of its own, so a new
    region without it passed check_course and then failed the unit tests with a bare 'AssertionError: <stem>'. It is
    required (every classifier reads the LiDAR), and the region's usual data ([scaffold]) must be the leaf state its
    classifier is tuned on; region_spec checks both, tests/test_robustness.py runs it over every region."""
    r = region("southern_ontario")
    del r["trees"]["leaf_off_parkland"]["lidar_leaf_off"]
    assert any("[trees.leaf_off_parkland] lidar_leaf_off: missing" in x for x in region_spec.problems(r))
    for key in ("lidar_leaf_off", "imagery_leaf_off"):
        r = region("southern_ontario")
        r["scaffold"][key] = False
        p = [x for x in region_spec.problems(r) if f"[scaffold] {key}" in x]
        assert len(p) == 1 and "leaf_off_parkland" in p[0] and "leaf-on" in p[0] and "leaf-off" in p[0], p
    r = region("northern_california")             # its classifier does not read the photo: nothing to compare
    assert "imagery_leaf_off" not in r["trees"]["leaf_on_woodland"] and region_spec.problems(r) == []
    merged = {k: v for k, v in region("southern_ontario").items() if k != "scaffold"}    # config.REGION
    assert region_spec.problems(merged, scaffold=False) == []


# ---- frame CRS
def test_a_datum_without_utm_names_gets_the_candidates_and_the_ways_out():
    """GDA2020's zones are 'MGA zone 56' in EPSG: new_course stopped at "no EPSG code for 'GDA2020 / UTM zone 56S'"
    with no way to give the CRS."""
    with pytest.raises(SystemExit) as e:
        N.utm_crs(151.2, -33.8, "GDA2020")
    msg = str(e.value)
    assert "GDA2020 / MGA zone 56" in msg and "EPSG:7856" in msg and "--crs" in msg and "[scaffold] crs" in msg
    assert N.utm_crs(151.2, -33.8, "GDA2020", "GDA2020 / MGA zone {zone}") == "EPSG:7856"
    assert N.utm_crs(-1.5, 52.5, "OSGB36", "EPSG:27700") == "EPSG:27700"
    assert N.utm_crs(-80.39, 43.36, "NAD83(CSRS)") == "EPSG:2958"          # the regions without a template
    assert N.utm_crs(-122.57, 38.77, "NAD83(2011)") == "EPSG:6339"


def test_the_course_frame_must_be_a_projected_crs_in_metres():
    """The engine reads every coordinate as metres: a State Plane (US survey feet) frame scales the course by 3.28."""
    assert N.check_frame_crs("EPSG:7856") == "EPSG:7856"
    for bad, words in (("EPSG:2227", "metre"), ("EPSG:4326", "projected"), ("EPSG:999999", "EPSG:999999")):
        with pytest.raises(SystemExit, match=words):
            N.check_frame_crs(bad)


def test_the_frame_crs_is_written_as_the_epsg_code_of_a_ground_metre_grid(monkeypatch):
    """The engine reads [frame] crs as EPSG:<code> (the photo request, the feature files' crs names): a CRS name, an
    OGC URN or a PROJ string was accepted, then fetch_data.py imagery stopped with IndexError or ValueError. A compound
    CRS (with heights) and Web Mercator were accepted too: Web Mercator's metres are 1.38 ground metres at 43 N, so
    every distance and yardage came out 38 % long."""
    for given in ("NAD83(CSRS) / UTM zone 17N", "urn:ogc:def:crs:EPSG::2958", "epsg:2958", "EPSG:2958"):
        assert N.check_frame_crs(given) == "EPSG:2958", given
    for bad, words in (("EPSG:2958+6647", r"compound.*--crs EPSG:2958"),
                       ("+proj=tmerc +lon_0=-80 +k=1 +x_0=0 +y_0=0 +ellps=GRS80 +units=m", "no EPSG code"),
                       ("EPSG:3857", "Web Mercator.*UTM"), ("ESRI:102100", "Web Mercator")):
        with pytest.raises(SystemExit, match=words):
            N.check_frame_crs(bad)
    with pytest.raises(SystemExit, match=r"1\.02\d\d of its metres.*400-yard hole.*410"):   # Statistics Canada Lambert
        N.check_frame_crs("EPSG:3347", -80.39, 43.36)
    with pytest.raises(SystemExit, match="Web Mercator"):                                  # whatever the latitude
        N.check_frame_crs("EPSG:3857", 103.8, 1.3)
    assert N.check_frame_crs("EPSG:2958", -80.39, 43.36) == "EPSG:2958"
    assert N.check_frame_crs("EPSG:2959", -80.39, 43.36) == "EPSG:2959"     # the neighbouring UTM zone: 0.2 % long
    assert N.check_frame_crs("EPSG:3310", -122.57, 38.77) == "EPSG:3310"    # California Albers: 0.13 %
    with pytest.raises(SystemExit, match=r"EPSG:2958.*1\.1685 of its metres.*467 yards"):   # Ontario's zone in California
        N.check_frame_crs("EPSG:2958", -122.57, 38.77)
    import pyproj
    class NoFactors:
        meridional_scale = parallel_scale = float("nan")
    monkeypatch.setattr(pyproj.Proj, "get_factors", lambda self, lon, lat: NoFactors())
    with pytest.raises(SystemExit, match="does not reach the course"):
        N.check_frame_crs("EPSG:2958", -80.39, 43.36)


def test_a_refused_frame_crs_says_where_it_came_from_and_by_how_much(tmp_path, monkeypatch, capsys):
    """The refusals told a newcomer to 'leave out --crs' when the CRS came from the region's [scaffold] crs, quoted
    Westmount's 1.38 at 43 N for Web Mercator wherever the course was (1.28 in California), and printed a grid just
    over the 0.5 % limit as '0.5% off' (GDA94 / Geoscience Australia Lambert at Sydney: 0.53 %)."""
    monkeypatch.setattr(N, "ROOT", tmp_path)
    (tmp_path / "regions").mkdir()
    text = (ROOT / "regions/northern_california.toml").read_text()
    assert "\n[scaffold]\n" in text
    (tmp_path / "regions/merc.toml").write_text(text.replace("\n[scaffold]\n", '\n[scaffold]\ncrs = "EPSG:3857"\n'))
    (tmp_path / "regions/northern_california.toml").write_text(text)
    bbox = "--bbox=-122.58,38.76,-122.56,38.78"
    with pytest.raises(SystemExit) as e:
        N.main(["test-club", "Test Club", "--region", "merc", bbox, "--dry-run"])
    msg = str(e.value)
    assert "regions/merc.toml [scaffold] crs" in msg and "leave out --crs" not in msg, msg
    assert "1.28 of its metres at 38.8 N" in msg and "1.38" not in msg, msg
    with pytest.raises(SystemExit) as e:
        N.main(["test-club", "Test Club", "--region", "northern_california", bbox, "--dry-run", "--crs", "EPSG:3857"])
    msg = str(e.value)
    assert "--crs EPSG:3857" in msg and "leave out --crs" in msg and "NAD83(2011)" in msg, msg
    with pytest.raises(SystemExit) as e:
        N.check_frame_crs("EPSG:3112", 151.2, -33.87)
    assert "0.53% off" in str(e.value) and "0.5% at most" in str(e.value), str(e.value)
    with pytest.raises(SystemExit, match="Web Mercator") as e:
        N.check_frame_crs("EPSG:3857")                                            # no latitude: the rule
    assert "1/cos" in str(e.value)


def test_check_course_checks_a_hand_edited_frame_crs():
    """new_course.py refused a CRS name, an OGC URN, a compound CRS, Web Mercator or a grid far off ground metres, but
    a [frame] crs edited by hand (the skeleton says 'check every value') passed check_course without a word, and
    fetch_data.py imagery then stopped with IndexError or ValueError: the engine reads the code after 'EPSG:'."""
    from pyproj import Transformer
    class Frame(Card):
        CORE = FRAME["core"]; TERRAIN = FRAME["terrain"]                # UTM 17N 500000, 4800000: 81.0 W, 43.4 N
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:3347", always_xy=True).transform(-80.39, 43.36)
    lambert = dict(xmin=x - 500, ymin=y - 500, xmax=x + 500, ymax=y + 500)    # Statistics Canada Lambert: 2.6 % long
    for crs, words in (("NAD83(CSRS) / UTM zone 17N", 'write it as "EPSG:2958"'),
                       ("urn:ogc:def:crs:EPSG::2958", 'write it as "EPSG:2958"'), ("epsg:2958", '"EPSG:2958"'),
                       ("EPSG:2958+6647", 'compound.*crs = "EPSG:2958"'), ("EPSG:3857", "Web Mercator"),
                       ("EPSG:2227", "metre"), ("EPSG:4326", "not a projected"), ("EPSG:999999", "not a CRS pyproj knows"),
                       ("EPSG:3347", r"1\.02\d\d of its metres")):
        box = lambert if crs == "EPSG:3347" else FRAME["core"]
        Bad = type("Bad", (Frame,), dict(CRS=crs, CORE=box, TERRAIN=box))
        p = [x for x in K.course_report(Bad) if x.startswith("[frame] crs")]
        assert len(p) == 1 and re.search(words, p[0]) and "course.toml" in p[0], (crs, p)
    assert K.course_report(type("Good", (Frame,), dict(CRS="EPSG:2958"))) == []
    assert not [x for x in K.course_report(C) if x.startswith("[frame] crs")]     # Westmount


# ---- regions (tests/test_robustness.py runs region_spec.problems over every regions/*.toml)
def test_the_region_check_knows_the_engines_classifiers():
    import detect_trees
    assert set(region_spec.CLASSIFIERS) == set(detect_trees.CLASSIFIERS)


def test_the_region_template_is_complete_and_is_not_a_region():
    """A newcomer outside the two regions had no list of the keys a region needs: the template has them all."""
    assert TEMPLATE.exists() and TEMPLATE not in REGIONS
    assert region_spec.problems(tomllib.loads(TEMPLATE.read_text())) == []


def test_gaps_in_a_region_are_named():
    r = region("southern_ontario")
    del r["materials"]; del r["buildings"]["suv_share"]; del r["foliage"]["oak"]; del r["trees"]["shapes"]["pine"]["R"]
    del r["scaffold"]["lidar_leaf_off"]; del r["trees"]["leaf_off_parkland"]["oak_pct"]
    r["trees"]["leaf_off_parkland"]["names"]["broad"] = "elm"
    r["trees"]["needles"]["spruce"] = "fir"
    p = "\n".join(region_spec.problems(r))
    for words in ("[materials]", "[buildings] suv_share", "[foliage.oak]", "[trees.shapes.pine] R",
                  "[scaffold] lidar_leaf_off", "[trees.leaf_off_parkland] oak_pct", "'elm'", "'fir'"):
        assert words in p, words
    r["trees"]["classifier"] = "leaf_off_parklands"
    assert "leaf_off_parklands" in "\n".join(region_spec.problems(r))


def test_check_course_lists_the_gaps_of_the_merged_region():
    class Gaps(Card):
        REGION = {k: v for k, v in Card.REGION.items() if k != "materials"}
    assert any("regions/southern_ontario.toml" in x and "[materials]" in x for x in K.course_report(Gaps))


def test_new_course_names_an_unknown_region_and_an_incomplete_scaffold(tmp_path, monkeypatch):
    with pytest.raises(SystemExit) as e:
        N.load_region("southern_ontaria")
    assert "southern_ontaria" in str(e.value) and "southern_ontario" in str(e.value) and "regions/" in str(e.value)
    monkeypatch.setattr(N, "ROOT", tmp_path)
    (tmp_path / "regions").mkdir()
    (tmp_path / "regions/plains.toml").write_text('[scaffold]\ndatum = "WGS 84"\n')
    with pytest.raises(SystemExit, match="lidar_leaf_off"):
        N.load_region("plains")


def test_the_scaffold_keys_of_a_searched_provider_are_checked(tmp_path, monkeypatch):
    """A new Canadian region written as lidar = { provider = "nrcan_copc" } passed load_region, then new_course.py
    stopped with a KeyError traceback: the NRCan search reads [scaffold] lidar province and backdrop url."""
    sc = region("southern_ontario")["scaffold"]
    assert region_spec.scaffold_problems({"scaffold": sc}) == []
    bare = dict(sc, lidar={"provider": "nrcan_copc"}, backdrop={"provider": "cog_dem"})
    p = "\n".join(region_spec.scaffold_problems({"scaffold": bare}))
    assert "[scaffold] lidar: no province" in p and "[scaffold] backdrop: no url" in p and "nrcan_copc" in p
    typo = dict(sc, backdrop={"provider": "cog_dem", "url": "https://x/{province}-{projet}-1m-dtm.tif"})
    p = "\n".join(region_spec.scaffold_problems({"scaffold": typo}))
    assert "{projet}" in p and "{project}" in p and "{kind}" in p, p
    monkeypatch.setattr(N, "ROOT", tmp_path)
    (tmp_path / "regions").mkdir()
    text = (ROOT / "regions/southern_ontario.toml").read_text()
    (tmp_path / "regions/quebec_test.toml").write_text(text.replace('lidar = { provider = "nrcan_copc", province = "ON" }',
                                                                    'lidar = { provider = "nrcan_copc" }'))
    with pytest.raises(SystemExit, match=r"quebec_test.toml.*\[scaffold\] lidar: no province"):
        N.load_region("quebec_test")


# ---- scaffold sources
def test_a_provider_new_course_cannot_discover_is_copied_from_the_region(monkeypatch):
    """Every region provider but nrcan_copc was rewritten as usgs_3dep (project '?', no DTM, base_h 0): a region with a
    provider of its own got a US skeleton."""
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("no network for a provider without discovery"))
    sc = {"lidar": {"provider": "ign_lidarhd", "dalles": "x"}, "backdrop": {"provider": "cog_dem", "dtm": ["https://y/dtm.tif"]}}
    lidar, backdrop, notes = N.discover_sources(sc, FRAME, (2.0, 48.0, 2.1, 48.1), "EPSG:2154", 31)
    assert lidar == sc["lidar"] and backdrop == sc["backdrop"]
    assert any("ign_lidarhd" in n and "[sources.lidar]" in n for n in notes)


def test_no_lidar_project_found_stops_the_scaffold(monkeypatch):
    monkeypatch.setattr(N, "usgs_projects", lambda bbox: [])
    with pytest.raises(SystemExit, match="3DEP"):
        N.discover_sources({"lidar": {"provider": "usgs_3dep"}, "backdrop": {"provider": "cog_dem"}}, FRAME,
                           (-122.6, 38.7, -122.5, 38.8), "EPSG:6339", 10)
    monkeypatch.setattr(N, "nrcan_projects", lambda core, zone, province: [])
    with pytest.raises(SystemExit, match="ON"):
        N.discover_sources(region("southern_ontario")["scaffold"], FRAME, (-80.5, 43.4, -80.4, 43.5), "EPSG:2958", 17)


def test_the_backdrop_dsm_files_come_from_the_url_pattern_the_region_check_accepts(monkeypatch):
    """The [scaffold] backdrop url check asks for {province}, {project} and {kind}, but the DSM list was the DTM URLs
    with '-1m-dtm.tif' replaced: https://x/{province}/{project}/{kind}.tif passed the check, and [sources.backdrop]
    dsm then repeated the DTM files."""
    monkeypatch.setattr(N, "nrcan_projects", lambda core, zone, province: [{"folder": f"{province}/Proj_A", "suffix": "x"}])
    sc = dict(region("southern_ontario")["scaffold"], lidar={"provider": "nrcan_copc", "province": "QC"},
              backdrop={"provider": "cog_dem", "url": "https://x/{province}/{project}/{kind}.tif"})
    assert region_spec.scaffold_problems({"scaffold": sc}) == []
    _, backdrop, _ = N.discover_sources(sc, FRAME, (-71.3, 46.8, -71.2, 46.9), "EPSG:2949", 19)
    assert backdrop["dtm"] == ["https://x/QC/Proj_A/dtm.tif"] and backdrop["dsm"] == ["https://x/QC/Proj_A/dsm.tif"]
    _, backdrop, _ = N.discover_sources(region("southern_ontario")["scaffold"], FRAME, (-80.5, 43.4, -80.4, 43.5),
                                        "EPSG:2958", 17)
    assert backdrop["dsm"] == [u.replace("-1m-dtm.tif", "-1m-dsm.tif") for u in backdrop["dtm"]]   # Ontario's files
    assert backdrop["dsm"] != backdrop["dtm"]


def test_the_scaffold_runs_end_to_end_with_the_network_stubbed(monkeypatch, capsys):
    """main() wiring: --crs for a grid EPSG does not call UTM, the found sources, the TODOs and the leaf flags."""
    monkeypatch.setattr(N, "osm_holes", lambda bbox: [])
    monkeypatch.setattr(N, "usgs_projects", lambda bbox: [("CA_Test_2020", "2021-01-01")])
    monkeypatch.setattr(N, "usgs_dem", lambda bbox, project: [])
    monkeypatch.setattr(N, "median_ground", lambda urls, crs, ext: None)
    N.main(["test-club", "Test Club", "--region", "northern_california", "--bbox=-122.58,38.76,-122.56,38.78", "--dry-run"])
    t = tomllib.loads(capsys.readouterr().out)
    assert t["frame"]["crs"] == "EPSG:6339" and t["sources"]["lidar"] == {"provider": "usgs_3dep", "project": "CA_Test_2020"}
    assert t["lidar"]["leaf_off"] is False and t["imagery"]["leaf_off"] is False and t["holes"]["playable"] == "1-18"
    N.main(["test-club", "Test Club", "--region", "northern_california", "--bbox=-122.58,38.76,-122.56,38.78", "--dry-run",
            "--crs", "EPSG:3310"])
    out = capsys.readouterr().out
    assert tomllib.loads(out)["frame"]["crs"] == "EPSG:3310" and "TODO" in out


def test_no_ground_height_and_no_hole_lines_are_left_as_todos():
    assert N.median_ground([], "EPSG:2958", FRAME["core"]) is None
    text = skeleton("southern_ontario", ground_known=False, holes=[])
    base = next(l for l in text.splitlines() if l.startswith("base_h"))
    play = next(l for l in text.splitlines() if l.startswith("playable"))
    assert "TODO" in base and "TODO" in play and tomllib.loads(text)["holes"]["playable"] == "1-18"


def test_placeholder_sources_are_reported():
    class Placeholders(Card):
        DATA_SOURCES = {"lidar": {"provider": "usgs_3dep", "project": "?"}, "imagery": {"provider": "arcgis_imageserver"},
                        "backdrop": {"provider": "cog_dem", "dtm": []}}
    p = "\n".join(K.course_report(Placeholders))
    assert "[sources.lidar] project" in p and "[sources.backdrop] dtm" in p


# ---- course.toml checks
def test_osm_par_that_differs_from_the_card_is_reported():
    """With the nines swapped in OSM, hole_data slid each hole's card yardages along another hole's tees."""
    rows = [{"hole": 1, "par": "4"}, {"hole": 2, "par": "4"}, {"hole": 3, "par": None}, {"hole": 4, "par": "4;5"}]
    p = K.par_problems(rows, {1: (4, 400), 2: (3, 150), 3: (5, 500), 4: (4, 380)})
    assert len(p) == 1 and "hole 2" in p[0] and "osm_ref" in p[0]
    from surface_classify import osm_geoms
    assert K.par_problems(K.osm_report(osm_geoms())[0], C.SCORECARD) == []          # Westmount


def test_a_dem_grid_the_engine_cannot_build_is_reported_before_the_downloads(tmp_path):
    """build_rasters stops on a [frame] dem_res other than 0.25 or a core side that is not a whole number of 0.5 m,
    but only at the rasters step, after the downloads and register: check_course said nothing. Both read
    config.grid_problems."""
    class Grid(Card):
        DEM_RES = 0.5; FETCH_CORE = dict(xmin=0.0, ymin=0.0, xmax=512.0, ymax=512.25)
        TEST_CORE = dict(xmin=0.0, ymin=0.0, xmax=100.1, ymax=100.0)
    p = K.course_report(Grid)
    assert any("[frame] dem_res = 0.5" in x and "0.25" in x for x in p), p
    assert any("[frame] core ymin..ymax is 512.25 m" in x and "0.5 m" in x for x in p), p
    assert any("[test_profile] core xmin..xmax is 100.1 m" in x for x in p), p
    class Fine(Grid):
        DEM_RES = 0.25; FETCH_CORE = dict(xmin=0.0, ymin=0.0, xmax=512.0, ymax=511.5); TEST_CORE = None
    assert K.course_report(Fine) == []
    r = load(tmp_path, '[test_profile]\ncore = { xmin = 0.0, ymin = 0.0, xmax = 10.0, ymax = 10.0 }\n',
             code="print(C.TEST_CORE, C.FETCH_CORE == C.CORE)")
    assert r.stdout.split()[-1] == "True" and "'xmax': 10.0" in r.stdout, r.stderr
    assert C.TEST_CORE == dict(xmin=537340.0, ymin=4810720.0, xmax=537980.0, ymax=4811360.0)   # Westmount
    assert not [x for x in K.course_report(C) if "dem_res" in x or "core" in x]


def test_a_tuning_key_or_table_the_engine_does_not_read_is_named(tmp_path):
    """config.tuning() returns the engine default for a name the engine does not ask for, so [tuning] trace_path =
    false (for trace_paths), a [tuning.snad] table or a region's misspelt key left the default in force without a word.
    The names the engine reads are its config.tuning / tuned calls, read from the scripts themselves."""
    keys = K.tuning_keys()
    for k in ("trace_paths", "osm_outline_margin", "pin_slope_limits", "level_tees", "road_half_width", "sand", "native"):
        assert k in keys, k
    assert keys["trace_paths"] is None and keys["road_half_width"] == frozenset() and {"L_min", "b_max"} <= keys["sand"]
    (tmp_path / "x.py").write_text('import config as C\nA = C.tuning("alpha", 1.0)\nB = tuned("beta", dict(x=1.0, y=2.0))\n'
                                   'D = C.tuning("gamma", {"k": 1})\ndef f(name):\n    return C.tuning(name, {})\n')
    assert K.tuning_keys(tmp_path) == {"alpha": None, "beta": frozenset({"x", "y"}), "gamma": frozenset({"k"})}
    class Course(Card):
        SLUG = "test-club"
        TUNING = {"trace_path": False, "snad": {"L_min": 60.0}, "sand": {"Lmin": 60.0, "b_max": 20.0},
                  "road_half_width": {"footway": 1.0}, "zzz_unknown": 1, "osm_outline_margin": 20.0}
        REGION_TUNING = {"forward_tee_fracs": 0.4}
    p = [x for x in K.course_report(Course) if "tuning" in x]
    assert len(p) == 5, p
    assert "[tuning] trace_path" in p[0] and "courses/test-club/course.toml" in p[0] and "did you mean trace_paths" in p[0]
    assert "[tuning.snad]" in p[1] and "table" in p[1] and "did you mean sand" in p[1]
    assert "[tuning.sand] Lmin" in p[2] and "did you mean L_min" in p[2] and "b_max" in p[2]
    assert "[tuning] zzz_unknown" in p[3] and "trace_paths" in p[3]                        # no close name: the list
    assert "regions/southern_ontario.toml" in p[4] and "did you mean forward_tee_frac" in p[4]
    assert not [x for x in K.course_report(C) if "tuning" in x]   # Westmount's own [tuning] keys are all read


def test_a_level_tees_key_is_checked_against_the_parameters_it_is_passed_as(tmp_path):
    """[tuning.level_tees] is passed as level_tees(..., **table), and its empty default made tuning_keys take any key:
    max_slop = 0.02 passed check_course, then the build stopped at the mesh step, after rasters, classify, vectorize
    and trees, with "TypeError: level_tees() got an unexpected keyword argument"; holes or protect, which the call
    passes itself, with "multiple values"."""
    keys = K.tuning_keys()
    assert {"max_slope", "deck_tol", "max_lift", "enabled"} <= keys["level_tees"]
    assert not {"dem", "T", "tees", "holes", "protect"} & keys["level_tees"]
    class Course(Card):
        SLUG = "test-club"; REGION_TUNING = {}
        TUNING = {"level_tees": {"max_slop": 0.02, "holes": [1], "enabled": False}}
    p = [x for x in K.course_report(Course) if "tuning" in x]
    assert len(p) == 2, p
    assert "[tuning.level_tees] max_slop" in p[0] and "did you mean max_slope" in p[0]
    assert "[tuning.level_tees] holes" in p[1] and "max_slope" in p[1]
    (tmp_path / "y.py").write_text(
        "import config as C\n"
        "def f(a, b, c=1, d=2, *, e=3):\n    pass\n"
        "def g(a, **kw):\n    pass\n"
        "f(1, d=4, **C.tuning('eff', {}))\n"     # the keyword parameters the call does not fill itself
        "g(1, **C.tuning('gee', {}))\n"           # **kw takes any key
        "h(**C.tuning('aitch', {}))\n")           # a function defined elsewhere: any key, as before
    assert K.tuning_keys(tmp_path) == {"eff": frozenset({"b", "c", "e"}), "gee": frozenset(), "aitch": frozenset()}


def test_nines_must_cover_the_playable_holes():
    """nines = { Front = "1-9" } on an 18-hole course passed, then hole_data raised KeyError 10."""
    class Front(Card):
        PLAYABLE = tuple(range(1, 19)); NINE = {h: "Front" for h in range(1, 10)}
    assert any("[holes] nines" in x and "10-18" in x for x in K.course_report(Front))


def test_one_stroke_index_for_all_and_unrated_tees_can_be_said(tmp_path):
    """A club with one stroke index row always got a '!!' line no setting could clear."""
    r = load(tmp_path, '[holes]\nplayable = "1-2"\n[stroke_index]\nmen = [2, 1]\nwomen = "same"\n',
             code="print(repr(C.HANDICAP_WOMEN))")
    assert r.stdout.strip() == "{1: 2, 2: 1}", r.stderr
    r = load(tmp_path, '[stroke_index]\nmen = [2, 1]\nwomen = "none"\n', code="print(1)")
    assert r.returncode != 0 and "[stroke_index] women" in r.stderr and "same" in r.stderr and "Traceback" not in r.stderr
    class Unrated(Card):
        RATINGS = {}
    assert any("blue = {}" in x for x in K.course_report(Unrated))


def test_a_unity_class_name_is_a_csharp_identifier(tmp_path):
    """Slug 18-oaks gave 'public class 18OaksSetup', which does not compile in Unity."""
    r = load(tmp_path, slug="18-oaks", code="print(C.UNITY_SCRIPT, C.UNITY_NAME)")
    assert r.stdout.split() == ["Course18OaksSetup.cs", "Course18Oaks"], r.stderr
    class Bad(Card):
        UNITY_SCRIPT = "My-Club.cs"; UNITY_NAME = "My-Club"
    assert any("unity_script" in x and "My-Club" in x for x in K.course_report(Bad))


def test_a_metric_scorecard_is_read_in_yards(tmp_path):
    """A card in metres read as yards put a 400 m hole's marker 34 m forward, and 'measured' still equalled 'card'."""
    r = load(tmp_path, '[scorecard]\nunits = "metres"\n1 = [4, 400, 350]\n2 = [3, 150, 120]\n',
             code="print(repr(C.SCORECARD), C.SCORECARD_UNITS)")
    assert r.stdout.strip() == "{1: (4, 437, 383), 2: (3, 164, 131)} metres", r.stderr
    r = load(tmp_path, '[scorecard]\n1 = [4, 400, 350]\n', code="print(repr(C.SCORECARD), C.SCORECARD_UNITS)")
    assert r.stdout.strip() == "{1: (4, 400, 350)} yards", r.stderr
    r = load(tmp_path, '[scorecard]\nunits = "km"\n1 = [4, 0.4]\n')
    assert r.returncode != 0 and "[scorecard] units" in r.stderr and "metres" in r.stderr and "Traceback" not in r.stderr
    assert C.SCORECARD_UNITS == "yards" and C.SCORECARD[1] == (5, 559, 535, 514, 433)       # Westmount
    assert "units" in skeleton("southern_ontario")


# ---- feature files
def _fc(coords, crs=None):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"golf": "green"}, "geometry": {"type": "Polygon", "coordinates": [coords]}}]}
    if crs:
        fc["crs"] = {"type": "name", "properties": {"name": crs}}
    return fc


def test_feature_files_in_lon_lat_or_another_frame_are_reported(tmp_path):
    """golf.geojson drawn in geojson.io (lon/lat) was read as metres: every feature sat near the UTM origin, and the
    build had no golf labels on the course."""
    class Course(Card):
        SOURCES = tmp_path / "features"; RESEARCH = tmp_path / "research"; CRS = "EPSG:2958"
        TERRAIN = FRAME["terrain"]; COURSE_DIR = tmp_path
    (tmp_path / "features/overrides").mkdir(parents=True); (tmp_path / "research").mkdir()
    sq = lambda x, y: [[x, y], [x + 10, y], [x + 10, y + 10], [x, y]]
    json.dump(_fc(sq(500000.0, 4800000.0)), open(tmp_path / "features/structures.geojson", "w"))
    json.dump(_fc(sq(500000.0, 4800000.0), "urn:ogc:def:crs:EPSG::2958"), open(tmp_path / "features/overrides/h1.geojson", "w"))
    assert K.feature_files_report(Course) == []
    json.dump(_fc([[-80.4, 43.4], [-80.39, 43.4], [-80.39, 43.41], [-80.4, 43.4]]), open(tmp_path / "features/golf.geojson", "w"))
    json.dump(_fc(sq(6000000.0, 2000000.0)), open(tmp_path / "research/layout.geojson", "w"))
    json.dump(_fc(sq(500000.0, 4800000.0), "urn:ogc:def:crs:EPSG::6339"), open(tmp_path / "features/overrides/h2.geojson", "w"))
    p = K.feature_files_report(Course)
    assert len(p) == 3, p
    assert "features/golf.geojson" in p[0] and "lon/lat" in p[0] and "EPSG:2958" in p[0]
    assert "features/overrides/h2.geojson" in p[1] and "6339" in p[1]
    assert "research/layout.geojson" in p[2] and "terrain" in p[2]


def test_a_broken_feature_file_or_one_that_is_not_a_collection_is_named(tmp_path):
    """An unknown geometry type or a one-point line raises shapely's GeometryTypeError / GEOSException, not
    ValueError, and check_course stopped with a traceback. A file holding a single Feature (or a bare geometry) was
    skipped without a word, and assemble_features then stopped with KeyError 'features'. The file is also closed."""
    import warnings
    class Course(Card):
        SOURCES = tmp_path / "features"; RESEARCH = tmp_path / "research"; CRS = "EPSG:2958"
        TERRAIN = FRAME["terrain"]; COURSE_DIR = tmp_path
    (tmp_path / "features/overrides").mkdir(parents=True); (tmp_path / "research").mkdir()
    poly = {"type": "Polygon", "coordinates": [[[500000.0, 4800000.0], [500010.0, 4800000.0], [500010.0, 4800010.0],
                                                [500000.0, 4800000.0]]]}
    feature = lambda g: {"type": "Feature", "properties": {"golf": "green"}, "geometry": g}
    files = {"a_circle": {"type": "FeatureCollection", "features": [feature({"type": "Circle", "coordinates": [1, 2]})]},
             "b_one_point": {"type": "FeatureCollection",
                             "features": [feature({"type": "LineString", "coordinates": [[500000.0, 4800000.0]]})]},
             "c_single_feature": feature(poly), "d_bare_geometry": poly}
    for name, d in files.items():
        json.dump(d, open(tmp_path / f"features/overrides/{name}.geojson", "w"))
    (tmp_path / "features/overrides/e_truncated.geojson").write_text('{"type": "FeatureCollection", "feat')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        p = K.feature_files_report(Course)
    assert len(p) == 5, p
    assert all(f"features/overrides/{n}.geojson" in x for n, x in zip(sorted(files) + ["e_truncated"], p)), p
    assert "circle" in p[0].lower() and "FeatureCollection" in p[2] and "FeatureCollection" in p[3] and "wrap" in p[2]
    assert not [x for x in w if issubclass(x.category, ResourceWarning)]
    # a FeatureCollection without a features list was 'a FeatureCollection, not a FeatureCollection: ... wrap it'
    for f in (tmp_path / "features/overrides").iterdir():
        f.unlink()
    for name, d in (("f_no_features", {"type": "FeatureCollection"}),
                    ("g_features_not_a_list", {"type": "FeatureCollection", "features": {"type": "Feature"}})):
        json.dump(d, open(tmp_path / f"features/overrides/{name}.geojson", "w"))
    p = K.feature_files_report(Course)
    assert len(p) == 2 and all('"features"' in x and "list" in x and "wrap" not in x for x in p), p
    assert "not a FeatureCollection" not in " ".join(p)


def test_westmounts_feature_files_are_in_its_frame():
    assert K.feature_files_report(C) == []


# ---- LiDAR CRS
def _las(path, crs=None, x=(537000.0, 537001.0), y=(4810000.0, 4810001.0)):
    import laspy
    from pyproj import CRS
    h = laspy.LasHeader(point_format=1, version="1.2")
    if crs:
        h.add_crs(CRS(crs))
    las = laspy.LasData(h)
    las.x = np.array(x); las.y = np.array(y); las.z = np.array([300.0, 301.0])
    las.write(path)
    return path


def test_lidar_tiles_in_another_crs_are_named(tmp_path, monkeypatch):
    """3DEP tiles in State Plane feet, or a project in the neighbouring UTM zone, failed as 'no LiDAR tile covers ...',
    which reads as a download gap. They are reprojected as they are read (tests/test_lidar_crs.py), and check_course
    names them with the CRS they come from."""
    monkeypatch.setattr(C, "CRS", "EPSG:2958")
    ok = _las(tmp_path / "ok.las", "EPSG:2958"); bare = _las(tmp_path / "bare.las")
    feet = _las(tmp_path / "feet.las", "EPSG:2227", x=(6000000.0, 6000001.0), y=(2000000.0, 2000001.0))
    assert C.lidar_crs_problems([ok, bare, feet]) == []
    monkeypatch.setattr(C, "LIDAR_TILES", [ok, feet])
    r = K.lidar_crs_report()
    assert any("feet.las" in x and "California zone 3" in x and "reprojected to EPSG:2958" in x for x in r), r


def test_a_photo_in_another_crs_is_named(tmp_path):
    """A photo placed by hand in data/<slug>/imagery in another CRS was read through course-CRS windows: black tiles,
    and the classifier trained on them."""
    import rasterio
    from rasterio.transform import from_origin
    class Course:
        CRS = "EPSG:2958"; IMAGERY_RAW = tmp_path / "photo.tif"
    assert K.photo_crs_report(Course) == []                                    # no photo yet: data_report says so
    for crs, n in (("EPSG:2958", 0), ("EPSG:4326", 1)):
        with rasterio.open(Course.IMAGERY_RAW, "w", driver="GTiff", width=4, height=4, count=1, dtype="uint8", crs=crs,
                           transform=from_origin(500000.0, 4800000.0, 1.0, 1.0)) as d:
            d.write(np.zeros((1, 4, 4), np.uint8))
        p = K.photo_crs_report(Course)
        assert len(p) == n and all(x.startswith("!!") and "WGS 84" in x and "EPSG:2958" in x for x in p), p

