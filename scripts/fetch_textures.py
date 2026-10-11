"""Download CC0 PBR texture sets from Poly Haven (diffuse, OpenGL normal, roughness/ARM) at 2k."""
import json, sys, os, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); import config as C
IDS = ["sand_01", "withered_grass", "wood_chips", "dry_ground_01", "concrete_floor_worn_001", "asphalt_02",
       "leafy_grass", "bark_platanus", "pine_bark", "eucalyptus_bark", "jolcham_oak_bark_01", "white_stucco",
       "clay_roof_tiles", "grey_roof_tiles", "forest_leaves_02", "brown_mud_leaves_01"]
UA = {"User-Agent": "mountain-gate-course-builder"}
def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()
for a in (sys.argv[1:] or IDS):
    out = C.DATA / "textures" / a; out.mkdir(parents=True, exist_ok=True)
    files = json.loads(get(f"https://api.polyhaven.com/files/{a}"))
    for key in ("Diffuse", "nor_gl", "Rough", "arm", "Displacement"):
        if key in files and "2k" in files[key]:
            fmt = "jpg" if "jpg" in files[key]["2k"] else "png"
            url = files[key]["2k"][fmt]["url"]; dst = out / f"{key.lower()}.{fmt}"
            if not dst.exists():
                dst.write_bytes(get(url))
            print(a, key, dst.stat().st_size)
