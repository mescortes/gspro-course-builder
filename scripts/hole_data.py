"""Hole metadata for every playable hole: tee boxes and markers, yardages, green geometry, pins, aim points, hazards.

Writes output/holes.json ({"holes": [...]}, config.CRS + model-frame coordinates) and output/hole01.json (hole 1, kept
for compatibility). This is what GSPro's GreenKeeper needs (tees, pins, aim/shot points, hazards) and it also drives
the tests, maps, viewer camera presets and tee-marker / flagstick placement.

Line of play: the OSM `golf=hole` line (tee -> doglegs -> green). Its interior vertices are the aim points; for
hole 1 the aim point was hand-checked against the fairway. Tee markers: each scorecard tee is assigned the tee pad
whose playing distance is closest, then slid along a line of play across the pad (the one nearest its centre line that reaches the yardage)
so the measured yardage matches the card (that is how real markers are set), clamped to stay 1.5 m inside the pad.
"""
import sys, json, math
import numpy as np
import rasterio
from shapely.geometry import shape, Point, LineString, Polygon
from shapely.ops import unary_union
from scipy import ndimage

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C

YD = 1 / 0.9144
TEE_KEYS = C.TEE_KEYS        # back -> front, the order of the yardages in config.SCORECARD
TEE_NAMES = C.TEE_NAMES
# hand-checked aim points (course hole -> list of UTM points); default = interior vertices of the OSM line of play.
# Per-hole QA overrides live in courses/<slug>/features/overrides/holeNN_meta.json:
#   {"aim_points_utm": [[e, n], ...], "tees_utm": {"<tee key>": [e, n], ...}, "notes": "..."}
AIM_OVERRIDES = {}


def hole_meta(h):
    p = C.SOURCES / "overrides" / f"hole{h:02d}_meta.json"
    return json.load(open(p)) if p.exists() else {}
HANDICAP = {}  # filled from config.HANDICAP when available


class Terrain:
    def __init__(self):
        self.ds = rasterio.open(C.BUILD / "dem_final.tif"); self.z = self.ds.read(1); self.T = self.ds.transform

    def h(self, e, n):
        c = (e - self.T.c) / self.T.a - 0.5; r = (n - self.T.f) / self.T.e - 0.5
        return float(ndimage.map_coordinates(self.z, [[r], [c]], order=1)[0])


def model(e, n, h):
    return [round(e - C.ORIGIN_E, 3), round(h - C.BASE_H, 3), round(-(n - C.ORIGIN_N), 3)]


def load_features(feats_path=None):
    return [(shape(f["geometry"]), f["properties"]) for f in json.load(open(feats_path or (C.FEATURES / "course_surfaces.geojson")))["features"]]


def hole_lines():
    from surface_classify import osm_geoms
    return {C.course_hole(t["ref"]): g for _, t, g in osm_geoms()
            if t.get("golf") == "hole" and t.get("ref") and g.geom_type == "LineString"}


FAIRWAY_MARKER_GAP = 6.0  # yd: a pad that misses the card by more than this is not that tee's box


def point_at_distance(d_m, aims, green_c, back_tee):
    """Point on the first leg of the line of play (back tee -> first aim / green) whose play distance is d_m."""
    first = np.asarray(aims[0]) if len(aims) else np.asarray(green_c)
    rest = play_distance(first, aims[1:], green_c) if len(aims) else 0.0
    need = d_m - rest
    leg = np.asarray(back_tee) - first; L = np.linalg.norm(leg)
    if need <= 0 or L < 1e-6 or need > L + 1.0:
        return None
    return first + leg / L * need


def play_distance(p, aims, green_c):
    """Horizontal play distance tee -> aim points -> green centre, as GreenKeeper computes it: aim points that are not
    nearer the green than the tee (a forward tee past the dogleg) are skipped (research/GSPRO_COSMETICS.md 5)."""
    d0 = math.dist(tuple(p)[:2], tuple(green_c)[:2])
    pts = [tuple(p)[:2]] + [tuple(a)[:2] for a in aims if math.dist(tuple(a)[:2], tuple(green_c)[:2]) < d0] + [tuple(green_c)[:2]]
    return sum(math.dist(a, b) for a, b in zip(pts[:-1], pts[1:]))


def pad_axes(pad, toward, step=1.5):
    """Candidate marker lines across the pad: segments parallel to the direction from the pad to `toward`, every `step` m
    across it, clipped to the pad inset by 1.5 m. Returns [(back, front, offset)], offset = metres from the centroid's
    line. Every line is a candidate because a composite / L-shaped tee complex has its centroid outside the pad (QA
    round 1), so the line through it alone can miss the arm that carries the card yardage."""
    c = np.asarray(pad.centroid.coords[0]); d = np.asarray(toward, float) - c; d /= np.linalg.norm(d)
    n = np.array([-d[1], d[0]])
    inner = pad.buffer(-1.5)
    if inner.is_empty:
        inner = pad.buffer(-0.5) if not pad.buffer(-0.5).is_empty else pad
    ext = np.asarray(inner.exterior.coords if inner.geom_type == "Polygon" else
                     [q for g in inner.geoms for q in g.exterior.coords]) - c
    across = ext @ n
    out = []
    for off in np.arange(np.floor(across.min() / step) * step, across.max() + 1e-9, step):
        seg = LineString([c + n * off - d * 80, c + n * off + d * 80]).intersection(inner)
        for piece in getattr(seg, "geoms", [seg]):
            if piece.is_empty or piece.geom_type != "LineString":
                continue
            a, b = np.asarray(piece.coords[0]), np.asarray(piece.coords[-1])
            if np.dot(b - a, d) < 0:
                a, b = b, a
            out.append((a, b, float(off)))
    if not out:
        p = np.asarray(inner.representative_point().coords[0])
        out.append((p, p, 0.0))
    return out  # back of pad, front, offset


def place_tees(pads, aims, green_c, card):
    """Assign card tees to pads and slide markers to match the card yardage. Returns list of tee dicts."""
    first = aims[0] if aims else green_c
    info = []
    for pad in pads:
        axes = [dict(back=a, front=b, off=off, dist_back=play_distance(a, aims, green_c) * YD,
                     dist_front=play_distance(b, aims, green_c) * YD) for a, b, off in pad_axes(pad, first)]
        info.append(dict(pad=pad, axes=axes, dist_c=play_distance(pad.centroid.coords[0], aims, green_c) * YD))

    def err(ax, yards):
        lo, hi = sorted((ax["dist_front"], ax["dist_back"]))
        return 0.0 if lo <= yards <= hi else min(abs(yards - lo), abs(yards - hi))

    tees = []
    for key, yards in zip(TEE_KEYS, card):
        if not info:
            break
        # distance error if the marker is placed anywhere on this pad
        best = min(info, key=lambda i: (min(err(ax, yards) for ax in i["axes"]), abs(i["dist_c"] - yards)))
        ax = min(best["axes"], key=lambda ax: (round(err(ax, yards), 3), abs(ax["off"])))   # nearest the centre line
        lo, hi = ax["dist_front"], ax["dist_back"]
        t = 0.5 if abs(hi - lo) < 1e-6 else float(np.clip((yards - lo) / (hi - lo), 0, 1))
        pos = ax["front"] + (ax["back"] - ax["front"]) * t
        measured = play_distance(pos, aims, green_c) * YD
        tees.append(dict(key=key, pad=best["pad"], pos=pos, measured=measured, card=yards, pad_err=err(ax, yards)))
    return tees


def hole_green(greens, snap=0.3):
    """The putting surface: the largest green polygon plus the pieces that touch it (within `snap` m). QA overrides that
    fill a notch are separate polygons (QA round 2, holes 8, 14 and 18); a green elsewhere is not part of this one."""
    main = max(greens, key=lambda g: g.area)
    parts = [g for g in greens if g is main or g.distance(main) <= snap]
    if len(parts) == 1:
        return main
    u = unary_union([g.buffer(snap / 2 + 0.01, join_style=2) for g in parts]).buffer(-(snap / 2 + 0.01), join_style=2)
    return max(getattr(u, "geoms", [u]), key=lambda g: g.area)


def green_analysis(green, terr, res=0.25):
    """Slope map on the putting surface and candidate pin locations (>= 3 m from the edge, slope <= 3 %, relaxed on
    steep greens: pin_candidates)."""
    import shapely
    minx, miny, maxx, maxy = green.bounds
    xs = np.arange(minx, maxx, res) + res / 2; ys = np.arange(miny, maxy, res) + res / 2
    X, Y = np.meshgrid(xs, ys)
    inside = shapely.contains_xy(green, X, Y)
    c = (X - terr.T.c) / terr.T.a - 0.5; r = (Y - terr.T.f) / terr.T.e - 0.5
    Z = ndimage.map_coordinates(terr.z, [r, c], order=1)
    gy, gx = np.gradient(Z, res)
    slope = np.hypot(gx, gy) * 100
    edge = ndimage.distance_transform_edt(inside) * res
    ok, limit = pin_candidates(inside, edge, slope)
    return X, Y, Z, slope, inside, edge, ok, limit


def nine_hole(h, nine):
    """Hole number within its nine (1-9), from config.NINE."""
    return [x for x in sorted(nine) if nine[x] == nine[h]].index(h) + 1


PIN_LIMITS = C.tuning("pin_slope_limits", (3.0, 3.5, 4.0, 4.5, 5.0))   # % slope, tried in turn
PIN_MIN_FRAC = C.tuning("pin_min_frac", 0.12)


def pin_candidates(inside, edge, slope, limits=PIN_LIMITS, min_frac=PIN_MIN_FRAC):
    """Cells >= 3 m from the edge with slope <= the first limit (in %) that leaves at least `min_frac` of the green
    pinnable. Steep Thompson greens (Westmount 14: 3.7 % at <= 3 %) would otherwise put all five pins in one spot."""
    for limit in limits:
        ok = inside & (edge >= 3.0) & (slope <= limit)
        if ok.sum() >= min_frac * max(inside.sum(), 1):
            break
    return ok, limit


def hole_record(h, line, feats, terr, all_feats):
    par, *card = C.SCORECARD[h]
    hf = [(g, p) for g, p in feats if p["hole"] == h]
    greens = [g for g, p in hf if p["surface"] == "green"]
    if not greens:
        return {"hole": h, "error": "no green polygon assigned"}
    green = hole_green(greens)
    gc = np.asarray(green.centroid.coords[0])
    coords = np.asarray(line.coords)
    meta = hole_meta(h)
    aims = [np.asarray(a, float) for a in meta.get("aim_points_utm", AIM_OVERRIDES.get(h, coords[1:-1].tolist()))]
    if par == 3:
        aims = []
    pads = [g for g, p in hf if p["surface"] == "tee" and g.area > 15]
    tees = place_tees(pads, aims, gc, card)
    # No tee pad can deliver the card yardage (composite forward tees): put the marker on the line of play at exactly the
    # card distance, as forward markers on a fairway are. QA overrides below still win.
    for t in tees:
        t["source"] = "pad"
        if t["pad_err"] > FAIRWAY_MARKER_GAP and t["key"] != TEE_KEYS[0]:
            pos = point_at_distance(t["card"] / YD, aims, gc, np.asarray(tees[0]["pos"]))
            if pos is not None:
                t["pos"] = pos; t["measured"] = play_distance(pos, aims, gc) * YD; t["source"] = "fairway_marker"
    for t in tees:  # QA-pinned marker positions (e.g. a forward tee that sits in the fairway)
        fixed = meta.get("tees_utm", {}).get(t["key"])
        if fixed:
            t["pos"] = np.asarray(fixed, float)
            t["measured"] = play_distance(t["pos"], aims, gc) * YD
            t["pad_err"] = 0.0
            t["source"] = "qa_override"
            near = [pd for pd in pads if pd.distance(Point(fixed)) < 3]
            if near:
                t["pad"] = near[0]
    rec = {"hole": h, "nine": C.NINE[h], "nine_hole": nine_hole(h, C.NINE), "par": par, "handicap": C.HANDICAP.get(h),
           "qa_notes": meta.get("notes", ""),
           "scorecard_yards": dict(zip(TEE_KEYS, card)), "tees": [], "pins": [], "aim_points": [], "hazards": [], "tee_pads": []}
    for pad in pads:
        c = pad.centroid
        rec["tee_pads"].append({"utm_centroid": [round(c.x, 2), round(c.y, 2)], "area_m2": round(pad.area, 1),
                                "polygon_utm": [[round(x, 2), round(y, 2)] for x, y in pad.exterior.coords]})
    first = aims[0] if aims else gc
    for t in tees:
        e, n = t["pos"]; hh = terr.h(e, n)
        az = math.degrees(math.atan2(first[0] - e, first[1] - n)) % 360
        rec["tees"].append({"key": t["key"], "name": TEE_NAMES[t["key"]], "utm": [round(e, 2), round(n, 2), round(hh, 2)],
                            "model": model(e, n, hh), "yards": round(t["measured"], 1), "scorecard_yards": t["card"],
                            "pad_error_yd": round(t["pad_err"], 1), "heading_deg": round(az, 1),
                            "source": t["source"],
                            "pad_centroid_utm": [round(t["pad"].centroid.x, 2), round(t["pad"].centroid.y, 2)]})
    # green geometry along the line of approach
    approach_from = aims[-1] if aims else (np.asarray(tees[0]["pos"]) if tees else coords[0])
    v = gc - approach_from; v /= np.linalg.norm(v)
    perp = np.array([-v[1], v[0]])  # points to the player's left
    def chord(direction):
        seg = LineString([gc - direction * 80, gc + direction * 80]).intersection(green)
        return max(getattr(seg, "geoms", [seg]), key=lambda s: s.length) if not seg.is_empty else None
    seg = chord(v)
    front, back = Point(seg.coords[0]), Point(seg.coords[-1])
    if Point(approach_from).distance(front) > Point(approach_from).distance(back):
        front, back = back, front
    width = chord(perp).length if chord(perp) is not None else 0.0
    X, Y, Z, slope, inside, edge, ok, pin_limit = green_analysis(green, terr)
    gh = terr.h(*gc)
    rec["green"] = {"centre_utm": [round(gc[0], 2), round(gc[1], 2), round(gh, 2)], "centre_model": model(gc[0], gc[1], gh),
                    "front_utm": [round(front.x, 2), round(front.y, 2)], "back_utm": [round(back.x, 2), round(back.y, 2)],
                    "depth_yd": round(seg.length * YD, 1), "width_yd": round(width * YD, 1),
                    "area_m2": round(green.area, 1), "area_sqft": round(green.area * 10.7639),
                    "slope_pct": {"mean": round(float(slope[inside].mean()), 2), "p95": round(float(np.percentile(slope[inside], 95)), 2),
                                  "max": round(float(slope[inside].max()), 2)},
                    "pinnable_fraction": round(float(ok.sum() / max(inside.sum(), 1)), 3),
                    "pin_slope_limit_pct": pin_limit,
                    "polygon_utm": [[round(x, 2), round(y, 2)] for x, y in green.exterior.coords]}
    along = (X - gc[0]) * v[0] + (Y - gc[1]) * v[1]; across = (X - gc[0]) * perp[0] + (Y - gc[1]) * perp[1]
    cand = np.flatnonzero(ok.ravel())
    if len(cand) < 5:
        cand = np.flatnonzero((inside & (edge >= 2.0)).ravel())
    if len(cand) == 0:
        cand = np.flatnonzero(inside.ravel())
    A, Bc, S = along.ravel()[cand], across.ravel()[cand], slope.ravel()[cand]
    chosen = []
    def pick(score, min_sep=4.0):
        """best-scoring candidate at least min_sep m from the pins already chosen (relaxed if the green is tiny)"""
        order = np.argsort(score)
        xs, ys = X.ravel()[cand[order]], Y.ravel()[cand[order]]
        for sep in (min_sep, min_sep / 2, 0.0):
            for x, y in zip(xs, ys):
                if all(math.hypot(x - a, y - b) >= sep for a, b in chosen):
                    chosen.append((float(x), float(y)))
                    return float(x), float(y)
        return float(xs[0]), float(ys[0])
    picks = {}
    picks["middle"] = pick(np.abs(A) + np.abs(Bc) + 0.5 * S)
    picks["front"] = pick(A + 0.3 * S)
    picks["back"] = pick(-A + 0.3 * S)
    picks["left"] = pick(-Bc + 0.3 * S)
    picks["right"] = pick(Bc + 0.3 * S)
    for name, (x, y) in picks.items():
        rec["pins"].append({"name": name, "utm": [round(x, 2), round(y, 2), round(terr.h(x, y), 2)], "model": model(x, y, terr.h(x, y)),
                            "from_front_yd": round(((x - front.x) * v[0] + (y - front.y) * v[1]) * YD, 1)})
    for a in aims:
        ah = terr.h(*a)
        rec["aim_points"].append({"name": "dogleg", "utm": [round(float(a[0]), 2), round(float(a[1]), 2), round(ah, 2)],
                                  "model": model(a[0], a[1], ah),
                                  "from_back_tee_yd": round(math.dist(tees[0]["pos"], a) * YD, 1) if tees else None})
    play = LineString([tuple(tees[0]["pos"]) if tees else tuple(coords[0])] + [tuple(a) for a in aims] + [tuple(gc)])
    rec["centerline_utm"] = [[round(x, 2), round(y, 2)] for x, y in play.coords]
    for g, p in hf:
        if p["surface"] == "bunker":
            c = g.centroid
            rec["hazards"].append({"type": "bunker", "utm_centroid": [round(c.x, 2), round(c.y, 2)], "area_m2": round(g.area, 1),
                                   "polygon_utm": [[round(x, 2), round(y, 2)] for x, y in g.exterior.coords]})
    corridor = play.buffer(40)
    for g, p in all_feats:
        if p["surface"] in ("native", "water") and g.area > 50 and g.intersects(corridor):
            c = g.centroid
            rec["hazards"].append({"type": "native_area" if p["surface"] == "native" else "water", "utm_centroid": [round(c.x, 2), round(c.y, 2)],
                                   "area_m2": round(g.area, 1), "polygon_utm": [[round(x, 2), round(y, 2)] for x, y in g.exterior.coords]})
    if rec["tees"]:
        rec["elevation_change_m"] = round(gh - rec["tees"][0]["utm"][2], 2)
    return rec


def main():
    feats = load_features()
    terr = Terrain()
    lines = hole_lines()
    holes = []
    for h in C.PLAYABLE:
        if h not in lines:
            holes.append({"hole": h, "error": "no OSM line of play"}); continue
        rec = hole_record(h, lines[h], feats, terr, feats)
        holes.append(rec)
        if "tees" in rec and rec["tees"]:
            print(f"hole {h:2d} ({rec['nine']} {rec['nine_hole']}) par {rec['par']}: " +
                  "  ".join(f"{C.TEE_LABEL[t['key']]} {t['yards']:.0f}/{t['scorecard_yards']}" + (f" (pad off {t['pad_error_yd']:.0f})" if t['pad_error_yd'] > 3 else "")
                            for t in rec["tees"]) + f"  green {rec['green']['area_sqft']} sqft", flush=True)
        else:
            print(f"hole {h}: {rec.get('error', 'no tees')}")
    out = {"course": C.COURSE_NAME, "layout": C.LAYOUT, "crs": C.CRS, "tee_sets": [{"key": k, "name": n} for k, n, _ in C.TEES],
           "model_frame": {"origin_utm": [C.ORIGIN_E, C.ORIGIN_N], "base_height": C.BASE_H, "axes": "x=east, y=up, z=south (metres)"},
           "holes": holes}
    C.OUTPUT.mkdir(exist_ok=True)
    json.dump(out, open(C.OUTPUT / "holes.json", "w"), indent=1)
    h1 = next((x for x in holes if "tees" in x), None)   # the first playable hole
    if h1:
        json.dump(dict(h1, course=out["course"], crs=C.CRS, model_frame=out["model_frame"]),
                  open(C.OUTPUT / f"hole{h1['hole']:02d}.json", "w"), indent=1)
    return out


if __name__ == "__main__":
    main()
