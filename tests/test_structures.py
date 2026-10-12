"""Unit tests for curated structures (features/structures.geojson) and their roofs (add_structures.roof_mesh)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import box, shape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _flat(z):
    return lambda e, n, order=1: np.full(np.atleast_1d(e).shape, float(z))


def test_hipped_roof_is_a_pyramid_from_the_eaves():
    """A shelter built after the 2018 LiDAR has only trees in the DSM: its roof is synthetic, eaves at height minus
    roof:height and the apex at height (OSM roof tags), not the canopy."""
    from add_structures import roof_mesh
    poly = box(0, 0, 7, 7)
    V2, F, z, ground = roof_mesh(poly, _flat(355.0), _flat(340.0), 4.5,
                                 tags={"roof:shape": "hipped", "roof:height": "2.0"})
    assert ground == 340.0
    edge = np.array([poly.exterior.distance(__import__("shapely").geometry.Point(p)) < 1e-6 for p in V2])
    assert np.allclose(z[edge], 342.5)
    assert z.max() <= 344.5 + 1e-9 and z.max() > 343.8
    assert np.all(z >= 342.5 - 1e-9)


def test_curated_structures_are_valid_buildings():
    path = ROOT / "features/structures.geojson"
    if not path.exists():
        pytest.skip("no curated structures")
    fc = json.load(open(path))
    assert fc["features"]
    for f in fc["features"]:
        g = shape(f["geometry"]); p = f["properties"]
        assert g.geom_type == "Polygon" and g.is_valid and 6 <= g.area < 400, p   # add_buildings skips < 6 m2
        assert "building" in p and float(p["height"]) > 2 and p.get("note")
