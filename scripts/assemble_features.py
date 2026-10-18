"""Merge the automatic surface partition with hand-curated overrides.

courses/<slug>/features/overrides/*.geojson: polygons with properties {surface, hole}. Each override polygon is burned on top of the
automatic partition (removing whatever was there), so curated edits survive re-running the automatic steps.
Output: build/<slug>/features/course_surfaces.geojson
"""
import sys, json, glob
from shapely.geometry import shape, mapping, box
from shapely.ops import unary_union
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C
from vectorize import STROKE, MIN_AREA, polys_of


def min_part(surface):
    """Smallest remnant of `surface` an override cut may leave: vectorize's own minimum part size, at least the 0.05 m2
    speck limit. A trimmed bunker otherwise left 0.1-1.3 m2 strips: sub-metre bunkers with 10 cm lips and 0 m2
    GreenKeeper hazards."""
    return max(0.05, 0.25 * MIN_AREA[surface]) if surface in MIN_AREA else 0.05


# An override cut leaves no part of these surfaces narrower than this (m: the widest circle inside it). A bunker drawn
# from the LiDAR 1-4 m off the photo's sand left the automatic bunker's strip along its lip, 0.5-1.7 m wide (MountainGate
# holes 4-10, Brambles holes 4 and 14): a bunker of its own, a tiny hazard in holes.json.
MIN_WIDTH = {"bunker": 2.0}


def too_narrow(part, surface):
    """Is a remnant of an override cut narrower than MIN_WIDTH[surface] everywhere?"""
    import shapely
    w = MIN_WIDTH.get(surface)
    return w is not None and 2 * shapely.maximum_inscribed_circle(part, 0.01).length < w


def give_to_neighbour(r, feats, surface):
    """Merge the strip r into the part of `feats` ([(geometry, properties)], changed in place) it shares the longest
    edge with, a part of another surface than `surface` first (a bunker strip goes to the grass beside it, not to the
    drawn bunker); with no neighbour it stays a part of its own. Only the part that takes it changes."""
    edge = [(r.boundary.intersection(h.boundary).length, q["surface"] != surface, j)
            for j, (h, q) in enumerate(feats) if h.distance(r) < 1e-9]
    edge = [(other, length, j) for length, other, j in edge if length > 0]
    if not edge:
        return False
    _, _, j = max(edge)
    h, q = feats[j]
    m = unary_union([h, r]); feats[j] = (m, dict(q, area=round(m.area, 2)))
    return True


def burn_overrides(feats, over, aoi=None):
    """feats, over: lists of (shapely geometry, properties). Later overrides win: each one is cut out of the automatic
    partition and of every earlier override. An override reaching past `aoi` (the build area) is clipped to it: the
    test profile reads every hole's overrides for a small extent. One inside it is used exactly as drawn."""
    out = [(g, p) for g, p in feats]
    for g, p in over:
        g = g.buffer(0)
        if aoi is not None and not aoi.contains(g):
            g = g.intersection(aoi)
            if g.is_empty or g.area <= 0:
                continue
        nxt, specks, strips = [], [], []
        for h, q in out:
            if not h.intersects(g):
                nxt.append((h, q)); continue
            for r in polys_of(h.difference(g)):
                if r.area <= min_part(q["surface"]):
                    specks.append(r)  # slivers left by the cut join the override, so the partition stays gap-free
                elif too_narrow(r, q["surface"]):
                    strips.append((r, q))
                else:
                    nxt.append((r, dict(q, area=round(r.area, 2))))
        if specks:
            g = unary_union([g] + specks)
        parts = polys_of(g)
        for r in parts:
            if len(parts) > 1 and r.area <= min_part(p["surface"]):
                # a speck that met the override only at a vertex stays detached: give it to the neighbour it shares
                # the longest edge with
                edge = [(r.boundary.intersection(h.boundary).length, j) for j, (h, _) in enumerate(nxt) if h.distance(r) < 1e-9]
                if edge and max(edge)[0] > 0:
                    j = max(edge)[1]; h, q = nxt[j]
                    m = unary_union([h, r]); nxt[j] = (m, dict(q, area=round(m.area, 2)))
                    continue
            nxt.append((r, {"surface": p["surface"], "hole": int(p.get("hole", 99)), "area": round(r.area, 2),
                            "stroke": STROKE.get(p["surface"], "#ff00ff"), "source": "override"}))
        for r, q in strips:   # once the override is in: a strip may touch nothing else
            if not give_to_neighbour(r, nxt, q["surface"]):
                nxt.append((r, dict(q, area=round(r.area, 2))))
        out = nxt
    return out


def main():
    auto = json.load(open(C.FEATURES / "auto_core.geojson"))
    feats = [(shape(f["geometry"]), f["properties"]) for f in auto["features"]]
    over = []
    for p in sorted(glob.glob(str(C.SOURCES / "overrides/*.geojson"))):
        for f in json.load(open(p))["features"]:
            over.append((shape(f["geometry"]), f["properties"]))
    if over:
        feats = burn_overrides(feats, over, aoi=box(C.CORE["xmin"], C.CORE["ymin"], C.CORE["xmax"], C.CORE["ymax"]))
    json.dump({"type": "FeatureCollection", "crs": auto.get("crs"),
               "features": [{"type": "Feature", "geometry": mapping(g), "properties": p} for g, p in feats]},
              open(C.FEATURES / "course_surfaces.geojson", "w"))
    print("features", len(feats), "overrides", len(over))


if __name__ == "__main__":
    main()
