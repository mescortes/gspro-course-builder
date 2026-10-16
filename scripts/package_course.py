"""Package a built course for scripts/get_course.py: its viewer bundle, the files viewer/index.html loads from
output/<slug>/ (viewer.json, the model it names, views.json, holes.json, gspro/grass_3dg.json) and the yardage-book
maps (maps/), as <slug>-viewer.tar.gz, with its checksum in courses/<slug>/prebuilt.json.

  python3 scripts/package_course.py <slug>            # output/<slug>/ -> build/<slug>/<slug>-viewer.tar.gz
      [--from DIR] [--out DIR] [--tag courses-YYYY-MM-DD] [--repo owner/name] [--built-from COMMIT]

The archive unpacks as <slug>/... (`tar -xzf <slug>-viewer.tar.gz -C output`). It is reproducible: the same files, with
the same modification times, give the same bytes, so packaging an unchanged build again gives the same checksum, and a
rebuilt course is packaged with the same command. prebuilt.json names the GitHub Release asset the bundle is published
as (`--tag`, default courses-<today>; one release can hold every course's bundle). Its `attribution` (the credit the
course's data need, written by hand) is kept when the bundle is made again. Nothing is uploaded: publishing the release
is the owner's step, and the command for it is printed."""
import argparse, datetime, gzip, hashlib, json, os, re, subprocess, sys, tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "mescortes/gspro-course-builder"
REQUIRED = ("viewer.json", "views.json", "holes.json", "gspro/grass_3dg.json")   # and the model viewer.json names


def bundle_files(src, slug):
    """(paths, model): the viewer's files in `src`, the output folder of course `slug` (relative, '/'-separated, the
    maps last), and the model's name. Exits naming every file the viewer needs that the build has not made."""
    model = None
    if (src / "viewer.json").exists():
        model = json.loads((src / "viewer.json").read_text()).get("model")
    model = model or f"{slug}.glb"
    files = list(REQUIRED) + [model]
    missing = [f for f in files if not (src / f).is_file()]
    if missing:
        sys.exit(f"{src}: no {', '.join(missing)} (build the course first: scripts/build_all.py)")
    maps = sorted(p.relative_to(src).as_posix() for p in (src / "maps").glob("*") if p.is_file()) \
        if (src / "maps").is_dir() else []
    return sorted(files) + maps, model


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_bundle(src, slug, files, dst):
    """`files` of `src` into the gzipped tar `dst` as <slug>/<file>, written through <dst>.part. Only what a file holds
    and its modification time reach the archive (no owner, no gzip timestamp), so the same files give the same bytes."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    with open(tmp, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as gz, \
            tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for rel in files:
            p = src / rel
            st = p.stat()
            info = tarfile.TarInfo(f"{slug}/{rel}")
            info.size, info.mtime, info.mode = st.st_size, int(st.st_mtime), 0o644
            with open(p, "rb") as f:
                tar.addfile(info, f)
    os.replace(tmp, dst)


def checkout_commit(path):
    """The commit checked out where `path` lives (the engine that built it, if the checkout has not moved since);
    None outside a git checkout."""
    try:
        r = subprocess.run(["git", "-C", str(path), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True)
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def package(slug, src, out, manifest_path, tag, repo, built_from=None, today=None):
    """Bundle `src` (course `slug`'s output folder) into `out` and write the manifest; returns the manifest."""
    files, model = bundle_files(src, slug)
    asset = f"{slug}-viewer.tar.gz"
    bundle = out / asset
    write_bundle(src, slug, files, bundle)
    old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    viewer = json.loads((src / "viewer.json").read_text())
    m = {
        "course": slug,
        "name": viewer.get("name") or viewer.get("title") or slug,
        "release": tag,
        "asset": asset,
        "url": f"https://github.com/{repo}/releases/download/{tag}/{asset}",
        "sha256": sha256(bundle),
        "bytes": bundle.stat().st_size,
        "files": len(files),
        "unpacked_bytes": sum((src / f).stat().st_size for f in files),
        "model": model,
        "packaged": (today or datetime.date.today()).isoformat(),
    }
    if built_from:
        m["built_from"] = built_from
    if old.get("attribution"):
        m["attribution"] = old["attribution"]
    manifest_path.write_text(json.dumps(m, indent=1) + "\n")
    return m


def main(argv=None, root=ROOT):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug", help="the course folder (courses/<slug>/)")
    ap.add_argument("--from", dest="src", type=Path, help="the built course (default output/<slug>/)")
    ap.add_argument("--out", type=Path, help="where the bundle goes (default build/<slug>/)")
    ap.add_argument("--tag", default=f"courses-{datetime.date.today().isoformat()}",
                    help="the GitHub Release the bundle is published in (default courses-<today>)")
    ap.add_argument("--repo", default=REPO, help=f"the GitHub repository (default {REPO})")
    ap.add_argument("--built-from", help="the engine commit that built it (default: the commit checked out at --from)")
    a = ap.parse_args(argv)
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", a.slug) or not (root / "courses" / a.slug / "course.toml").exists():
        sys.exit(f"no course {a.slug}: courses/{a.slug}/course.toml does not exist")
    src = a.src or root / "output" / a.slug
    out = a.out or root / "build" / a.slug
    manifest_path = root / "courses" / a.slug / "prebuilt.json"
    m = package(a.slug, src, out, manifest_path, a.tag, a.repo, a.built_from or checkout_commit(src))
    bundle = out / m["asset"]
    print(f"{bundle}  {m['bytes'] / 1e6:.1f} MB ({m['files']} files, {m['unpacked_bytes'] / 1e6:.1f} MB unpacked)")
    print(f"sha256 {m['sha256']}")
    print(f"wrote {manifest_path.relative_to(root)}" if manifest_path.is_relative_to(root) else f"wrote {manifest_path}")
    if not m.get("attribution"):
        print(f"courses/{a.slug}/prebuilt.json has no attribution: add the credit its data need (the course README)")
    print("\nNothing is uploaded. To publish it (the release once, then each course's bundle):")
    print(f"  gh release create {a.tag} --repo {a.repo} --title 'Prebuilt courses {a.tag}' --notes-file <notes.md>")
    print(f"  gh release upload {a.tag} --repo {a.repo} --clobber {bundle}")


if __name__ == "__main__":
    main()
