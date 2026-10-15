"""Measure the planimetric offset of the aerial imagery (and OSM) relative to the LiDAR.

Method: bunker sand (bright, low-chroma pixels in the photo) vs LiDAR bunker hollows (DEM below its local mean).
For each sand blob, search the shift (dx, dy) in [-6, 6] m that maximises the overlap of the shifted sand with the hollow
mask in a window around it; report robust statistics overall and per region. Positive dx = photo must move EAST.
Also: OSM building footprints vs LiDAR elevated-object mask (dsm - dem > 2.5 m).
"""
import sys, json
import numpy as np
import rasterio
from rasterio.features import rasterize
from scipy import ndimage
from skimage.color import rgb2lab

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C
from surface_classify import grid, read_imagery_window, osm_geoms
from vectorize import sand_mask

RES = C.DEM_RES
S = 24  # max shift in px (6 m)
MIN_BUNKERS = 3  # fewer give no robust median


def best_shift(a, b, mask_win):
    """shift (dy, dx) in px of a that best overlaps b; returns (dy, dx, score, score0)."""
    best = (0, 0, -1)
    A = a.astype(np.float32); B = b.astype(np.float32)
    for dy in range(-S, S + 1):
        for dx in range(-S, S + 1):
            sh = np.roll(np.roll(A, dy, 0), dx, 1)
            sc = (sh * B)[mask_win].sum()
            if sc > best[2]:
                best = (dy, dx, sc)
    s0 = (A * B)[mask_win].sum()
    return best[0], best[1], best[2], s0


def applied_shift(raw=None, registered=None, fallback=None):
    """The shift (m, +E/+N) the registered photo on disk carries: its origin minus the raw photo's, as
    register_imagery.py writes it. That photo is the one measured, so the new shift adds the measurement to this one:
    course.toml's [imagery] shift differs from it when the shift was changed after build_all.py register ran, and adding
    to it counted the measurement twice. `fallback` (course.toml's shift) when either photo is missing."""
    from pathlib import Path
    raw, registered = Path(raw or C.IMAGERY_RAW), Path(registered or C.IMAGERY)
    if not (raw.exists() and registered.exists()):
        return tuple(C.IMAGERY_SHIFT if fallback is None else fallback)
    with rasterio.open(registered) as d, rasterio.open(raw) as s:
        return (round(d.transform.c - s.transform.c, 3), round(d.transform.f - s.transform.f, 3))


def bunker_shift(A, core, shift):
    """(report lines, the new [imagery] shift or None) from the per-bunker offsets A (x, y, dx, dy, score rows). The
    photo measured is the registered one, so the new shift is the one it carries (applied_shift) plus the median
    offset. Fewer than MIN_BUNKERS bunkers used to crash (IndexError) instead of saying so."""
    if len(A) < MIN_BUNKERS:
        return [f"!! {len(A)} bunker(s) pass the sand and hollow tests, {MIN_BUNKERS} are needed for a photo shift: if "
                "the sand is not the usual tan (white, grey), set course.toml [tuning.sand] (the bunker sand colour rule, "
                "vectorize.py SAND: L_min, a_min, b_min, b_max); otherwise measure a few photo features against the LiDAR by hand (the OSM "
                "building line below is OSM's offset, not the photo's)"], None
    lines = []
    def stats(sel, name):
        if sel.sum() < MIN_BUNKERS:
            return
        dx, dy = np.median(A[sel, 2]), np.median(A[sel, 3])
        mx = np.median(np.abs(A[sel, 2] - dx)); my = np.median(np.abs(A[sel, 3] - dy))
        lines.append(f"{name:12s} n={sel.sum():3d}  photo->lidar shift: dx {dx:+.2f} m (MAD {mx:.2f})  dy {dy:+.2f} m (MAD {my:.2f})")
    stats(np.ones(len(A), bool), "all")
    cy = 0.5 * (core["ymin"] + core["ymax"]); cx = 0.5 * (core["xmin"] + core["xmax"])
    stats(A[:, 1] > cy, "north half")
    stats(A[:, 1] <= cy, "south half")
    stats(A[:, 0] < cx, "west")
    stats(A[:, 0] >= cx, "east")
    new = (round(shift[0] + float(np.median(A[:, 2])), 2), round(shift[1] + float(np.median(A[:, 3])), 2))
    lines.append(f"shift = [{new[0]:.2f}, {new[1]:.2f}]  # course.toml [imagery]: the registered photo's shift "
                 f"[{shift[0]:.2f}, {shift[1]:.2f}] plus this measurement; then rebuild (build_all.py register)")
    return lines, new


def main():
    W, H, T = grid()
    dem = rasterio.open(C.BUILD / "dem_final.tif").read(1)
    loc = dem - ndimage.gaussian_filter(dem, 10)
    hollow = loc < -0.12
    feats = json.load(open(C.FEATURES / "auto_core.geojson"))["features"]
    from shapely.geometry import shape
    bunkers = [shape(f["geometry"]) for f in feats if f["properties"]["surface"] == "bunker" and f["properties"]["area"] > 25]
    out = []
    for g in bunkers:
        x0, y0, x1, y1 = g.buffer(8).bounds
        c0, c1 = int((x0 - T.c) / RES), int((x1 - T.c) / RES); r0, r1 = int((T.f - y1) / RES), int((T.f - y0) / RES)
        if c0 < S or r0 < S or c1 > W - S or r1 > H - S:
            continue
        rgb = read_imagery_window(T, r0 - S, r1 + S, c0 - S, c1 + S)
        Lab = rgb2lab(np.moveaxis(rgb, 0, -1))
        sand, _ = sand_mask(Lab[..., 0], Lab[..., 1], Lab[..., 2], parts=True)  # sunlit sand ([tuning.sand])
        hol = hollow[r0 - S:r1 + S, c0 - S:c1 + S]
        win = np.zeros_like(sand); win[S:-S, S:-S] = True
        if sand[win].sum() < 200 or hol[win].sum() < 200:
            continue
        dy, dx, sc, s0 = best_shift(sand, hol, win)
        if sc < 1.15 * s0 and (dx, dy) != (0, 0):
            pass
        c = g.centroid
        out.append((c.x, c.y, dx * RES, -dy * RES, sc / max(s0, 1)))
    A = np.array(out).reshape(-1, 5)
    print(f"bunkers used: {len(A)}")
    shift = applied_shift()
    if any(abs(a - b) > 1e-3 for a, b in zip(shift, C.IMAGERY_SHIFT)):
        print(f"!! the registered photo ({C.IMAGERY.name}) carries shift [{shift[0]:.2f}, {shift[1]:.2f}], course.toml "
              f"[imagery] shift is [{C.IMAGERY_SHIFT[0]:.2f}, {C.IMAGERY_SHIFT[1]:.2f}]: build_all.py register has not "
              "run since the shift changed. This measures the registered photo, so the new shift below adds to its "
              "shift; run build_all.py register (and the steps after it) to build with course.toml's")
    lines, _ = bunker_shift(A, C.CORE, shift)
    for x in lines:
        print(x)
    np.save(C.BUILD / "registration_bunkers.npy", A)
    # buildings: OSM footprints vs LiDAR elevated objects
    dsm = rasterio.open(C.BUILD / "dsm.tif").read(1); dem2 = dem.reshape(dem.shape[0] // 2, 2, dem.shape[1] // 2, 2).mean((1, 3))
    T2 = rasterio.open(C.BUILD / "dsm.tif").transform
    elev = (dsm - dem2) > 2.5
    G = osm_geoms()
    bl = [g for _, t, g in G if "building" in t and g.geom_type == "Polygon"]
    bm = rasterize([(g, 1) for g in bl], out_shape=elev.shape, transform=T2, fill=0, dtype="uint8").astype(np.float32)
    E = elev.astype(np.float32)
    best = (0, 0, -1)
    for dy in range(-12, 13):
        for dx in range(-12, 13):
            sc = (np.roll(np.roll(bm, dy, 0), dx, 1) * E).sum()
            if sc > best[2]:
                best = (dy, dx, sc)
    print(f"OSM buildings -> lidar shift: dx {best[1] * 0.5:+.2f} m  dy {-best[0] * 0.5:+.2f} m  (gain {best[2] / max((bm * E).sum(), 1):.3f})")


if __name__ == "__main__":
    main()
