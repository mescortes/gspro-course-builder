"""Run the whole pipeline (or a sub-range of steps). Usage: build_all.py [first_step] [last_step] | --list"""
import os, platform, shutil, subprocess, sys, time
from pathlib import Path
S = Path(__file__).parent
sys.path.insert(0, str(S)); import config as C
STEPS = [
    ("register",   "register_imagery.py"),   # imagery translated onto the LiDAR (config.IMAGERY_SHIFT)
    ("rasters",    "build_rasters.py"),      # LiDAR -> DEM / DSM / CHM / intensity
    ("paths",      "trace_paths.py"),        # cart-path centre lines from the photo ([tuning] trace_paths)
    ("classify",   "surface_classify.py"),   # imagery + LiDAR per-pixel surfaces
    ("vectorize",  "vectorize.py"),          # clean surface partition (build/<slug>/features/auto_core.geojson)
    ("assemble",   "assemble_features.py"),  # auto + manual overrides -> build/<slug>/features/course_surfaces.geojson
    ("trees",      "detect_trees.py"),       # LiDAR tree detection + archetypes
    ("textures",   "make_textures.py"),      # procedural turf textures
    ("foliage",    "make_foliage.py"),       # foliage card atlases
    ("treemodels", "make_trees.py"),         # tree archetype meshes
    ("mesh",       "build_terrain_mesh.py"), # conforming terrain triangulation
    ("backdrop",   "build_backdrop.py"),     # 5 km surrounding terrain (watertight seam to the core mesh)
    ("hole",       "hole_data.py"),          # tees, pins, yardages
    ("facade",     "make_facade.py"),        # building facade texture
    ("export",     "export_course.py"),      # glTF (terrain + trees + backdrop + structures)
    ("gspro",      "export_gspro.py"),       # heightmap RAW, OPCD SVG, trees CSV, GreenKeeper data
    ("prefabs",    "export_tree_prefabs.py"),  # Unity tree prefabs (LOD0-2) + reference sizes
    ("fbx",        None),                    # Blender: FBX meshes in the Unity terrain frame
    ("maps",       "make_maps.py"),          # yardage-book hole maps, green maps, course map
    ("views",      "make_views.py"),         # viewer camera presets (output/<slug>/views.json) from hole 1
]
names = [n for n, _ in STEPS]


def blender_defaults():
    """Where Blender installs itself when it is not on PATH: the macOS app bundle; on Windows the installer's folders,
    4.2 LTS first."""
    if platform.system() == "Darwin":
        return ("/Applications/Blender.app/Contents/MacOS/Blender",)
    if platform.system() == "Windows":
        found = sorted(map(str, Path("C:/Program Files/Blender Foundation").glob("Blender*/blender.exe")), reverse=True)
        return tuple(sorted(found, key=lambda p: "Blender 4.2" not in p))
    return ()


def step_range(args):
    """(first, last) step indices from the command line, or exit listing the step names (a wrong name used to be a
    bare ValueError traceback)."""
    listing = "steps, in order: " + " ".join(names)
    if args[:1] == ["--list"]:
        print(listing); sys.exit(0)
    bad = [x for x in args[:2] if x not in names]
    if bad or len(args) > 2:
        sys.exit(f"build_all.py [first_step] [last_step]: {', '.join(map(repr, bad or args[2:]))} is not a step; {listing}")
    a = names.index(args[0]) if args else 0
    b = names.index(args[1]) if len(args) > 1 else len(STEPS) - 1
    if b < a:
        sys.exit(f"build_all.py {args[0]} {args[1]}: {args[1]!r} comes before {args[0]!r}; {listing}")
    return a, b


def find_blender(env=os.environ, which=shutil.which, defaults=None):
    """Headless Blender for the FBX step: $BLENDER, else `blender` on PATH, else the usual install folders; None when
    there is none. A BLENDER that names no program is an error, not a fallback."""
    b = env.get("BLENDER")
    if b:
        exe = which(b) or (b if Path(b).is_file() and os.access(b, os.X_OK) else None)
        if exe is None:
            sys.exit(f"BLENDER={b} is not a program: point it at the Blender 4.2 LTS executable "
                     "(macOS: /Applications/Blender.app/Contents/MacOS/Blender)")
        return exe
    return which("blender") or next((d for d in (blender_defaults() if defaults is None else defaults)
                                     if Path(d).is_file()), None)


def main(argv=None):
    a, b = step_range(sys.argv[1:] if argv is None else argv)
    blender = None
    if a <= names.index("fbx") <= b:  # look before the first step, not after an hour of them
        blender = find_blender()
        if blender is None:
            sys.exit("no Blender for the fbx step: set BLENDER=/path/to/blender (4.2 LTS; macOS: "
                     "/Applications/Blender.app/Contents/MacOS/Blender), or build without it: "
                     "build_all.py register prefabs, then build_all.py maps views")
    print(f"course {C.SLUG} ({C.COURSE_NAME}), profile {C.PROFILE}", flush=True)
    for n, script in STEPS[a:b + 1]:
        if script is None:
            t = time.time(); print(f"== {n}", flush=True)
            subprocess.run([blender, "-b", "--python-exit-code", "1", "--python", str(S / "export_fbx_blender.py"), "--", str(C.OUTPUT / f"{C.MODEL_NAME}_noveg.glb"),
                            str(C.OUTPUT / "gspro"), str(C.OUTPUT / "gspro/terrain.json")], check=True, stdout=subprocess.DEVNULL)
            if (C.OUTPUT / "gspro/tree_prefabs.glb").exists():
                subprocess.run([blender, "-b", "--python-exit-code", "1", "--python", str(S / "glb_to_fbx_blender.py"), "--", str(C.OUTPUT / "gspro/tree_prefabs.glb"),
                                str(C.OUTPUT / "gspro/tree_prefabs.fbx")], check=True, stdout=subprocess.DEVNULL)
            print(f"   {n} done in {time.time() - t:.0f}s", flush=True)
            continue
        if not (S / script).exists():
            print(f"-- skip {n} (missing {script})"); continue
        if n == "paths" and not C.tuning("trace_paths", True):   # a course whose OSM maps its cart paths
            print("-- skip paths (course.toml [tuning] trace_paths = false)"); continue
        t = time.time(); print(f"== {n}", flush=True)
        subprocess.run([sys.executable, str(S / script)], check=True)
        print(f"   {n} done in {time.time() - t:.0f}s", flush=True)


if __name__ == "__main__":
    main()
