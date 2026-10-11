"""Unit tests for burning QA overrides onto the automatic partition (assemble_features.burn_overrides)."""
import sys
from pathlib import Path

from shapely.geometry import box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import assemble_features as A  # noqa: E402


def _auto():
    """A 10 x 10 m partition: a 6 x 6 m bunker in rough."""
    return [(box(0, 0, 10, 10).difference(box(2, 2, 8, 8)), {"surface": "rough", "hole": 99}),
            (box(2, 2, 8, 8), {"surface": "bunker", "hole": 17})]


def _surf(feats, name):
    return [g for g, p in feats if p["surface"] == name]


def test_override_cut_leaves_no_bunker_slivers():
    """An override that trims a bunker leaves a 0.4 m2 strip: vectorize never emits a bunker part that small (its
    minimum part is 0.25 x MIN_AREA), so the strip joins the override instead of becoming a sub-metre bunker with a
    10 cm lip and a 0 m2 GreenKeeper hazard (holes 5, 8 and 17)."""
    auto = _auto()
    over = [(box(1, 2.4, 9, 9), {"surface": "rough", "hole": 17})]   # leaves the bunker strip y 2..2.4 (6 x 0.4 m)
    out = A.burn_overrides(auto, over)
    assert _surf(out, "bunker") == []
    total = unary_union([g for g, _ in out])
    assert abs(total.area - 100.0) < 1e-6                           # still gap-free
    assert abs(sum(g.area for g, _ in out) - 100.0) < 1e-6          # and overlap-free


def test_override_cut_keeps_real_remnants():
    auto = _auto()
    over = [(box(1, 5, 9, 9), {"surface": "rough", "hole": 17})]     # the south half of the bunker (18 m2) stays
    out = A.burn_overrides(auto, over)
    b = _surf(out, "bunker")
    assert len(b) == 1 and abs(b[0].area - 18.0) < 1e-6
    # rough remnants of any size are kept as they are (rough has no minimum part)
    assert abs(sum(g.area for g in _surf(out, "rough")) - (100.0 - 18.0)) < 1e-6


def test_speck_touching_the_override_at_a_point_joins_its_real_neighbour():
    """A cut remnant that meets the override only at a vertex cannot merge with it: unioned in, it became a detached
    0.07 m2 override part (hole 8, a bunker sliver beside a bunker override). It goes to the neighbour it shares an
    edge with instead."""
    from shapely.geometry import Polygon, MultiPolygon
    tri = Polygon([(5, 5), (5.4, 5.1), (5.1, 5.4)])                    # 0.075 m2, touches the override at (5, 5)
    inner = box(3, 3, 5, 4)
    auto = [(box(0, 0, 10, 10).difference(inner).difference(tri), {"surface": "rough", "hole": 99}),
            (MultiPolygon([inner, tri]), {"surface": "bunker", "hole": 8})]
    over = [(box(0, 0, 5, 5), {"surface": "fairway", "hole": 8})]
    out = A.burn_overrides(auto, over)
    assert _surf(out, "bunker") == []
    assert all(g.area > 1.0 for g in _surf(out, "fairway"))
    assert abs(unary_union([g for g, _ in out]).area - 100.0) < 1e-6
    assert abs(sum(g.area for g, _ in out) - 100.0) < 1e-6
