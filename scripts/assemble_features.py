"""Merge the automatic surface partition with hand-curated overrides.

features/overrides/*.geojson: polygons with properties {surface, hole}. Each override polygon is burned on top of the
automatic partition (removing whatever was there), so curated edits survive re-running the automatic steps.
Output: features/course_surfaces.geojson
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


def burn_overrides(feats, over):
    """feats, over: lists of (shapely geometry, properties). Later overrides win: each one is cut out of the automatic
    partition and of every earlier override."""
    out = [(g, p) for g, p in feats]
    for g, p in over:
        g = g.buffer(0)
        nxt, specks = [], []
        for h, q in out:
            if not h.intersects(g):
                nxt.append((h, q)); continue
            for r in polys_of(h.difference(g)):
                if r.area > min_part(q["surface"]):
                    nxt.append((r, dict(q, area=round(r.area, 2))))
                else:
                    specks.append(r)  # slivers left by the cut join the override, so the partition stays gap-free
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
        out = nxt
    return out


def main():
    auto = json.load(open(C.FEATURES / "auto_core.geojson"))
    feats = [(shape(f["geometry"]), f["properties"]) for f in auto["features"]]
    over = []
    for p in sorted(glob.glob(str(C.FEATURES / "overrides/*.geojson"))):
        for f in json.load(open(p))["features"]:
            over.append((shape(f["geometry"]), f["properties"]))
    if over:
        feats = burn_overrides(feats, over)
    json.dump({"type": "FeatureCollection", "crs": auto.get("crs"),
               "features": [{"type": "Feature", "geometry": mapping(g), "properties": p} for g, p in feats]},
              open(C.FEATURES / "course_surfaces.geojson", "w"))
    print("features", len(feats), "overrides", len(over))


if __name__ == "__main__":
    main()
