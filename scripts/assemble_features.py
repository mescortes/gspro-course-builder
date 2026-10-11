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
from vectorize import STROKE, polys_of

auto = json.load(open(C.FEATURES / "auto_core.geojson"))
feats = [(shape(f["geometry"]), f["properties"]) for f in auto["features"]]
over = []
for p in sorted(glob.glob(str(C.FEATURES / "overrides/*.geojson"))):
    for f in json.load(open(p))["features"]:
        over.append((shape(f["geometry"]), f["properties"]))
if over:
    # later overrides win: each one is cut out of the automatic partition and of every earlier override
    out = [(g, p) for g, p in feats]
    for g, p in over:
        g = g.buffer(0)
        nxt, specks = [], []
        for h, q in out:
            if not h.intersects(g):
                nxt.append((h, q)); continue
            for r in polys_of(h.difference(g)):
                if r.area > 0.05:
                    nxt.append((r, dict(q, area=round(r.area, 2))))
                else:
                    specks.append(r)  # slivers left by the cut join the override, so the partition stays gap-free
        if specks:
            g = unary_union([g] + specks)
        for r in polys_of(g):
            nxt.append((r, {"surface": p["surface"], "hole": int(p.get("hole", 99)), "area": round(r.area, 2),
                            "stroke": STROKE.get(p["surface"], "#ff00ff"), "source": "override"}))
        out = nxt
    feats = out
json.dump({"type": "FeatureCollection", "crs": auto.get("crs"),
           "features": [{"type": "Feature", "geometry": mapping(g), "properties": p} for g, p in feats]},
          open(C.FEATURES / "course_surfaces.geojson", "w"))
print("features", len(feats), "overrides", len(over))
