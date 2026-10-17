"""make_maps.py: the yardage-book hole maps and the course map (synthetic surfaces and DEM)."""
import sys
from pathlib import Path

import numpy as np
from matplotlib import colors
from matplotlib.image import imread
from rasterio.transform import from_origin
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config as C  # noqa: E402
import make_maps  # noqa: E402


def _share(png, surface, alpha):
    """Share of the image's pixels showing `surface`'s fill under the flat DEM's hillshade (grey, `alpha`)."""
    img = imread(png)[..., :3]
    flat = make_maps.hillshade(np.full((8, 8), 300.0), 1.0)[4, 4]
    want = (1 - alpha) * np.asarray(colors.to_rgb(make_maps.FILL[surface])) + alpha * flat
    return float(np.all(np.abs(img - want) < 0.02, axis=-1).mean())


def _surfaces(cx, cy, half, inner):
    """A rough polygon over the square of side 2 * half round (cx, cy) with a hole of side 2 * inner, and the fairway
    that fills the hole listed before it (course_surfaces lists the rough after what lies in its holes: Whistle Bear's
    853,337 m2 rough, 263 holes, is feature 758 of 937)."""
    hole = box(cx - inner, cy - inner, cx + inner, cy + inner)
    rough = box(cx - half, cy - half, cx + half, cy + half).difference(hole)
    assert len(rough.interiors) == 1
    return [(hole, {"surface": "fairway", "hole": 1}), (rough, {"surface": "rough", "hole": 99})]


def _dem(e):
    """A flat DEM over the build extent `e` (5 m cells)."""
    T = from_origin(e["xmin"], e["ymax"], 5.0, 5.0)
    return np.full((int((e["ymax"] - e["ymin"]) / 5), int((e["xmax"] - e["xmin"]) / 5)), 300.0), T


def test_course_map_draws_the_surfaces_inside_a_polygons_holes(tmp_path):
    """Every map showed only rough, paths and trees: each polygon was filled to its exterior, so a rough polygon with
    holes painted over the fairways, greens, bunkers and water in them."""
    e = C.CORE
    cx, cy = (e["xmin"] + e["xmax"]) / 2, (e["ymin"] + e["ymax"]) / 2
    side = min(e["xmax"] - e["xmin"], e["ymax"] - e["ymin"]) / 2
    dem, T = _dem(e)
    out = tmp_path / "course_map.png"
    make_maps.course_map({"holes": []}, _surfaces(cx, cy, side, side / 2), dem, T, out)
    assert _share(out, "fairway", 0.3) > 0.08
    assert _share(out, "rough", 0.3) > 0.2


def test_hole_map_draws_the_surfaces_inside_a_polygons_holes(tmp_path):
    e = C.CORE
    cx, cy = (e["xmin"] + e["xmax"]) / 2, (e["ymin"] + e["ymax"]) / 2
    tee, green = [cx, cy - 150.0], [cx, cy + 150.0]
    hole = {"hole": 1, "par": 4, "hazards": [], "pins": [], "elevation_change_m": 0.0,
            "scorecard_yards": {k: 360 for k in C.TEE_KEYS},
            "tees": [{"key": C.TEE_KEYS[0], "utm": tee + [300.0], "yards": 360.0}],
            "centerline_utm": [tee, [cx, cy], green],
            "green": {"polygon_utm": [[cx - 15, cy + 135], [cx + 15, cy + 135], [cx + 15, cy + 165], [cx - 15, cy + 165]],
                      "centre_utm": green + [300.0], "depth_yd": 33.0, "width_yd": 33.0, "area_sqft": 9688}}
    dem, T = _dem(e)
    out = tmp_path / "hole01_map.png"
    make_maps.hole_map(hole, _surfaces(cx, cy, 400.0, 100.0), dem, T, out, trees=[])
    assert _share(out, "fairway", 0.35) > 0.08
    assert _share(out, "rough", 0.35) > 0.2
