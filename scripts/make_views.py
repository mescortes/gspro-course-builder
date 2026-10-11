"""Camera presets for the viewer (model frame), derived from hole 1 in output/holes.json + the DEM -> viewer/views.json.

The viewer also builds per-hole cameras from holes.json at runtime; these are the named presets (#tee, #green, ...)."""
import sys, json
from pathlib import Path
import numpy as np, rasterio
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).parent)); import config as C
from surface_classify import osm_geoms

with rasterio.open(C.BUILD / 'dem_final.tif') as _ds:
    _Z = _ds.read(1); _T = _ds.transform


def h_at(e, n):
    r, c = rasterio.transform.rowcol(_T, e, n)
    r = min(max(r, 0), _Z.shape[0] - 1); c = min(max(c, 0), _Z.shape[1] - 1)
    return float(_Z[r, c])


def m(p, dz=0.0):
    e, n = float(p[0]), float(p[1])
    return [round(e - C.ORIGIN_E, 2), round(h_at(e, n) - C.BASE_H + dz, 2), round(-(n - C.ORIGIN_N), 2)]


def unit(v):
    v = np.asarray(v, float); return v / max(np.linalg.norm(v), 1e-9)


def main():
    holes = {h["hole"]: h for h in json.load(open(C.OUTPUT / "holes.json"))["holes"]}
    h = holes[min(holes)]
    tee = np.asarray(h["tees"][0]["utm"][:2])
    cl = np.asarray(h["centerline_utm"], float)
    green = np.asarray(h["green"]["centre_utm"][:2])
    pin = np.asarray(next(p for p in h["pins"] if p["name"] == "middle")["utm"][:2])
    d1 = unit(cl[1] - cl[0])                      # first leg
    da = unit(green - cl[-2])                     # approach direction
    side = np.array([-da[1], da[0]])              # player's left on the approach
    first_leg = np.linalg.norm(cl[1] - cl[0])
    fairway_pt = cl[0] + d1 * min(230.0, 0.8 * first_leg) if len(cl) > 2 else cl[0] + d1 * 0.6 * first_leg
    bunkers = [np.asarray(z["utm_centroid"]) for z in h["hazards"] if z["type"] == "bunker"]
    gb = min(bunkers, key=lambda b: np.linalg.norm(b - green)) if bunkers else green - da * 15 + side * 10
    blds = [g for _, t, g in osm_geoms() if "building" in t and g.geom_type == "Polygon" and g.distance(Point(tee)) < 400]
    house = max(blds, key=lambda g: g.area) if blds else None
    club = np.asarray(house.centroid.coords[0]) if house is not None else tee + np.array([40.0, -40.0])
    # clubhouse camera: 40 m outside the footprint toward the 1st tee, stepped out until it is clear of every building
    reach = max(Point(club).distance(Point(c)) for c in house.exterior.coords) if house is not None else 30.0
    club_cam = club + unit(tee - club) * (reach + 40.0)
    while any(g.buffer(3.0).contains(Point(club_cam)) for g in blds):
        club_cam = club_cam + unit(tee - club) * 10.0
    mid = 0.5 * (tee + green)
    views = {
        "tee":          {"pos": m(tee, 1.75), "target": m(tee + d1 * 150), "fov": 50},
        "tee_wide":     {"pos": m(tee - d1 * 12, 6.0), "target": m(tee + d1 * 200), "fov": 60},
        "fairway":      {"pos": m(fairway_pt, 1.75), "target": m(green, 0.5), "fov": 45},
        "approach":     {"pos": m(green - da * 50, 1.75), "target": m(green), "fov": 45},
        "green":        {"pos": m(green - da * 18, 1.7), "target": m(pin), "fov": 50},
        "behind_green": {"pos": m(green + da * 30, 6.0), "target": m(tee), "fov": 55},
        "flag":         {"pos": m(pin - da * 7, 1.6), "target": m(pin, 1.0), "fov": 45},
        "clubhouse":    {"pos": m(club_cam, 4.0), "target": m(club, 4.0), "fov": 55},
        "putt":         {"pos": m(pin - da * 3, 1.2), "target": m(pin), "fov": 55},
        "rough_lie":    {"pos": m(mid + side * 30, 1.5), "target": m(green), "fov": 60},
        "bunker_lie":   {"pos": m(gb, 1.5), "target": m(pin, 0.5), "fov": 60},
        "overview":     {"pos": m(tee - d1 * 150, 160.0), "target": m(mid), "fov": 45},
        "top":          {"pos": m([C.ORIGIN_E, C.ORIGIN_N], 420.0), "target": m([C.ORIGIN_E, C.ORIGIN_N + 1]), "fov": 45},
    }
    json.dump(views, open(C.ROOT / 'viewer/views.json', 'w'), indent=1)
    print(json.dumps(views, indent=1))


if __name__ == "__main__":
    main()
