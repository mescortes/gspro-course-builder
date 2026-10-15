"""Download CC0 PBR texture sets from Poly Haven (diffuse, OpenGL normal, roughness/ARM) at 2k, plus the leaf sprite
atlases make_foliage.py cuts foliage cards from (data/<slug>/textures/leaf_refs/<model>__<file>).

  fetch_textures.py [asset ...]    (no argument: the leaf atlases and every texture the engine and the region use)

Downloads go through sources.http (requests, retried, written to a .part file and renamed once complete). The files
each asset was given are recorded in data/<slug>/textures.source.json: a rerun with all of them present needs no
network (the Poly Haven API used to be asked about every asset first, so an offline rerun crashed). A file already
there is kept as it is: the build was made from it.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); import config as C
from sources import http, store

IDS = ["sand_01", "withered_grass", "wood_chips", "dry_ground_01", "concrete_floor_worn_001", "asphalt_02",
       "leafy_grass", "bark_brown_01", "white_stucco", "clay_roof_tiles", "grey_roof_tiles", "forest_leaves_02",
       "brown_mud_leaves_01"]
IDS += [t for t in [*C.REGION["trees"]["bark"].values(), *C.REGION["materials"].values()] if t not in IDS]  # the region's
LEAF_REFS = [("island_tree_02", "leaves_diff")]   # broadleaf sprites (recoloured per species in make_foliage.py)
API = "https://api.polyhaven.com/files/"
MAPS = ("Diffuse", "nor_gl", "Rough", "arm", "Displacement")


def api(asset):
    """The Poly Haven file list of an asset."""
    return http.get_json(API + asset, valid=lambda j: isinstance(j, dict))


def maps(files):
    """{file name: url} of an asset's 2k maps."""
    out = {}
    for key in MAPS:
        if key in files and "2k" in files[key]:
            fmt = "jpg" if "jpg" in files[key]["2k"] else "png"
            out[f"{key.lower()}.{fmt}"] = files[key]["2k"][fmt]["url"]
    return out


def leaf_atlas(model, key):
    url = api(model)[key]["1k"]["jpg"]["url"]
    return {f"{model}__{url.split('/')[-1]}": url}


def fetch(name, folder, listing, record):
    """The files of `name` into `folder`, listed by `listing()` ({file name: url}, from the Poly Haven API) unless the
    record lists them all and they are there. Offline, an asset fetched before the record existed keeps its files."""
    done = record.get(name)
    if not (done and all((folder / f).exists() for f in done)):
        try:
            want = listing()
        except RuntimeError as ex:
            have = sorted(p.name for p in folder.glob("*") if p.is_file()) if folder.exists() and not done else []
            if not have:
                sys.exit(f"textures: Poly Haven does not answer for {name} ({ex}): check the network and rerun fetch_textures.py")
            print(f"textures: Poly Haven does not answer for {name}: keeping the {len(have)} files already in {folder}", flush=True)
            return
        for f, url in want.items():
            if not (folder / f).exists():
                http.download(url, folder / f)
        record[name] = done = dict(sorted(want.items()))   # file name: url
    for f in done:
        print(name, f, (folder / f).stat().st_size)


def main(ids=()):
    tex = C.DATA / "textures"
    record = store.read_record(tex) or {}
    try:
        for model, key in ([] if ids else LEAF_REFS):
            fetch(f"leaf_refs/{model}", tex / "leaf_refs", lambda: leaf_atlas(model, key), record)
        for a in (ids or IDS):
            fetch(a, tex / a, lambda: maps(api(a)), record)
    finally:
        store.write_record(tex, record)   # data/<slug>/textures.source.json (outside textures/: not a build input)


if __name__ == "__main__":
    main(sys.argv[1:])
