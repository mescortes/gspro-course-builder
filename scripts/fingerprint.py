"""Build fingerprint: a digest of every downloaded input and build product, compared with a golden reference before an
engine change merges. Usage:

  fingerprint.py write [path]     compute and save (default courses/<slug>/fingerprint.json)
  fingerprint.py check [path]     compute and compare; exit 1 when an enforced artefact changed, is missing or is new
  fingerprint.py compare A B      compare two saved fingerprints

GeoTIFFs hash their pixels and georeference (not the encoding), .npz files their arrays (not the zip timestamps),
everything else its bytes. FBX and .blend files are listed but not enforced: Blender writes the time into both and
derives FBX object ids from Python's per-process string hash (their content is covered by the glTF they are made from
and fbx_manifest.json).
Summaries (surface counts and areas, trees per archetype, hole yards, glTF object counts) explain a difference. The
environment (machine, OS, package versions, Blender) is recorded; a different one is a note, not a failure, but
floating-point results are only expected to match on the machine and packages that wrote the golden file.
"""
import hashlib, json, os, platform, re, shutil, struct, subprocess, sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent)); import config as C

GOLDEN = C.COURSE_DIR / "fingerprint.json"
UNENFORCED = (".fbx", ".blend")  # Blender writes the time into both, and FBX ids come from the salted str hash


@dataclass
class Artefact:
    key: str           # stable logical name, e.g. OUTPUT/holes.json (the folders may move; the key does not)
    path: Path
    core: bool = False  # the plan's golden set: holes, surfaces, trees, heightmap, GreenKeeper data, glTF
    enforced: bool = True


def artefacts():
    """Every downloaded input and build product, in pipeline order (a change upstream explains the ones below it)."""
    D, B, F, O = C.DATA, C.BUILD, C.FEATURES, C.OUTPUT
    out = []

    def one(key, path, **kw):
        out.append(Artefact(key, Path(path), **kw))

    def many(prefix, base, pattern, skip=lambda p: False, **kw):
        for p in sorted(Path(base).glob(pattern)):
            if p.is_file() and not skip(p):
                rel = p.relative_to(base).as_posix()
                one(f"{prefix}/{rel}", p, enforced=p.suffix.lower() not in UNENFORCED, **kw)

    import build_backdrop  # the backdrop photo names carry the extent (a test-profile build writes its own)
    photos = [D / "imagery" / p.name[:-4] for p in (build_backdrop.FAR_IMG, build_backdrop.NEAR_IMG)]
    # inputs: fetch_data.py, fetch_textures.py, fetch_backdrop.py, build_backdrop.py (photo download)
    many("DATA", D, "lidar/*.laz")
    one("DATA/imagery/" + C.IMAGERY_RAW.name, C.IMAGERY_RAW)
    for p in photos:
        for suffix in (".tif", "_nir.tif"):
            one(f"DATA/imagery/{p.name}{suffix}", f"{p}{suffix}")
    many("DATA", D, "dem/*.tif")
    many("DATA", D, "textures/**/*")
    # register, rasters, paths, classify, vectorize, assemble, trees
    one("DATA/imagery/" + C.IMAGERY.name, C.IMAGERY)
    for n in ("dem_raw", "dem", "dsm", "bdsm", "chm", "intensity", "ground_count"):
        one(f"BUILD/{n}.tif", B / f"{n}.tif")
    one("RESEARCH/paths_detected.geojson", B / "paths_detected.geojson")  # key kept from the pre-course layout
    for n in ("labels_osm.tif", "classes.tif", "proba_u8.npy"):
        one(f"BUILD/{n}", B / n)
    one("FEATURES/auto_core.geojson", F / "auto_core.geojson")
    one("FEATURES/course_surfaces.geojson", F / "course_surfaces.geojson", core=True)
    one("FEATURES/trees.geojson", F / "trees.geojson", core=True)
    one("BUILD/crowns.tif", B / "crowns.tif")
    # textures, foliage, treemodels, mesh, backdrop, hole, facade
    many("DATA", D, "textures_gen/**/*")
    many("DATA", D, "trees/*.npz")
    one("BUILD/dem_final.tif", B / "dem_final.tif")
    one("BUILD/terrain_mesh.npz", B / "terrain_mesh.npz")
    one("BUILD/water_planes.json", B / "water_planes.json")
    for p in photos:
        for suffix in ("_summer.tif", "_raw.jpg", ".jpg"):
            one(f"DATA/imagery/{p.name}{suffix}", f"{p}{suffix}")
    one("BUILD/backdrop_mesh.npz", B / "backdrop_mesh.npz")
    one("OUTPUT/holes.json", O / "holes.json", core=True)
    one("OUTPUT/hole01.json", O / "hole01.json")
    # export, gspro, prefabs, fbx, maps, views
    one(f"OUTPUT/{C.MODEL_NAME}.glb", O / f"{C.MODEL_NAME}.glb", core=True)
    one(f"OUTPUT/{C.MODEL_NAME}_noveg.glb", O / f"{C.MODEL_NAME}_noveg.glb")
    core = [O / "gspro/heightmap_4097.raw", O / "gspro/greenkeeper.json"]
    for p in core:
        one("OUTPUT/gspro/" + p.name, p, core=True)
    many("OUTPUT", O, "gspro/**/*", skip=lambda p: p in core)
    many("OUTPUT", O, "maps/**/*")
    one("VIEWER/views.json", O / "views.json")  # key kept from the pre-course layout
    return out


def digest(path):
    """sha256 of the content: pixels + georeference for GeoTIFFs, arrays for .npz, bytes otherwise."""
    p = Path(path); h = hashlib.sha256(); suf = p.suffix.lower()
    if suf in (".tif", ".tiff"):
        import rasterio
        with rasterio.open(p) as ds:
            h.update(json.dumps([ds.width, ds.height, ds.count, list(ds.dtypes), ds.crs.to_string() if ds.crs else None,
                                 list(ds.transform)[:6], ds.nodata]).encode())
            for b in range(1, ds.count + 1):
                h.update(np.ascontiguousarray(ds.read(b)).tobytes())
        kind = "raster"
    elif suf == ".npz":
        with np.load(p, allow_pickle=False) as z:
            for k in sorted(z.files):
                a = np.ascontiguousarray(z[k])
                h.update(json.dumps([k, a.dtype.str, list(a.shape)]).encode()); h.update(a.tobytes())
        kind = "arrays"
    else:
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 24), b""):
                h.update(chunk)
        kind = "bytes"
    return {"sha256": h.hexdigest(), "kind": kind, "bytes": p.stat().st_size}


def gltf_stats(path):
    """Object counts of a .glb, and separate digests of its JSON and binary chunks."""
    b = Path(path).read_bytes()
    nj = struct.unpack_from("<I", b, 12)[0]; js = b[20:20 + nj]
    nb = struct.unpack_from("<I", b, 20 + nj)[0] if len(b) > 28 + nj else 0
    g = json.loads(js); acc = g.get("accessors", [])
    prims = [p for m in g.get("meshes", []) for p in m["primitives"]]
    inst = [n["extensions"]["EXT_mesh_gpu_instancing"]["attributes"]["TRANSLATION"] for n in g.get("nodes", [])
            if "EXT_mesh_gpu_instancing" in n.get("extensions", {})]
    names = Counter(re.sub(r"\d+", "#", n.get("name", "")) for n in g.get("nodes", []))
    return {k: len(g.get(k, [])) for k in ("nodes", "meshes", "materials", "textures", "images", "accessors")} | {
        "primitives": len(prims),
        "vertices": sum(acc[p["attributes"]["POSITION"]]["count"] for p in prims),
        "triangles": sum(acc[p["indices"]]["count"] // 3 for p in prims if "indices" in p and p.get("mode", 4) == 4),
        "instances": sum(acc[a]["count"] for a in inst),
        "node_names": dict(sorted(names.items())),
        "json_sha256": hashlib.sha256(js).hexdigest(),
        "bin_sha256": hashlib.sha256(b[28 + nj:28 + nj + nb]).hexdigest()}


def summarise(path):
    """A few readable numbers for the artefacts a reviewer looks at first; None for the rest."""
    p = Path(path); name = p.name
    if name.endswith(".geojson"):
        feats = json.load(open(p)).get("features", [])
        s = {"features": len(feats)}
        if any("surface" in f.get("properties", {}) for f in feats):
            from shapely.geometry import shape
            by = {}
            for f in feats:
                pr = f["properties"]; a = pr.get("area")
                if a is None and f.get("geometry"):
                    a = shape(f["geometry"]).area
                c = by.setdefault(pr.get("surface"), [0, 0.0]); c[0] += 1; c[1] += a or 0.0
            s["by_surface"] = {k: [n, round(a)] for k, (n, a) in sorted(by.items(), key=lambda kv: str(kv[0]))}
        if any("archetype" in f.get("properties", {}) for f in feats):
            s["by_archetype"] = dict(sorted(Counter(f["properties"].get("archetype") for f in feats).items()))
        return s
    if name in ("holes.json", "hole01.json"):
        d = json.load(open(p)); holes = d.get("holes", [d] if "hole" in d else [])
        return {"holes": {str(h["hole"]): [h.get("par"), {t["key"]: round(t["yards"]) for t in h.get("tees", [])}]
                          for h in holes}}
    if name == "greenkeeper.json":
        d = json.load(open(p))
        return {"holes": len(d.get("holes", [])), "tee_sets": [t.get("key") for t in d.get("tee_sets", [])]}
    if name.endswith(".raw") and "heightmap" in name:
        a = np.fromfile(p, dtype="<u2")
        return {"min": int(a.min()), "max": int(a.max()), "mean": round(float(a.mean()), 1)}
    if name.endswith(".csv"):
        return {"rows": max(0, sum(1 for _ in open(p)) - 1)}
    if name.endswith(".glb"):
        return gltf_stats(p)
    return None


def compute(arts=None):
    """{"course", "artefacts": {key: digest + summary}}; artefacts that do not exist are left out."""
    res = {}
    for a in artefacts() if arts is None else arts:
        if not a.path.is_file():
            continue
        d = digest(a.path)
        if a.core:
            d["core"] = True
        if not a.enforced:
            d["enforced"] = False
        try:
            s = summarise(a.path)
        except (ValueError, KeyError, TypeError, IndexError, struct.error) as ex:  # a broken artefact still gets a digest
            s = {"unreadable": f"{ex.__class__.__name__}: {ex}"}
        if s is not None:
            d["summary"] = s
        res[a.key] = d
    return {"course": C.MODEL_NAME, "artefacts": res}


def _machine():
    if sys.platform == "darwin":
        try:
            hw = subprocess.run(["system_profiler", "SPHardwareDataType"], capture_output=True, text=True, timeout=60).stdout
            f = dict(re.findall(r"^\s*(Model Name|Model Identifier|Chip|Processor Name): (.+)$", hw, re.M))
            return f"{f.get('Model Name', '?')} ({f.get('Model Identifier', '?')}), {f.get('Chip') or f.get('Processor Name', '?')}"
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        cpu = re.search(r"^model name\s*:\s*(.+)$", open("/proc/cpuinfo").read(), re.M)
        return cpu.group(1) if cpu else platform.processor()
    except OSError:
        return platform.processor() or platform.machine()


def _blender():
    exe = os.environ.get("BLENDER") or shutil.which("blender")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=120).stdout
        m = re.search(r"^Blender (.+)$", out, re.M)
        return m.group(1).strip() if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def environment():
    """Machine, OS and package versions: floating-point results depend on all of them."""
    from importlib import metadata
    import pyproj, rasterio
    try:
        blas = np.show_config(mode="dicts")["Build Dependencies"]["blas"]
        blas = f"{blas.get('name')} {blas.get('version', '')}".strip()
    except Exception:  # noqa: BLE001 - informational only
        blas = None
    return {"machine": _machine(), "arch": platform.machine(), "os": platform.platform(), "cpus": os.cpu_count(),
            "ram_gb": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30, 1),
            "python": platform.python_version(), "gdal": rasterio.__gdal_version__, "proj": pyproj.proj_version_str,
            "numpy_blas": blas, "blender": _blender(),
            "packages": dict(sorted((d.metadata["Name"].lower(), d.version) for d in metadata.distributions()))}


def _git():
    run = lambda *a: subprocess.run(["git", "-C", str(C.ROOT), *a], capture_output=True, text=True).stdout.strip()
    return {"commit": run("rev-parse", "HEAD"), "dirty": run("status", "--porcelain", "--untracked-files=no").splitlines()}


def _diff(a, b, pre="", out=None, limit=12):
    """Readable differences between two summaries (nested dicts / lists)."""
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in list(a) + [k for k in b if k not in a]:
            if len(out) >= limit:
                break
            if a.get(k) != b.get(k):
                _diff(a.get(k), b.get(k), f"{pre}.{k}" if pre else str(k), out, limit)
    elif a != b:
        out.append(f"{pre}: {json.dumps(a)} -> {json.dumps(b)}")
    return out


def compare(golden, current):
    """(failures, notes). A failure is an enforced artefact that changed, is missing or is new."""
    fails, notes = [], []
    g, c = golden["artefacts"], current["artefacts"]
    for k, gv in g.items():
        to = fails if gv.get("enforced", True) else notes
        if k not in c:
            to.append(f"{k}: missing")
        elif c[k]["sha256"] != gv["sha256"]:
            d = _diff(gv.get("summary"), c[k].get("summary")) if gv.get("summary") else []
            to.append(f"{k}: changed" + "".join(f"\n    {x}" for x in d))
    for k, cv in c.items():
        if k not in g:
            (fails if cv.get("enforced", True) else notes).append(f"{k}: new (not in the golden fingerprint)")
    ge, ce = golden.get("env", {}), current.get("env", {})
    for k in list(ge) + [k for k in ce if k not in ge]:
        if k == "packages":
            gp, cp = ge.get(k, {}), ce.get(k, {})
            for p in sorted(set(gp) | set(cp)):
                if gp.get(p) != cp.get(p):
                    notes.append(f"env package {p}: {gp.get(p)} -> {cp.get(p)}")
        elif ge.get(k) != ce.get(k):
            notes.append(f"env {k}: {ge.get(k)} -> {ce.get(k)}")
    return fails, notes


def report(golden, current):
    fails, notes = compare(golden, current)
    n = len(golden["artefacts"]); core = [k for k, v in golden["artefacts"].items() if v.get("core")]
    bad = {f.split(":")[0] for f in fails}
    print(f"{golden.get('course')}: {n} artefacts in the golden fingerprint ({golden.get('build', {}).get('commit', '?')[:7]})")
    print(f"core: {sum(k not in bad for k in core)}/{len(core)} match")
    for x in notes:
        print("note:", x)
    for x in fails:
        print("FAIL:", x)
    print("MATCH" if not fails else f"{len(fails)} difference(s)")
    return not fails


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "compare":
        ok = report(json.load(open(sys.argv[2])), json.load(open(sys.argv[3])))
        sys.exit(0 if ok else 1)
    path = Path(sys.argv[2]) if len(sys.argv) > 2 else GOLDEN
    fp = {"course": C.MODEL_NAME, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
          "build": _git(), "env": environment()}
    fp |= compute()
    if cmd == "write":
        path.parent.mkdir(parents=True, exist_ok=True)
        json.dump(fp, open(path, "w"), indent=1); open(path, "a").write("\n")
        print(f"wrote {path}: {len(fp['artefacts'])} artefacts")
    elif cmd == "check":
        cur = C.BUILD / "fingerprint_current.json"
        json.dump(fp, open(cur, "w"), indent=1)
        print(f"current fingerprint: {cur}")
        sys.exit(0 if report(json.load(open(path)), fp) else 1)
    else:
        sys.exit(__doc__)
