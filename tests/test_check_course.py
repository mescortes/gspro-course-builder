"""check_course.py: OSM coverage per hole and gaps in course.toml (offline: Westmount's committed OSM snapshot)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_course as K  # noqa: E402
import config as C  # noqa: E402


def test_westmount_osm_covers_every_hole():
    from surface_classify import osm_geoms
    rows, problems = K.osm_report(osm_geoms())
    assert [r["hole"] for r in rows] == list(range(1, 19))
    assert all(r["line"] and r["green"] and r["tee"] for r in rows), [r for r in rows if not (r["line"] and r["green"] and r["tee"])]
    assert sum(r["bunkers"] for r in rows) > 40 and not [p for p in problems if "duplicate" in p]


def test_westmount_course_file_is_complete():
    assert K.course_report(C) == []


class _Card:
    PLAYABLE = tuple(range(1, 19)); TEES = (("blue", "Blue", "#00f"), ("red", "Red", "#f00"))
    TEE_KEYS = ("blue", "red"); TEE_GKD = {"blue": "Blue"}
    SCORECARD = {h: (4, 400) for h in range(1, 18)}          # hole 18 missing, one yardage per hole for two tees
    HANDICAP = dict(zip(range(1, 19), [1] * 18)); HANDICAP_WOMEN = {}
    RATINGS = {"blue": (72.0, 130, None, None, 7000)}
    REGION_NAME = None; DATA_SOURCES = {"lidar": {}}; OSM_OUTLINE = ()


def test_gaps_in_a_course_file_are_listed():
    p = "\n".join(K.course_report(_Card))
    for words in ("hole 18", "yardages", "stroke index", "women", "rating", "red", "gkd_slot", "region", "imagery", "backdrop"):
        assert words in p, words


def test_duplicate_hole_refs_are_reported():
    from shapely.geometry import LineString, Polygon
    G = [(1, {"golf": "hole", "ref": "1"}, LineString([(0, 0), (300, 0)])),
         (2, {"golf": "hole", "ref": "1"}, LineString([(0, 900), (300, 900)])),
         (3, {"golf": "green"}, Polygon([(290, -10), (310, -10), (310, 10), (290, 10)]))]
    rows, problems = K.osm_report(G, playable=(1, 2))
    assert rows[0]["line"] and rows[0]["green"] and not rows[1]["line"]
    assert any("duplicate" in p and "1" in p for p in problems) and any("hole 2" in p for p in problems)
    G += [(4, {"leisure": "golf_course"}, Polygon([(-50, -50), (400, -50), (400, 50), (-50, 50)])),
          (5, {"leisure": "golf_course"}, Polygon([(-50, 850), (400, 850), (400, 950), (-50, 950)]))]
    assert any("[osm] outline" in p for p in K.osm_report(G, playable=(1, 2))[1])
