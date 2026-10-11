"""Move QA overrides drawn on the unregistered photo into the LiDAR-registered frame (config.IMAGERY_SHIFT).

Idempotent: features / meta files already marked {"frame": "lidar"} are left alone; everything else is translated by
the imagery shift and marked. Run once after switching config.IMAGERY to the registered copy.
"""
import sys, json, glob
from shapely.geometry import shape, mapping
from shapely.affinity import translate
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C

dx, dy = C.IMAGERY_SHIFT
n_f = n_m = 0
for p in sorted(glob.glob(str(C.FEATURES / "overrides" / "*.geojson"))):
    fc = json.load(open(p))
    for f in fc["features"]:
        if f["properties"].get("frame") == "lidar":
            continue
        f["geometry"] = mapping(translate(shape(f["geometry"]), dx, dy))
        f["properties"]["frame"] = "lidar"
        n_f += 1
    json.dump(fc, open(p, "w"))
for p in sorted(glob.glob(str(C.FEATURES / "overrides" / "*_meta.json"))):
    m = json.load(open(p))
    if m.get("frame") == "lidar":
        continue
    if "aim_points_utm" in m:
        m["aim_points_utm"] = [[a[0] + dx, a[1] + dy] for a in m["aim_points_utm"]]
    if "tees_utm" in m:
        m["tees_utm"] = {k: [v[0] + dx, v[1] + dy] for k, v in m["tees_utm"].items()}
    m["frame"] = "lidar"
    json.dump(m, open(p, "w"), indent=1)
    n_m += 1
print(f"shifted {n_f} override features and {n_m} meta files by ({dx}, {dy}) m")
