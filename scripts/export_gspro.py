"""GSPro / OPCD hand-off package (output/gspro/) for the terrain square config.TERRAIN.

  heightmap_<N>.raw      Unity terrain heightmap, 16-bit little-endian ("Windows" byte order), N x N (N = 2^k + 1),
                         north row first. Inside the build extent: the course DEM; outside: the 1-2 m backdrop DEM (feathered).
  heightmap_<N>.png      same data as 16-bit greyscale PNG
  terrain.json           size, height range, origin, import settings, Unity <-> UTM transform
  overlay_8192.jpg       satellite overlay for the Inkscape tracing layer (north-up, covers the terrain exactly)
  course_opcd.svg        OPCD-style SVG: mm = metres, layers Hole01..Hole18 (+ any config.SCENERY_HOLES), Hole98 (cart
                         paths), Hole99 (outer rough and non-hole surfaces); OPCD palette fills; shapes stacked bottom ->
                         top as OPCD expects (no holes/donuts)
  trees.csv              tree placements in Unity terrain coordinates (for OPCD Arborist / prefab placement)
  greenkeeper.json       every hole: tees / pins / aim points / hazards in Unity terrain coordinates
  (course_meshes.fbx etc. are written by export_fbx_blender.py)
"""
import sys, json, math
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from shapely.geometry import shape, box, Polygon
from shapely.ops import unary_union
from scipy import ndimage
from PIL import Image

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C

OUT = C.OUTPUT / "gspro"
TE = C.TERRAIN
SIZE = TE["xmax"] - TE["xmin"]
N = 2 ** int(math.ceil(math.log2(SIZE / 0.5))) + 1  # 2048 m -> 4097 (0.5 m spacing)
SINK = 0.05  # m the Unity terrain sits below the course meshes inside the build extent
OPCD = {  # surface -> (OPCD palette name, fill hex, stacking order)
    "rough": ("Rough", "#278438", 0), "deeprough": ("Deep Rough", "#164B20", 1), "native": ("Pinestraw", "#BE751D", 2),
    "semirough": ("Semi Rough", "#36B74D", 3), "fairway": ("Fairway", "#43E561", 4), "fringe": ("Green Fringe", "#A4C88F", 5),
    "tee": ("Tee", "#A0E5B8", 6), "bunker": ("Bunker", "#E5E5AA", 7), "green": ("Green", "#BCE5A4", 8),
    "water": ("Water", "#0000C0", 9), "cartpath": ("Concrete", "#BEBEBB", 10), "road": ("Concrete", "#BEBEBB", 10),
    "court": ("Custom1", "#FCA328", 2), "building": ("Custom2", "#FC28EB", 2),
}


def sample(path, X, Y):
    with rasterio.open(path) as ds:
        z = ds.read(1).astype(np.float64); T = ds.transform
    cols = (X - T.c) / T.a - 0.5; rows = (Y - T.f) / T.e - 0.5
    return ndimage.map_coordinates(np.nan_to_num(z, nan=np.nanmean(z)), [rows, cols], order=1, mode="nearest")


def heightmap():
    # Unity heightmap samples sit on the terrain's corners/edges: x_i = xmin + i * size / (N - 1)
    xs = TE["xmin"] + np.arange(N) * (TE["xmax"] - TE["xmin"]) / (N - 1)
    ys = TE["ymax"] - np.arange(N) * (TE["ymax"] - TE["ymin"]) / (N - 1)  # north row first
    X, Y = np.meshgrid(xs, ys)
    z = sample(C.BUILD / "dem_final.tif", X, Y)
    e = C.CORE
    inside = (X > e["xmin"]) & (X < e["xmax"]) & (Y > e["ymin"]) & (Y < e["ymax"])
    if not inside.all() and (C.DATA / "dem/backdrop_dem.tif").exists():
        zb = sample(C.DATA / "dem/backdrop_dem.tif", X, Y)
        # feather over 25 m inside the build extent so the seam has no step
        d = np.minimum.reduce([X - e["xmin"], e["xmax"] - X, Y - e["ymin"], e["ymax"] - Y])
        w = np.clip(d / 25.0, 0, 1)
        z = w * z + (1 - w) * zb
    # the surface meshes (course_meshes.fbx) cover the whole build extent; sink the Unity terrain 5 cm below them so the
    # two never z-fight (outside the build extent the terrain itself is the visible ground)
    dd = np.minimum.reduce([X - e["xmin"], e["xmax"] - X, Y - e["ymin"], e["ymax"] - Y])
    z = z - SINK * np.clip(dd / 2.0, 0, 1)
    hmin, hmax = float(np.floor(z.min() - 1)), float(np.ceil(z.max() + 1))
    q = np.round((z - hmin) / (hmax - hmin) * 65535).astype("<u2")
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("heightmap_*"):
        old.unlink()
    q.tofile(OUT / f"heightmap_{N}.raw")
    Image.fromarray(q.astype(np.uint16)).save(OUT / f"heightmap_{N}.png")
    meta = {"heightmap": f"heightmap_{N}.raw", "resolution": N, "format": "RAW 16-bit unsigned, little-endian (Unity: Byte Order = Windows)",
            "row_order": "first row = NORTH edge (GIS north-up). In Unity's Import Raw dialog tick 'Flip Vertically' so north stays at +Z.",
            "terrain_size_m": {"width_x": SIZE, "length_z": TE["ymax"] - TE["ymin"], "height_y": hmax - hmin},
            "height_range_m": [hmin, hmax], "sample_spacing_m": SIZE / (N - 1),
            "crs": C.CRS_LABEL,
            "model_origin": [C.ORIGIN_E, C.ORIGIN_N, C.BASE_H],
            "unity_frame": {"x": "easting - %.1f" % TE["xmin"], "z": "northing - %.1f" % TE["ymin"], "y": "height - %.1f" % hmin},
            "utm_extent": TE, "build_extent_utm": C.CORE, "svg_document_mm": [SIZE, TE["ymax"] - TE["ymin"]],
            "overlay": "overlay_8192.jpg",
            "terrain_sunk_below_meshes_m": SINK}
    json.dump(meta, open(OUT / "terrain.json", "w"), indent=1)
    return hmin, hmax


OUTER_SINK = 2.0   # m: the outer plot sits this far below the inner terrain inside the inner square (inner always wins)


def outer_extent():
    """OPCD 'Plot (Outer)': a second Unity terrain twice the inner size, centred on it, for the mountain background."""
    cx, cy = (TE["xmin"] + TE["xmax"]) / 2, (TE["ymin"] + TE["ymax"]) / 2
    return dict(xmin=cx - SIZE, ymin=cy - SIZE, xmax=cx + SIZE, ymax=cy + SIZE)


def outer_terrain(n=4097, px=8192):
    """Outer plot heightmap (16-bit RAW, 4097^2 over 2x the inner size) + 8192 px overlay, as in the OPCD outer-plot
    recipe (research/GSPRO_COSMETICS.md). Inside the inner square it is sunk OUTER_SINK m (feathered over 10 m)."""
    oe = outer_extent()
    xs = oe["xmin"] + np.arange(n) * (oe["xmax"] - oe["xmin"]) / (n - 1)
    ys = oe["ymax"] - np.arange(n) * (oe["ymax"] - oe["ymin"]) / (n - 1)
    X, Y = np.meshgrid(xs, ys)
    z = sample(C.DATA / "dem/backdrop_dem.tif", X, Y)
    d_in = np.minimum.reduce([X - TE["xmin"], TE["xmax"] - X, Y - TE["ymin"], TE["ymax"] - Y])
    z = z - OUTER_SINK * np.clip(d_in / 10.0, 0, 1)
    hmin, hmax = float(np.floor(z.min() - 1)), float(np.ceil(z.max() + 1))
    q = np.round((z - hmin) / (hmax - hmin) * 65535).astype("<u2")
    q.tofile(OUT / f"outer_heightmap_{n}.raw")
    Image.fromarray(q.astype(np.uint16)).save(OUT / f"outer_heightmap_{n}.png")
    out = np.zeros((px, px, 3), np.uint8)
    from build_backdrop import NEAR_IMG, FAR_IMG, summer_tif
    # the summer-graded backdrop photos (build_backdrop.summer_grade) where built; finer sources on top
    for src in (*(summer_tif(p) if summer_tif(p).exists() else p.with_suffix(".tif") for p in (FAR_IMG, NEAR_IMG)), C.IMAGERY):
        if not src.exists():
            continue
        with rasterio.open(src) as ds:
            a = ds.read([1, 2, 3], window=from_bounds(oe["xmin"], oe["ymin"], oe["xmax"], oe["ymax"], transform=ds.transform),
                        out_shape=(3, px, px), resampling=Resampling.lanczos, boundless=True, fill_value=0)
        paint(out, np.moveaxis(a, 0, -1))
    Image.fromarray(out).save(OUT / f"outer_overlay_{px}.jpg", quality=90)
    return {"heightmap": f"outer_heightmap_{n}.raw", "resolution": n, "overlay": f"outer_overlay_{px}.jpg",
            "terrain_size_m": {"width_x": oe["xmax"] - oe["xmin"], "length_z": oe["ymax"] - oe["ymin"], "height_y": hmax - hmin},
            "height_range_m": [hmin, hmax], "utm_extent": oe, "sunk_inside_inner_m": OUTER_SINK,
            "unity_position": {"x": oe["xmin"] - TE["xmin"], "z": oe["ymin"] - TE["ymin"], "y": hmin},
            "note": "OPCD 'Plot (Outer)': import like the inner terrain (16-bit, Windows byte order, Flip Vertically) and place "
                    "it at unity_position relative to the inner terrain's origin (y relative to the inner terrain's height base)."}


def unity(e_, n_, h_, hmin):
    return [round(e_ - TE["xmin"], 3), round(h_ - hmin, 3), round(n_ - TE["ymin"], 3)]


def paint(out, a, feather_px=48):
    """Paint a finer image layer over `out`, feathering its edge so tone differences between sources don't show as
    rectangles."""
    m = a.max(-1) > 0
    if not m.any():
        return
    w = np.clip(ndimage.distance_transform_edt(m) / feather_px, 0, 1)[..., None]
    have = (out.max(-1) > 0)[..., None]
    w = np.where(have, w, m[..., None].astype(float))
    out[:] = np.clip(out * (1 - w) + a * w + 0.5, 0, 255).astype(np.uint8)


def overlay(px=8192):
    out = np.zeros((px, px, 3), np.uint8)
    from build_backdrop import NEAR_IMG
    for src in (NEAR_IMG.with_suffix(".tif"), C.IMAGERY):  # later sources paint over earlier ones
        if not src.exists():
            continue
        with rasterio.open(src) as ds:
            a = ds.read([1, 2, 3], window=from_bounds(TE["xmin"], TE["ymin"], TE["xmax"], TE["ymax"], transform=ds.transform),
                        out_shape=(3, px, px), resampling=Resampling.lanczos, boundless=True, fill_value=0)
        paint(out, np.moveaxis(a, 0, -1))
    for old in OUT.glob("overlay_*.jpg"):
        old.unlink()
    Image.fromarray(out).save(OUT / "overlay_8192.jpg", quality=88)


def svg():
    Wm, Hm = SIZE, TE["ymax"] - TE["ymin"]
    feats = [(shape(f["geometry"]), f["properties"]) for f in json.load(open(C.FEATURES / "course_surfaces.geojson"))["features"]]
    def pathd(poly):
        c = np.asarray(poly.exterior.coords)
        pts = [f"{x - TE['xmin']:.3f},{TE['ymax'] - y:.3f}" for x, y in c[:-1]]
        return "M " + " L ".join(pts) + " Z"
    # stacked, hole-free shapes: each surface becomes its filled outline (interiors are covered by the shapes on top)
    layers = {}
    for g, p in feats:
        s = p["surface"]
        if s not in OPCD or s == "rough":
            continue  # rough = the Hole99 outer shape covering the whole terrain
        hole = int(p.get("hole", 99))
        for poly in getattr(g, "geoms", [g]):
            if poly.area < 0.5:
                continue
            layers.setdefault(hole, []).append((OPCD[s][2], s, Polygon(poly.exterior).simplify(0.08)))
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" '
           f'width="{Wm}mm" height="{Hm}mm" viewBox="0 0 {Wm} {Hm}">',
           '<g inkscape:groupmode="layer" inkscape:label="image" id="layer_image" sodipodi:insensitive="true">',
           f'<image x="0" y="0" width="{Wm}" height="{Hm}" xlink:href="overlay_8192.jpg" preserveAspectRatio="none"/></g>',
           '<g inkscape:groupmode="layer" inkscape:label="Hole99" id="Hole99">',
           f'<path id="Hole99_Rough_outer" d="M 0,0 L {Wm},0 L {Wm},{Hm} L 0,{Hm} Z" style="fill:{OPCD["rough"][1]};stroke:none"/>']
    for k, (order, s, poly) in enumerate(sorted(layers.get(99, []), key=lambda t: t[0])):
        out.append(f'<path id="Hole99_{OPCD[s][0].replace(" ", "")}_{k}" d="{pathd(poly)}" style="fill:{OPCD[s][1]};stroke:none"/>')
    out.append("</g>")
    for hole in sorted(h for h in layers if h not in (98, 99)):
        label = f"Hole{hole:02d}"
        out.append(f'<g inkscape:groupmode="layer" inkscape:label="{label}" id="{label}">')
        for k, (order, s, poly) in enumerate(sorted(layers[hole], key=lambda t: t[0])):
            out.append(f'<path id="{label}_{OPCD[s][0].replace(" ", "")}_{k}" d="{pathd(poly)}" style="fill:{OPCD[s][1]};stroke:none"/>')
        out.append("</g>")
    out.append('<g inkscape:groupmode="layer" inkscape:label="Hole98" id="Hole98">')
    for k, (order, s, poly) in enumerate(layers.get(98, [])):
        out.append(f'<path id="Hole98_Concrete_{k}" d="{pathd(poly)}" style="fill:{OPCD["cartpath"][1]};stroke:none"/>')
    out.append("</g></svg>")
    (OUT / "course_opcd.svg").write_text("\n".join(out))
    return sum(len(v) for v in layers.values())


def grass_spec_json():
    import grass_spec
    grass_spec.write_spec(OUT / "grass_3dg.json")


def trees_csv(hmin):
    trees = json.load(open(C.FEATURES / "trees.geojson"))["features"]
    E = np.array([t["geometry"]["coordinates"][0] for t in trees]); Nn = np.array([t["geometry"]["coordinates"][1] for t in trees])
    H = sample(C.BUILD / "dem_final.tif", E, Nn) if len(trees) else []
    from add_vegetation import instance_params
    # prefab = tree_prefabs.fbx object; yaw/scale exactly as in the glTF (glTF yaw theta about +Y = Unity -theta)
    rows = ["id,archetype,prefab,unity_x,unity_y,unity_z,yaw_deg,scale_xz,scale_y,height_m,crown_radius_m,crown_base_m,utm_e,utm_n"]
    for t, x, y, h, (var, yaw, sxz, sy, _, _) in zip(trees, E, Nn, H, instance_params(trees)):
        p = t["properties"]; u = unity(x, y, h - 0.05, hmin)
        rows.append(f"{p['id']},{p['archetype']},Tree_{p['archetype']}_v{var},{u[0]},{u[1]},{u[2]},{(-math.degrees(yaw)) % 360:.1f},"
                    f"{sxz:.4f},{sy:.4f},{p['height']},{p['crown_r']},{p['crown_base']},{x:.2f},{y:.2f}")
    (OUT / "trees.csv").write_text("\n".join(rows))
    return len(trees)


GKD_TEE_SLOT = dict(C.TEE_GKD)   # GKD TeeType per card tee (course.toml [[tees]] gkd_slot)


def unity_script(short=None, name=None, last_hole=None):
    """The Unity editor helper for this course, from unity/Editor/CourseSetup.cs.in: class <name>Setup, menu and
    Assets/<name>, course meshes Hole01 .. Hole<last_hole>."""
    t = (C.ROOT / "unity/Editor/CourseSetup.cs.in").read_bytes().decode()
    return (t.replace("{{SHORT}}", short or C.COURSE_SHORT).replace("{{NAME}}", name or C.UNITY_NAME)
             .replace("{{LAST_HOLE}}", str(last_hole or max(C.PLAYABLE))))

GKD_PIN_DAYS = (("Thursday", "middle"), ("Friday", "front"), ("Saturday", "back"))   # Sunday: the harder side pin


def heights(X, Y):
    """Terrain height at UTM points: the course DEM inside the build extent, the backdrop DEM outside."""
    X = np.asarray(X, float); Y = np.asarray(Y, float)
    z = sample(C.DATA / "dem/backdrop_dem.tif", X, Y) if (C.DATA / "dem/backdrop_dem.tif").exists() else np.zeros(len(X))
    e = C.CORE
    inside = (X > e["xmin"]) & (X < e["xmax"]) & (Y > e["ymin"]) & (Y < e["ymax"])
    if inside.any():
        z[inside] = sample(C.BUILD / "dem_final.tif", X[inside], Y[inside])
    return z


def ring3d(coords, hmin, step=6.0):
    """[[x, y, z], ...] Unity coordinates along a UTM ring, resampled every `step` m, y on the ground."""
    from shapely.geometry import LineString
    line = LineString(coords).segmentize(step)
    P = np.asarray(line.coords)
    H = heights(P[:, 0], P[:, 1])
    return [unity(x, y, h, hmin) for (x, y), h in zip(P, H)]


def gkd_hole(h, hmin):
    """GreenKeeper (GKD) view of one hole record: tee slots + computed distances, 4 day pins, aim points, hazards."""
    import math
    gc = h["green"]["centre_utm"][:2]
    aims = [a["utm"][:2] for a in h["aim_points"]]
    def gk_dist(p):
        d0 = math.dist(p, gc)
        pts = [p] + [a for a in aims if math.dist(a, gc) < d0] + [gc]
        return sum(math.dist(a, b) for a, b in zip(pts[:-1], pts[1:]))
    tees = [{"tee_type": GKD_TEE_SLOT.get(t["key"], t["name"]), "card_tee": t["name"], "position": unity(*t["utm"], hmin),
             "distance_m": round(gk_dist(t["utm"][:2]), 2), "yards": t["yards"]} for t in h["tees"]]
    pins = {p["name"]: p for p in h["pins"]}
    bunkers = [np.asarray(z["polygon_utm"]) for z in h["hazards"] if z["type"] == "bunker"]
    def bunker_gap(p):
        if not bunkers:
            return 1e9
        q = np.asarray(p["utm"][:2])
        return min(np.min(np.hypot(*(b - q).T)) for b in bunkers)
    side = min((pins[k] for k in ("left", "right") if k in pins), key=bunker_gap)
    day_pins = [{"day": d, "name": k, "position": unity(*pins[k]["utm"], hmin)} for d, k in GKD_PIN_DAYS if k in pins]
    day_pins.append({"day": "Sunday", "name": side["name"], "position": unity(*side["utm"], hmin)})
    hazards = [{"type": z["type"], "coords": ring3d(z["polygon_utm"], hmin)} for z in h["hazards"] if z["type"] != "bunker"]
    return {"tees": tees, "pins": day_pins, "aim_points": [unity(*a["utm"], hmin) for a in h["aim_points"]][:2],
            "green_center": unity(*h["green"]["centre_utm"], hmin), "hazards": hazards,
            "bunkers": [{"coords": ring3d(z["polygon_utm"], hmin, 2.0)} for z in h["hazards"] if z["type"] == "bunker"]}


def greenkeeper(hmin):
    """greenkeeper.json: per hole tees / pins / aim points / hazards in Unity terrain coordinates, plus a 'gkd' view in
    GreenKeeper's own vocabulary (tee slots, rating/slope strings, Thursday-Sunday pins, pOOB ring, 3D hazard rings)
    to type into GreenKeeper (it has no documented import)."""
    data = json.load(open(C.OUTPUT / "holes.json"))
    def u(p):
        return unity(p[0], p[1], p[2], hmin)
    holes = []
    for h in data["holes"]:
        if not h.get("tees"):
            continue
        holes.append({"hole": h["hole"], "nine": h["nine"], "par": h["par"], "handicap": h.get("handicap"),
                      "tees": [{"name": t["name"], "position": u(t["utm"]), "heading_deg_from_north": t["heading_deg"],
                                "yards": t["yards"], "scorecard_yards": t["scorecard_yards"]} for t in h["tees"]],
                      "pins": [{"name": p["name"], "position": u(p["utm"])} for p in h["pins"] if p["name"] != "osm"],
                      "aim_points": [{"name": a["name"], "position": u(a["utm"])} for a in h["aim_points"]],
                      "green_center": u(h["green"]["centre_utm"]),
                      "hazards": [{"type": z["type"], "polygon": [[round(x - TE["xmin"], 2), round(y - TE["ymin"], 2)] for x, y in z["polygon_utm"]]}
                                  for z in h["hazards"]],
                      "gkd": gkd_hole(h, hmin)})
    from surface_classify import osm_geoms
    course = max((g for _, t, g in osm_geoms() if t.get("leisure") == "golf_course" and g.geom_type == "Polygon"),
                 key=lambda g: g.area, default=None)
    sr = {}
    for k, slot in GKD_TEE_SLOT.items():
        r = C.RATINGS.get(k)
        if r:
            sr[f"{slot}SR"] = f"{r[0]:.1f}/{r[1]}"
            if r[2] is not None:
                sr[f"{slot}SR_women"] = f"{r[2]:.1f}/{r[3]}"
    gk = {"course": C.COURSE_NAME, "layout": C.LAYOUT, "frame": "Unity terrain (x east, y up, z north) metres",
          "tee_sets": [{"key": k, "name": n, "colour": c} for k, n, c in C.TEES],
          "ratings": {k: dict(zip(("men_rating", "men_slope", "women_rating", "women_slope", "total_yards"), v)) for k, v in C.RATINGS.items()},
          "gkd": {"note": "GreenKeeper (GKD) vocabulary: TeeType slot per card tee, one 'rating/slope' string per slot (GKD holds "
                          "one value per slot: pick men's or women's), pOOB = the OSM property line on the ground (our OB "
                          "line), hazards = water / native rings with ground heights. Distances follow GreenKeeper's rule.",
                  "tee_slots": GKD_TEE_SLOT, "ratings": sr, "par": sum(h["par"] for h in holes),
                  "pOOB": {"coords": ring3d(list(course.exterior.coords), hmin) if course is not None else []}},
          "terrain": "see terrain.json", "holes": holes}
    json.dump(gk, open(OUT / "greenkeeper.json", "w"), indent=1)
    for old in OUT.glob("hole01_greenkeeper.json"):
        old.unlink()
    return len(holes)


def main():
    hmin, hmax = heightmap()
    overlay()
    n = svg()
    nt = trees_csv(hmin)
    grass_spec_json()
    # Unity editor helpers (terrains, trees, water probes, 3DG) travel with the package
    (OUT / "unity/Editor").mkdir(parents=True, exist_ok=True)
    for old in (OUT / "unity/Editor").glob("*.cs"):
        old.unlink()
    (OUT / "unity/Editor" / C.UNITY_SCRIPT).write_bytes(unity_script().encode())
    meta = json.load(open(OUT / "terrain.json"))
    meta["outer"] = outer_terrain()
    meta["outer"]["unity_position"]["y"] = round(meta["outer"]["unity_position"]["y"] - hmin, 3)
    json.dump(meta, open(OUT / "terrain.json", "w"), indent=1)
    nh = greenkeeper(hmin)
    print(f"gspro package: heightmap {N}^2 over {SIZE:.0f} m ({hmin}..{hmax} m), svg shapes {n}, trees {nt}, holes {nh}")


if __name__ == "__main__":
    main()
