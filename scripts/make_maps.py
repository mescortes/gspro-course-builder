"""Yardage-book style hole maps + green maps (PNG) for every hole, and a whole-course map."""
import sys, json, math
import numpy as np
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MPoly
from shapely.geometry import shape, Point, LineString, Polygon
from scipy import ndimage

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C

FILL = {"deeprough": "#1f5a28", "green": "#7ccf6a", "fringe": "#6dbb5c", "fairway": "#58b84a", "semirough": "#3f9a3a", "rough": "#2f7d32",
        "tee": "#7fd38a", "bunker": "#efe6c4", "cartpath": "#c9c9c4", "native": "#a8743a", "road": "#7a7a7a",
        "building": "#b9b2a6", "court": "#4b6fa8", "water": "#3a6fc4"}
YD = 1 / 0.9144


def hillshade(z, res, az=315, alt=40):
    gy, gx = np.gradient(z, res)
    slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy)
    a, b = np.radians(az), np.radians(alt)
    return np.clip(np.sin(b) * np.cos(slope) + np.cos(b) * np.sin(slope) * np.cos(a - aspect), 0, 1)


def hole_bounds(hole, margin=45.0):
    pts = np.array([t["utm"][:2] for t in hole["tees"]] + [p[:2] for p in hole["centerline_utm"]] + hole["green"]["polygon_utm"])
    x0, y0 = pts.min(0) - margin; x1, y1 = pts.max(0) + margin
    # pad to a 9:10 portrait aspect around the centre
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2; w, h = x1 - x0, y1 - y0
    if w / h > 0.9:
        h = w / 0.9
    else:
        w = h * 0.9
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def hole_map(hole, feats, dem, T, out, trees=None):
    b = hole_bounds(hole)
    fig, ax = plt.subplots(figsize=(9, 10), dpi=150)
    c0 = max(0, int((b[0] - T.c) / T.a)); c1 = min(dem.shape[1], int((b[2] - T.c) / T.a))
    r0 = max(0, int((b[3] - T.f) / T.e)); r1 = min(dem.shape[0], int((b[1] - T.f) / T.e))
    hs = hillshade(dem[r0:r1, c0:c1], T.a)
    hs_ext = (T.c + c0 * T.a, T.c + c1 * T.a, T.f + r1 * T.e, T.f + r0 * T.e)
    for g, p in feats:
        if not g.intersects(LineString([(b[0], b[1]), (b[2], b[3])]).envelope):
            continue
        for poly in getattr(g, "geoms", [g]):
            ax.add_patch(MPoly(np.asarray(poly.exterior.coords), closed=True, fc=FILL.get(p["surface"], "#888"), ec="none", zorder=1))
            for hole_ring in poly.interiors:
                ax.add_patch(MPoly(np.asarray(hole_ring.coords), closed=True, fc="none", ec="none"))
    ax.imshow(hs, extent=hs_ext, cmap="gray", alpha=0.35, zorder=2, vmin=0, vmax=1)
    # trees
    for t in (trees if trees is not None else json.load(open(C.FEATURES / "trees.geojson"))["features"]):
        x, y = t["geometry"]["coordinates"]
        if b[0] < x < b[2] and b[1] < y < b[3] and t["properties"]["height"] > 4:
            ax.add_patch(plt.Circle((x, y), t["properties"]["crown_r"], fc="#1d4d22", ec="#123316", alpha=0.85, zorder=3, lw=0.4))
    # line of play + distances
    cl = np.asarray(hole["centerline_utm"])
    ax.plot(cl[:, 0], cl[:, 1], color="white", lw=1.2, ls="--", zorder=4)
    tee = np.asarray(next(t for t in hole["tees"] if t["key"] == C.TEE_KEYS[0])["utm"][:2])
    gc = np.asarray(hole["green"]["centre_utm"][:2])
    cols = C.TEE_COLOURS
    for t in hole["tees"]:
        ax.plot(*t["utm"][:2], "o", ms=7, mfc=cols[t["key"]], mec="black", zorder=6)
        ax.annotate(f"{t['yards']:.0f}", t["utm"][:2], xytext=(6, -12), textcoords="offset points", fontsize=8, color="black",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.8), zorder=7)
    # distance arcs from the back tee, centred on the first leg of the line of play
    first = np.asarray(cl[1]); ang0 = math.atan2(first[1] - tee[1], first[0] - tee[0])
    for yd in ((150, 200, 250) if hole["par"] > 3 else (100, 150)):
        r = yd / YD
        th = np.linspace(ang0 - math.radians(40), ang0 + math.radians(40), 200)
        ax.plot(tee[0] + r * np.cos(th), tee[1] + r * np.sin(th), color="white", lw=0.6, alpha=0.7, zorder=4)
        ax.text(tee[0] + r * math.cos(ang0 + 0.5), tee[1] + r * math.sin(ang0 + 0.5), f"{yd}", color="white",
                fontsize=7, zorder=5, ha="center")
    # hazard distances from the back tee (front / carry)
    for hz in hole["hazards"]:
        poly = np.asarray(hz["polygon_utm"])
        d = np.hypot(*(poly - tee).T) * YD
        c = poly.mean(0)
        ax.annotate(f"{d.min():.0f}/{d.max():.0f}", c, fontsize=7, color="black", ha="center", zorder=7,
                    bbox=dict(boxstyle="round,pad=0.15", fc="#fff8d0", alpha=0.85))
    for p in hole["pins"]:
        if p["name"] == "middle":
            ax.plot(*p["utm"][:2], marker=(3, 0, 0), ms=8, color="red", zorder=8)
    gd = hole["green"]
    ax.text(gc[0] + 14, gc[1] + 6, f"Green {gd['depth_yd']:.0f} x {gd['width_yd']:.0f} yd\n{gd['area_sqft']} sq ft\n"
            f"elev. change {hole['elevation_change_m']:+.1f} m", fontsize=8, zorder=8,
            bbox=dict(boxstyle="round", fc="white", alpha=0.85))
    ax.set_xlim(b[0], b[2]); ax.set_ylim(b[1], b[3]); ax.set_aspect("equal")
    card = " / ".join(str(v) for v in hole["scorecard_yards"].values())
    ax.set_title(f"{C.COURSE_SHORT} — hole {hole['hole']} · Par {hole['par']} · " +
                 " / ".join(f"{t['yards']:.0f}" for t in hole["tees"]) +
                 f" yd (model)\nscorecard {card} · hazard labels: yards from {C.TEE_NAMES[C.TEE_KEYS[0]]} tee (front/back)", fontsize=10)
    ax.set_xticks([]); ax.set_yticks([])
    ax.plot([b[2] - 70, b[2] - 20], [b[1] + 12, b[1] + 12], color="white", lw=3); ax.text(b[2] - 45, b[1] + 16, "50 m", color="white", ha="center", fontsize=8)
    ax.annotate("N", xy=(b[0] + 15, b[3] - 12), xytext=(b[0] + 15, b[3] - 35), arrowprops=dict(arrowstyle="-|>", color="white"), color="white", ha="center")
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


def green_map(hole, feats, dem, T, out):
    hn = hole["hole"]
    green = Polygon(hole["green"]["polygon_utm"])
    fringe = [g for g, p in feats if p["hole"] == hn and p["surface"] == "fringe"]
    minx, miny, maxx, maxy = green.buffer(4).bounds
    res = 0.1
    xs = np.arange(minx, maxx, res); ys = np.arange(maxy, miny, -res)
    X, Y = np.meshgrid(xs, ys)
    Z = ndimage.map_coordinates(dem, [(Y - T.f) / T.e - 0.5, (X - T.c) / T.a - 0.5], order=1)
    gy, gx = np.gradient(Z, -res, res)
    slope = np.hypot(gx, gy) * 100
    import shapely
    inside = shapely.contains_xy(green, X, Y)
    fig, ax = plt.subplots(figsize=(8, 8), dpi=150)
    sl = np.where(inside, slope, np.nan)
    im = ax.imshow(sl, extent=(xs[0], xs[-1], ys[-1], ys[0]), cmap="RdYlGn_r", vmin=0, vmax=6, zorder=1)
    plt.colorbar(im, ax=ax, fraction=0.04, label="slope %")
    ax.contour(X, Y, np.where(inside, Z, np.nan), levels=np.arange(np.nanmin(Z[inside]) // 0.05 * 0.05, np.nanmax(Z[inside]), 0.05),
               colors="black", linewidths=0.5, zorder=2)
    step = 12
    ax.quiver(X[::step, ::step], Y[::step, ::step], np.where(inside, -gx, np.nan)[::step, ::step], np.where(inside, -gy, np.nan)[::step, ::step],
              color="navy", scale=0.6, width=0.003, zorder=3)
    ax.plot(*green.exterior.xy, color="black", lw=1.2)
    for f in fringe:
        for p in getattr(f, "geoms", [f]):
            ax.plot(*p.exterior.xy, color="gray", lw=0.6)
    for g, p in feats:
        if p["hole"] == hn and p["surface"] == "bunker" and g.distance(green) < 6:
            ax.add_patch(MPoly(np.asarray(g.exterior.coords), fc=FILL["bunker"], ec="#a89a6a", zorder=1))
    for p in hole["pins"]:
        ax.plot(*p["utm"][:2], "o", ms=5, color="red" if p["name"] != "osm" else "purple", zorder=5)
        ax.annotate(p["name"], p["utm"][:2], xytext=(4, 4), textcoords="offset points", fontsize=7, zorder=6)
    gd = hole["green"]
    ax.set_title(f"Hole {hn} ({hole['nine']} {hole['nine_hole']}) green · {gd['depth_yd']:.0f} yd deep × {gd['width_yd']:.0f} yd wide · {gd['area_sqft']} sq ft\n"
                 f"5 cm contours, arrows = direction of fall · mean slope {gd['slope_pct']['mean']}% · "
                 f"pinnable (≥3 m from edge, ≤{gd.get('pin_slope_limit_pct', 3.0):g}%): {gd['pinnable_fraction'] * 100:.0f}%", fontsize=9)
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


NINE_COLOURS = (("blue", "#1f4fd1"), ("red", "#d1361f"), ("green", "#2a9d3c"), ("orange", "#e08a1e"))


def nine_legend(nine):
    """("1–9 blue · 10–18 red", {hole: colour}): one colour per nine, in hole order."""
    names = list(dict.fromkeys(nine[h] for h in sorted(nine)))
    col = {n: NINE_COLOURS[i % len(NINE_COLOURS)] for i, n in enumerate(names)}
    span = {n: [h for h in sorted(nine) if nine[h] == n] for n in names}
    return " · ".join(f"{span[n][0]}–{span[n][-1]} {col[n][0]}" for n in names), {h: col[n][1] for h, n in nine.items()}


def course_map(data, feats, dem, T, out):
    """Whole-course map: surfaces over hillshade, lines of play, tees and hole numbers (front nine blue, back nine red)."""
    e = C.CORE
    fig, ax = plt.subplots(figsize=(12, 15.6), dpi=150)
    for g, p in feats:
        for poly in getattr(g, "geoms", [g]):
            ax.add_patch(MPoly(np.asarray(poly.exterior.coords), closed=True, fc=FILL.get(p["surface"], "#888"), ec="none", zorder=1))
    step = 4
    hs = hillshade(dem[::step, ::step], T.a * step)
    ax.imshow(hs, extent=(e["xmin"], e["xmax"], e["ymin"], e["ymax"]), cmap="gray", alpha=0.3, zorder=2, vmin=0, vmax=1)
    legend, nine_colour = nine_legend(C.NINE)
    for h in data["holes"]:
        if not h.get("tees"):
            continue
        col = nine_colour[h["hole"]]
        cl = np.asarray(h["centerline_utm"])
        ax.plot(cl[:, 0], cl[:, 1], color="white", lw=1.0, zorder=4)
        ax.plot(*cl[0], "o", ms=4, color=col, zorder=5)
        gc = h["green"]["centre_utm"]
        ax.annotate(str(h["hole"]), gc[:2], fontsize=11, fontweight="bold", color="white", ha="center", va="center", zorder=6,
                    bbox=dict(boxstyle="circle,pad=0.25", fc=col, ec="white", lw=1))
    ax.set_xlim(e["xmin"], e["xmax"]); ax.set_ylim(e["ymin"], e["ymax"]); ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    tot = {k: sum(t["yards"] for h in data["holes"] for t in h.get("tees", []) if t["key"] == k) for k in C.TEE_KEYS}
    card = {k: sum(v[1 + i] for v in C.SCORECARD.values()) for i, k in enumerate(C.TEE_KEYS)}
    ax.set_title(f"{C.COURSE_NAME} ({legend})\nmodel yardage " + " / ".join(f"{tot[k]:.0f}" for k in C.TEE_KEYS) +
                 " (card " + " / ".join(str(card[k]) for k in C.TEE_KEYS) + ", " + " / ".join(C.TEE_NAMES[k] for k in C.TEE_KEYS) + ")", fontsize=11)
    ax.plot([e["xmax"] - 230, e["xmax"] - 30], [e["ymin"] + 30, e["ymin"] + 30], color="white", lw=3, zorder=7)
    ax.text(e["xmax"] - 130, e["ymin"] + 42, "200 m", color="white", ha="center", zorder=7)
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


def main():
    data = json.load(open(C.OUTPUT / "holes.json"))
    feats = [(shape(f["geometry"]), f["properties"]) for f in json.load(open(C.FEATURES / "course_surfaces.geojson"))["features"]]
    trees = json.load(open(C.FEATURES / "trees.geojson"))["features"]
    with rasterio.open(C.BUILD / "dem_final.tif") as ds:
        dem = ds.read(1).astype(np.float64); T = ds.transform
    (C.OUTPUT / "maps").mkdir(parents=True, exist_ok=True)
    n = 0
    for hole in data["holes"]:
        if not hole.get("tees"):
            continue
        hn = hole["hole"]
        hole_map(hole, feats, dem, T, C.OUTPUT / f"maps/hole{hn:02d}_map.png", trees)
        green_map(hole, feats, dem, T, C.OUTPUT / f"maps/hole{hn:02d}_green.png")
        n += 1
    course_map(data, feats, dem, T, C.OUTPUT / "maps/course_map.png")
    print("maps written for", n, "holes + course map")


if __name__ == "__main__":
    main()
