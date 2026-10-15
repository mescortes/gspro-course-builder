"""Starting a course somewhere new: new_course.py, check_course.py, the course and region loaders, and the LiDAR /
photo CRS checks. Each test is a newcomer's failure that was silent or a bare traceback (synthetic data, no network)."""
import json, os, shutil, subprocess, sys, tomllib
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


def test_each_region_says_which_leaf_state_its_data_and_classifier_have():
    for p in REGIONS:
        r = tomllib.load(open(p, "rb"))
        tr = r["trees"]
        prm = tr[tr["classifier"]]
        assert isinstance(prm.get("lidar_leaf_off"), bool), p.stem
        assert r["scaffold"]["lidar_leaf_off"] == prm["lidar_leaf_off"], p.stem
        if "imagery_leaf_off" in prm:
            assert r["scaffold"]["imagery_leaf_off"] == prm["imagery_leaf_off"], p.stem


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


def test_the_frame_crs_is_written_as_the_epsg_code_of_a_ground_metre_grid():
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


# ---- regions
@pytest.mark.parametrize("path", REGIONS, ids=[p.stem for p in REGIONS])
def test_every_region_has_every_key_the_engine_reads(path):
    assert region_spec.problems(tomllib.load(open(path, "rb"))) == []


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
    which reads as a download gap."""
    monkeypatch.setattr(C, "CRS", "EPSG:2958")
    ok = _las(tmp_path / "ok.las", "EPSG:2958"); bare = _las(tmp_path / "bare.las")
    feet = _las(tmp_path / "feet.las", "EPSG:2227", x=(6000000.0, 6000001.0), y=(2000000.0, 2000001.0))
    assert C.lidar_crs_problems([ok, bare]) == []
    p = C.lidar_crs_problems([ok, feet])
    assert len(p) == 1 and "feet.las" in p[0] and "California zone 3" in p[0] and "EPSG:2958" in p[0] and "[frame] crs" in p[0]
    import build_rasters as R
    monkeypatch.setattr(R.C, "LIDAR_TILES", [ok, feet])
    with pytest.raises(SystemExit, match="feet.las"):
        R.pass1(dict(xmin=537000.0, ymin=4810000.0, xmax=537256.0, ymax=4810256.0), 1.0)
    monkeypatch.setattr(C, "LIDAR_TILES", [ok, feet])
    assert any(x.startswith("!!") and "feet.las" in x for x in K.lidar_crs_report())


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

