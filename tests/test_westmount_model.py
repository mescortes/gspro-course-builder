"""Regressions of the reference course, Westmount (skipped for any other course): features and numbers checked against
the Golf Canada card, the photo and QA rounds 1 and 2."""
import json, sys
from pathlib import Path

import pytest
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config as C  # noqa: E402

pytestmark = pytest.mark.skipif(C.SLUG != "westmount", reason="Westmount's own regressions")
FULL = C.PROFILE == "course"


@pytest.fixture(scope="module")
def feats():
    return [(shape(f["geometry"]), f["properties"]) for f in json.load(open(C.FEATURES / "course_surfaces.geojson"))["features"]]


@pytest.fixture(scope="module")
def holes():
    return {h["hole"]: h for h in json.load(open(C.OUTPUT / "holes.json"))["holes"]}


def test_hole1_features(feats):
    """Westmount #1 (par 5): a ~675 m2 green ringed by four bunkers, plus two fairway bunkers down the right."""
    h1 = [(g, p) for g, p in feats if p["hole"] == 1]
    green = max((g for g, p in h1 if p["surface"] == "green"), key=lambda g: g.area)
    assert 450 < green.area < 900, f"hole 1 green {green.area:.0f} m2"
    near_bunkers = [g for g, p in h1 if p["surface"] == "bunker" and g.distance(green) < 6]
    assert len(near_bunkers) == 4, f"{len(near_bunkers)} greenside bunkers"
    assert all(50 < b.area < 220 for b in near_bunkers), "bunker polygons should hug the sand"
    assert len([g for g, p in h1 if p["surface"] == "bunker"]) >= 6


def test_water_hazard_on_hole3(holes):
    if not FULL:
        pytest.skip("hole 3 not in the test extent")
    assert any(z["type"] == "water" for z in holes[3]["hazards"]), "the pond right of the 3rd (OSM 918946248) must be a water hazard"


def test_hole1_regression(holes):
    h = holes[1]
    ys = {t["key"]: t["yards"] for t in h["tees"]}
    for k, card in zip(C.TEE_KEYS, C.SCORECARD[1][1:]):
        assert abs(ys[k] - card) <= 4, f"hole 1 {k}: {ys[k]} vs {card}"
    assert -8 < h["elevation_change_m"] < -3, "the 1st tee by the clubhouse sits ~6 m above the green"


def test_scorecard_totals():
    """Golf Canada card: par 73 (37 out / 36 in); each tee's holes add up to its published total; SI permutations."""
    assert sum(v[0] for v in C.SCORECARD.values()) == 73
    assert sum(C.SCORECARD[h][0] for h in range(1, 10)) == 37
    for i, k in enumerate(C.TEE_KEYS):
        assert sum(v[1 + i] for v in C.SCORECARD.values()) == C.RATINGS[k][4], k
    assert [C.RATINGS[k][4] for k in C.TEE_KEYS] == [7018, 6550, 6143, 5432]
    assert sorted(C.HANDICAP.values()) == list(range(1, 19))
    assert sorted(C.HANDICAP_WOMEN.values()) == list(range(1, 19))
