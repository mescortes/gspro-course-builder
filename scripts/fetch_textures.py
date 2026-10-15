"""Download CC0 PBR texture sets from Poly Haven (diffuse, OpenGL normal, roughness/ARM) at 2k, plus the leaf sprite
atlases make_foliage.py cuts foliage cards from (data/textures/leaf_refs/<model>__<file>)."""
import json, sys, os, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); import config as C
IDS = ["sand_01", "withered_grass", "wood_chips", "dry_ground_01", "concrete_floor_worn_001", "asphalt_02",
       "leafy_grass", "bark_brown_01", "white_stucco", "clay_roof_tiles", "grey_roof_tiles", "forest_leaves_02",
       "brown_mud_leaves_01"]
IDS += [t for t in [*C.REGION["trees"]["bark"].values(), *C.REGION["materials"].values()] if t not in IDS]  # the region's
LEAF_REFS = [("island_tree_02", "leaves_diff")]   # broadleaf sprites (recoloured per species in make_foliage.py)
UA = {"User-Agent": "westmount-course-builder"}
def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()
ref = C.DATA / "textures" / "leaf_refs"; ref.mkdir(parents=True, exist_ok=True)
for model, key in ([] if sys.argv[1:] else LEAF_REFS):
    url = json.loads(get(f"https://api.polyhaven.com/files/{model}"))[key]["1k"]["jpg"]["url"]
    dst = ref / f"{model}__{url.split('/')[-1]}"
    if not dst.exists():
        dst.write_bytes(get(url))
    print(model, key, dst.stat().st_size)
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
