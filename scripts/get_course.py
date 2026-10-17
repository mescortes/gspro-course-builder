"""Fetch a prebuilt course to explore in the viewer, without building it: downloads the course's viewer bundle (the
files viewer/index.html loads, and the yardage-book maps; scripts/package_course.py makes it) from this repository's
GitHub Release, checks it against the sha256 in courses/<slug>/prebuilt.json, and unpacks it into output/<slug>/.

  python3 scripts/get_course.py <slug>         # --list: the courses there are bundles of
  python3 scripts/devserver.py 8765            # then open the viewer URL it prints

It needs only Python 3.9 or newer and requests or curl, not the build's virtualenv. --file <bundle> installs a bundle
already on disk (checked the same way). A course already in output/<slug>/ from a bundle is replaced only by a
different bundle; a course built here (output/<slug>/ without prebuilt.json) is never touched. The download is
deleted once unpacked (--keep keeps it in data/<slug>/); an interrupted one resumes on a rerun."""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))   # sources/http.py (requests), when it is installed
PORT = 8765
MARKER = "prebuilt.json"   # output/<slug>/prebuilt.json: the manifest of the bundle unpacked there, and its files


def manifests(root):
    """{slug: manifest} of the courses with a prebuilt bundle (courses/<slug>/prebuilt.json)."""
    return {p.parent.name: json.loads(p.read_text()) for p in sorted((root / "courses").glob("*/prebuilt.json"))}


def load(root, slug):
    known = manifests(root)
    if slug in known:
        return known[slug]
    have = ", ".join(known) or "none yet"
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug) or not (root / "courses" / slug).is_dir():
        sys.exit(f"no course {slug}. Courses with a prebuilt bundle: {have}")
    sys.exit(f"no prebuilt bundle for {slug} (courses/{slug}/prebuilt.json): build it (README.md, 'Building a "
             f"course'). Courses with a prebuilt bundle: {have}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def downloader():
    """'requests' when it is installed (the build's virtualenv), else 'curl'."""
    try:
        import requests  # noqa: F401
        return "requests"
    except ImportError:
        return "curl"


def unpublished(m):
    return (f"the {m['course']} bundle is not published yet ({m['url']} is not there): the release "
            f"{m.get('release', '')} has not been made. Build the course instead (README.md, 'Building a course').")


def fetch(m, dst):
    """The bundle at m['url'] into `dst`, through <dst>.part (resumed on a rerun), checked for m['bytes'] bytes."""
    size = m.get("bytes")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if downloader() == "requests":
        from sources.http import PermanentError, download
        try:
            download(m["url"], dst, size=size)
        except PermanentError as ex:
            sys.exit(unpublished(m) if ex.missing else str(ex))
        except RuntimeError as ex:
            sys.exit(str(ex))
        return
    if dst.exists() and dst.stat().st_size == size:
        return
    if not shutil.which("curl"):
        sys.exit("downloading needs requests (pip install requests) or curl")
    tmp = dst.with_name(dst.name + ".part")
    if size is not None and tmp.exists() and tmp.stat().st_size >= size:
        tmp.unlink()   # whole or larger: start again rather than ask for a range past the end
    print("downloading", dst.name, round((size or 0) / 1e6), "MB", flush=True)
    r = subprocess.run(["curl", "--fail", "--location", "--retry", "5", "--retry-delay", "10", "--continue-at", "-",
                        "--output", str(tmp), m["url"]])
    if r.returncode == 22 and (not tmp.exists() or tmp.stat().st_size == 0):   # an HTTP error, nothing received
        tmp.unlink(missing_ok=True)
        sys.exit(unpublished(m) + " (or the server refused it: rerun to retry)")
    if r.returncode != 0:
        sys.exit(f"download failed (curl exit {r.returncode}): {m['url']} (rerun to resume from {tmp})")
    if size is not None and tmp.stat().st_size != size:
        sys.exit(f"download incomplete: {tmp.stat().st_size} of {size} bytes from {m['url']} (rerun to resume)")
    os.replace(tmp, dst)


def contents(archive, slug):
    """{path: size} of the files in the archive, below <slug>/. Exits on anything else: a link, a device, a path
    outside <slug>/ (absolute, '..', another course)."""
    files = {}
    with tarfile.open(archive) as t:
        for e in t.getmembers():
            p = PurePosixPath(e.name)
            if p.is_absolute() or ".." in p.parts or len(p.parts) < 2 or p.parts[0] != slug \
                    or not (e.isfile() or e.isdir()):
                sys.exit(f"{archive.name}: unexpected entry {e.name!r} (a bundle holds files below {slug}/ only)")
            if e.isfile():
                files[PurePosixPath(*p.parts[1:]).as_posix()] = e.size
    return files


def intact(dest, m):
    """True when output/<slug>/ holds the bundle `m` describes, with every file it unpacked."""
    try:
        had = json.loads((dest / MARKER).read_text())
    except (OSError, ValueError):
        return False
    return had.get("sha256") == m["sha256"] and all(
        (dest / f).is_file() and (dest / f).stat().st_size == n for f, n in had.get("contents", {}).items())


def unpack(archive, m, out):
    """The checked `archive` into out/<slug>/, through a folder beside it renamed into place at the end, so an
    interrupted unpack never leaves a half course the viewer would load. Writes the marker last."""
    slug = m["course"]
    files = contents(archive, slug)
    stage, old = out / f".{slug}.unpack", out / f".{slug}.old"
    for d in (stage, old):
        shutil.rmtree(d, ignore_errors=True)
    stage.mkdir(parents=True)
    with tarfile.open(archive) as t:
        if hasattr(tarfile, "data_filter"):   # Python 3.12+ (and 3.9.17+ / 3.10.12+ / 3.11.4+)
            t.extractall(stage, filter="data")
        else:                                 # contents() has refused links and paths outside <slug>/
            t.extractall(stage)
    dest = out / slug
    if dest.exists():
        os.replace(dest, old)
    os.replace(stage / slug, dest)
    shutil.rmtree(old, ignore_errors=True)
    shutil.rmtree(stage, ignore_errors=True)
    (dest / MARKER).write_text(json.dumps(dict(m, contents=files), indent=1) + "\n")


def install(root, m, file=None, keep=False):
    """Course m['course'] into root/output/<slug>/ from the release (or the bundle at `file`)."""
    slug = m["course"]
    dest = root / "output" / slug
    if intact(dest, m):
        print(f"{m.get('name', slug)} is already in output/{slug}/ (bundle {m['sha256'][:12]})")
        return
    if dest.exists() and any(dest.iterdir()) and not (dest / MARKER).exists():
        sys.exit(f"{slug}: output/{slug}/ holds a local build (no {MARKER}), which is left alone. To explore the "
                 f"prebuilt one instead, move it away first (mv output/{slug} output/{slug}.local)")
    archive = Path(file) if file else root / "data" / slug / m["asset"]
    if not file:
        fetch(m, archive)
    if m.get("bytes") is not None and archive.stat().st_size != m["bytes"]:
        bad = f"{archive}: {archive.stat().st_size} bytes, courses/{slug}/prebuilt.json says {m['bytes']}"
        if not file:
            archive.unlink()
        sys.exit(bad + " (the sha256 cannot match)")
    got = sha256(archive)
    if got != m["sha256"]:
        if not file:
            archive.unlink()   # a rerun downloads it again
        sys.exit(f"{archive.name}: sha256 {got} does not match courses/{slug}/prebuilt.json ({m['sha256']})")
    unpack(archive, m, root / "output")
    if not file and not keep:
        archive.unlink()
        try:
            archive.parent.rmdir()   # data/<slug>/, when the bundle was all there was
        except OSError:
            pass


def main(argv=None, root=ROOT):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug", nargs="?", help="the course (courses/<slug>/); --list shows them")
    ap.add_argument("--list", action="store_true", help="the courses there are prebuilt bundles of")
    ap.add_argument("--file", help="install this bundle (a .tar.gz on disk) instead of downloading it")
    ap.add_argument("--keep", action="store_true", help="keep the downloaded bundle in data/<slug>/")
    a = ap.parse_args(argv)
    if a.list or not a.slug:
        for slug, m in manifests(root).items():
            there = " (in output/)" if intact(root / "output" / slug, m) else ""
            print(f"{slug:16} {m.get('name', slug):36} {m['bytes'] / 1e6:6.0f} MB  release {m.get('release')}{there}")
        if not a.list:
            ap.print_usage()
        return
    m = load(root, a.slug)
    install(root, m, a.file, a.keep)
    print(f"\nTo explore {m.get('name', a.slug)}, start the viewer's server from the repository root:\n"
          f"  python3 scripts/devserver.py {PORT}\n"
          f"and open http://localhost:{PORT}/viewer/?course={a.slug}#h1-tee")
    if m.get("attribution"):
        print(f"\nData: {m['attribution']}")


if __name__ == "__main__":
    main()
