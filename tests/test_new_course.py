"""new_course.py: the course.toml skeleton for a new course (frame, extents, CRS) - offline parts."""
import json, sys, tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import new_course as N  # noqa: E402


def _westmount_outline():
    from pyproj import Transformer
    d = json.load(open(ROOT / "courses/westmount/research/osm_golf.json"))
    e = next(e for e in d["elements"] if e.get("tags", {}).get("leisure") == "golf_course")
    tr = Transformer.from_crs("EPSG:4326", "EPSG:2958", always_xy=True)
    return [tr.transform(g["lon"], g["lat"]) for g in e["geometry"]]


def test_rescaffolding_westmount_reproduces_its_frame_and_extents():
    """Plan PR 5: CORE = the outline + 100 m, rounded up to whole 256 m tiles and centred on it; TERRAIN = a 2048 m
    square centred on CORE; ORIGIN = the CORE centre floored to 50 m; BASE_H = the median ground rounded to 5 m."""
    f = N.frame(_westmount_outline(), median_ground=345.22)
    w = tomllib.load(open(ROOT / "courses/westmount/course.toml", "rb"))["frame"]
    assert f["core"] == w["core"] and f["terrain"] == w["terrain"]
    assert f["origin"] == w["origin"] and f["base_h"] == w["base_h"]


def test_the_crs_is_the_regions_datum_in_the_courses_utm_zone():
    assert N.utm_crs(-80.39, 43.36, "NAD83(CSRS)") == "EPSG:2958"      # Whistle Bear
    assert N.utm_crs(-122.57, 38.77, "NAD83(2011)") == "EPSG:6339"     # Brambles
    assert N.utm_crs(-75.7, 45.4, "NAD83(CSRS)") == "EPSG:2959"        # Ottawa: zone 18


def test_a_small_course_still_gets_whole_tiles_and_the_terrain_square():
    f = N.frame([(500000.0, 5000000.0), (500300.0, 5000000.0), (500300.0, 5000200.0), (500000.0, 5000200.0)], 250.0)
    c, t = f["core"], f["terrain"]
    assert (c["xmax"] - c["xmin"]) % 256 == 0 and (c["ymax"] - c["ymin"]) % 256 == 0
    assert c["xmin"] <= 500000.0 - 100 and c["xmax"] >= 500300.0 + 100
    assert t["xmax"] - t["xmin"] == 2048.0 and t["xmin"] <= c["xmin"] and t["xmax"] >= c["xmax"]


def test_the_skeleton_is_a_loadable_course_file(tmp_path):
    region = tomllib.load(open(ROOT / "regions/southern_ontario.toml", "rb"))
    text = N.course_toml("Test Golf Club", "southern_ontario", region, "EPSG:2958",
                         N.frame(_westmount_outline(), 345.2), holes=list(range(1, 19)),
                         lidar={"provider": "nrcan_copc", "zone": 17, "projects": [{"folder": "ON/Lake_Erie_2018", "suffix": "2018LLAKEERIE"}]},
                         backdrop={"provider": "cog_dem", "dtm": ["https://x/ON-Lake_Erie_2018-1m-dtm.tif"]},
                         outline=["way/39971102"], notes=["OSM: 18 hole lines"])
    t = tomllib.loads(text)
    assert t["course"]["name"] == "Test Golf Club" and t["course"]["region"] == "southern_ontario"
    assert t["frame"]["crs"] == "EPSG:2958" and t["holes"]["playable"] == "1-18" and t["osm"]["outline"] == ["way/39971102"]
    assert t["sources"]["lidar"]["projects"][0]["suffix"] == "2018LLAKEERIE"
    assert t["sources"]["imagery"]["provider"] == "arcgis_imageserver" and t["imagery"]["res"] == region["scaffold"]["imagery_res"]
    assert "OSM: 18 hole lines" in text


def test_the_scaffold_runs_when_several_courses_exist(tmp_path):
    """new_course.py writes a course before COURSE can name it: it must not load a course itself (the second scaffold
    in a repo stopped at 'set COURSE')."""
    import os, shutil, subprocess
    shutil.copytree(ROOT / "scripts", tmp_path / "scripts")
    for c in ("alpha", "bravo"):
        (tmp_path / "courses" / c).mkdir(parents=True)
        (tmp_path / "courses" / c / "course.toml").write_text('[course]\nname = "x"\n')
    env = {k: v for k, v in os.environ.items() if k not in ("COURSE", "MG_PROFILE")}
    r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); import new_course; "
                        "from sources import nrcan_copc, usgs_3dep; print('ok')"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert r.stdout.strip() == "ok", r.stderr
