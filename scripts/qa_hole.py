"""Standard QA image set for one course hole -> build/qa/holeNN/.

  overview.png        whole hole: imagery + surface outlines (this hole bold, others thin) + tees/pins/aim/centre line
  surfaces.png        whole hole: filled surface map (OPCD colours) blended 60 % over imagery
  hillshade.png       whole hole: LiDAR hillshade + outlines (shows bunker hollows, tee decks, green pads, swales)
  tees.png            close-up of the tee complex (0.1 m/px)
  green.png           close-up of the green complex (0.08 m/px)
  info.json           hole record from output/holes.json + the features assigned to the hole (surface, area, centroid)

Usage: python scripts/qa_hole.py <hole> [<hole> ...]
Coordinates in the images: grid lines every 10 m (close-ups) or 25 m (overviews), labelled with the last 3 digits of
the UTM easting (vertical lines) / northing (horizontal lines), e.g. "582" on a vertical line = E 362582.
"""
import sys, json, math
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import shape, box, Polygon

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C

COL = {"deeprough": (0, 90, 30), "green": (60, 255, 255), "fringe": (120, 220, 200), "fairway": (60, 255, 60), "semirough": (40, 190, 70),
       "rough": (20, 120, 40), "tee": (255, 0, 255), "bunker": (255, 255, 0), "cartpath": (210, 210, 210),
       "native": (255, 140, 0), "road": (90, 90, 90), "building": (255, 50, 50), "court": (60, 90, 255), "water": (0, 80, 255)}
FILL = {"deeprough": (22, 75, 32), "green": (188, 229, 164), "fringe": (150, 200, 130), "fairway": (67, 229, 97), "semirough": (54, 183, 77),
        "rough": (39, 132, 56), "tee": (160, 229, 184), "bunker": (240, 235, 170), "cartpath": (190, 190, 187),
        "native": (190, 117, 29), "road": (85, 85, 85), "building": (200, 60, 60), "court": (51, 85, 170), "water": (0, 0, 192)}
TEE_COL = {"championship": (230, 180, 20), "middle": (40, 80, 230), "forward": (250, 250, 250)}


def read_img(b, res, src=None):
    W = int(round((b[2] - b[0]) / res)); H = int(round((b[3] - b[1]) / res))
    with rasterio.open(src or C.IMAGERY) as ds:
        a = ds.read([1, 2, 3], window=from_bounds(*b, transform=ds.transform), out_shape=(3, H, W),
                    resampling=Resampling.bilinear, boundless=True, fill_value=0)
    return Image.fromarray(np.moveaxis(a, 0, -1))


def hillshade_img(b, res):
    W = int(round((b[2] - b[0]) / res)); H = int(round((b[3] - b[1]) / res))
    with rasterio.open(C.BUILD / "dem_final.tif") as ds:
        z = ds.read(1, window=from_bounds(*b, transform=ds.transform), out_shape=(H, W), resampling=Resampling.bilinear,
                    boundless=True, fill_value=np.nan).astype(np.float64)
    z = np.where(np.isfinite(z), z, np.nanmean(z))
    gy, gx = np.gradient(z, res)
    slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy)
    a, el = math.radians(315), math.radians(35)
    hs = np.clip(np.sin(el) * np.cos(slope) + np.cos(el) * np.sin(slope) * np.cos(a - aspect), 0, 1)
    return Image.fromarray((np.clip((hs - 0.2) / 0.8, 0, 1) * 255).astype(np.uint8)).convert("RGB")


def px(b, res, x, y):
    return ((x - b[0]) / res, (b[3] - y) / res)


def grid(im, b, res, step):
    d = ImageDraw.Draw(im)
    for x in np.arange(math.ceil(b[0] / step) * step, b[2], step):
        p = (x - b[0]) / res
        d.line([(p, 0), (p, im.height)], fill=(255, 0, 0) if x % 100 == 0 else (255, 140, 140), width=1)
        d.text((p + 2, 2), f"{int(x) % 1000}", fill=(255, 255, 0))
    for y in np.arange(math.ceil(b[1] / step) * step, b[3], step):
        p = (b[3] - y) / res
        d.line([(0, p), (im.width, p)], fill=(255, 0, 0) if y % 100 == 0 else (255, 140, 140), width=1)
        d.text((2, p + 2), f"{int(y) % 1000}", fill=(255, 255, 0))


def draw_feats(im, b, res, feats, hn, fill=False):
    d = ImageDraw.Draw(im)
    view = box(*b)
    order = ["rough", "deeprough", "semirough", "native", "fairway", "fringe", "court", "building", "road", "cartpath", "water", "tee", "bunker", "green"]
    for s in order:
        for g, p in feats:
            if p["surface"] != s or not g.intersects(view):
                continue
            for poly in getattr(g, "geoms", [g]):
                pts = [px(b, res, x, y) for x, y in poly.exterior.coords]
                if fill:
                    mask = Image.new("L", im.size, 0); md = ImageDraw.Draw(mask)
                    md.polygon(pts, fill=255)
                    for r in poly.interiors:
                        md.polygon([px(b, res, x, y) for x, y in r.coords], fill=0)
                    im.paste(FILL[s], mask=mask)
                else:
                    w = 3 if p["hole"] == hn else 1
                    d.line(pts, fill=COL[s], width=w)
                    for r in poly.interiors:
                        d.line([px(b, res, x, y) for x, y in r.coords], fill=COL[s], width=w)


def draw_hole(im, b, res, h):
    d = ImageDraw.Draw(im)
    cl = [px(b, res, x, y) for x, y in h["centerline_utm"]]
    d.line(cl, fill=(255, 255, 255), width=2)
    for a in h["aim_points"]:
        x, y = px(b, res, *a["utm"][:2]); d.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(255, 0, 0), width=3)
        d.text((x + 9, y - 6), "aim", fill=(255, 0, 0))
    for t in h["tees"]:
        x, y = px(b, res, *t["utm"][:2]); c = TEE_COL[t["key"]]
        d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=c, outline=(0, 0, 0))
        d.text((x + 8, y - 6), f"{t['key'][0].upper()} {t['yards']:.0f}/{t['scorecard_yards']}", fill=c)
    for p in h["pins"]:
        x, y = px(b, res, *p["utm"][:2])
        d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(255, 0, 0) if p["name"] != "osm" else (160, 0, 255))
        d.text((x + 5, y - 5), p["name"], fill=(255, 255, 255))


def bounds_of(points, margin, min_size=0):
    P = np.asarray(points)
    x0, y0 = P.min(0) - margin; x1, y1 = P.max(0) + margin
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w = max(x1 - x0, min_size); h = max(y1 - y0, min_size)
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def main(hn):
    holes = {h["hole"]: h for h in json.load(open(C.OUTPUT / "holes.json"))["holes"]}
    h = holes[hn]
    feats = [(shape(f["geometry"]), f["properties"]) for f in json.load(open(C.FEATURES / "course_surfaces.geojson"))["features"]]
    out = C.BUILD / "qa" / f"hole{hn:02d}"; out.mkdir(parents=True, exist_ok=True)
    pts = [t["utm"][:2] for t in h["tees"]] + [p[:2] for p in h["centerline_utm"]] + h["green"]["polygon_utm"] + \
          [p["utm_centroid"] for p in h["tee_pads"]]
    b = bounds_of(pts, 35)
    res = max(0.2, max(b[2] - b[0], b[3] - b[1]) / 1800)
    im = read_img(b, res); draw_feats(im, b, res, feats, hn); draw_hole(im, b, res, h); grid(im, b, res, 25)
    im.save(out / "overview.png")
    im = read_img(b, res); fill = im.copy(); draw_feats(fill, b, res, feats, hn, fill=True)
    im = Image.blend(im, fill, 0.6); draw_hole(im, b, res, h); grid(im, b, res, 25); im.save(out / "surfaces.png")
    im = hillshade_img(b, res); draw_feats(im, b, res, feats, hn); draw_hole(im, b, res, h); grid(im, b, res, 25)
    im.save(out / "hillshade.png")
    tb = bounds_of([t["utm"][:2] for t in h["tees"]] + [p["utm_centroid"] for p in h["tee_pads"]], 25, 60)
    im = read_img(tb, 0.1); draw_feats(im, tb, 0.1, feats, hn); draw_hole(im, tb, 0.1, h); grid(im, tb, 0.1, 10)
    im.save(out / "tees.png")
    gb = bounds_of(h["green"]["polygon_utm"], 22, 50)
    im = read_img(gb, 0.08); draw_feats(im, gb, 0.08, feats, hn); draw_hole(im, gb, 0.08, h); grid(im, gb, 0.08, 10)
    im.save(out / "green.png")
    mine = [{"surface": p["surface"], "area_m2": round(g.area, 1), "centroid_utm": [round(g.centroid.x, 1), round(g.centroid.y, 1)]}
            for g, p in feats if p["hole"] == hn]
    near = [{"surface": p["surface"], "hole": p["hole"], "area_m2": round(g.area, 1), "centroid_utm": [round(g.centroid.x, 1), round(g.centroid.y, 1)]}
            for g, p in feats if p["hole"] != hn and p["surface"] in ("green", "tee", "bunker", "fairway", "water")
            and g.intersects(box(*b))]
    json.dump({"hole": h, "features_of_this_hole": mine, "other_holes_features_in_view": near,
               "image_bounds_utm": {"overview": b, "tees": tb, "green": gb}}, open(out / "info.json", "w"), indent=1)
    print("qa images ->", out)


if __name__ == "__main__":
    for a in sys.argv[1:]:
        main(int(a))
