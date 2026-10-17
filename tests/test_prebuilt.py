"""Prebuilt courses: scripts/package_course.py makes a built course's viewer bundle (the files viewer/index.html loads,
and the maps) and records its checksum in courses/<slug>/prebuilt.json; scripts/get_course.py downloads that bundle,
checks it and unpacks it into output/<slug>/, so a clone can explore a course without building it. Synthetic courses
in temporary repo trees; the downloads come from a local HTTP server."""
import functools, hashlib, http.server, io, json, os, shutil, sys, tarfile, threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import get_course as G  # noqa: E402
import package_course as P  # noqa: E402

SLUG = "test-links"
VIEWER = {"viewer.json", "test_links.glb", "views.json", "holes.json", "gspro/grass_3dg.json",
          "maps/course_map.png", "maps/hole01_map.png"}


def built(root, model="test_links.glb"):
    """A repo tree with courses/<slug>/ and output/<slug>/ as a build leaves it: the viewer's files, the maps, and
    what a viewer bundle leaves out (the vegetation-free model, the GSPro package, per-hole debug files)."""
    (root / "courses" / SLUG).mkdir(parents=True)
    (root / "courses" / SLUG / "course.toml").write_text("")
    out = root / "output" / SLUG
    (out / "gspro").mkdir(parents=True)
    (out / "maps").mkdir()
    (out / "viewer.json").write_text(json.dumps({"name": "Test Links", "model": model}))
    (out / model).write_bytes(b"glTF" + bytes(range(256)) * 400)
    (out / "test_links_noveg.glb").write_bytes(b"glTF noveg")
    (out / "views.json").write_text('{"tee": {}}')
    (out / "holes.json").write_text('{"holes": []}')
    (out / "hole01.json").write_text("{}")
    (out / "gspro" / "grass_3dg.json").write_text('{"viewer": {}}')
    (out / "gspro" / "course.svg").write_text("<svg/>")
    (out / "maps" / "course_map.png").write_bytes(b"png map")
    (out / "maps" / "hole01_map.png").write_bytes(b"png hole 1")
    return out


def package(root, *extra):
    """package_course's CLI on the tree at `root`, the bundle into root/release; the manifest it wrote."""
    P.main([SLUG, "--out", str(root / "release"), "--tag", "courses-test", "--repo", "owner/repo", *extra], root=root)
    return json.loads((root / "courses" / SLUG / "prebuilt.json").read_text())


def members(path):
    with tarfile.open(path) as t:
        return {m.name for m in t.getmembers()}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def server(tmp_path):
    """A local HTTP server for files in tmp_path/served; yields its base URL."""
    d = tmp_path / "served"
    d.mkdir()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(d))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", d
    srv.shutdown()


def clone(tmp_path, manifest, url):
    """A fresh clone: courses/<slug>/prebuilt.json (pointing at `url`), and no output/."""
    root = tmp_path / "clone"
    (root / "courses" / SLUG).mkdir(parents=True)
    (root / "courses" / SLUG / "prebuilt.json").write_text(json.dumps(dict(manifest, url=url)))
    return root


@pytest.fixture(params=["requests", "curl"])
def downloader(request, monkeypatch):
    """Both download paths: requests (the build's virtualenv) and curl (a Python without requests)."""
    if request.param == "curl" and not shutil.which("curl"):
        pytest.skip("no curl")
    if request.param == "requests":
        pytest.importorskip("requests")
    monkeypatch.setattr(G, "downloader", lambda: request.param)
    return request.param


# ---------------------------------------------------------------- package_course.py

def test_bundle_holds_the_viewer_files_and_the_maps_only(tmp_path):
    built(tmp_path)
    m = package(tmp_path)
    bundle = tmp_path / "release" / f"{SLUG}-viewer.tar.gz"
    assert members(bundle) == {f"{SLUG}/{f}" for f in VIEWER}   # unpacks as output/<slug>/ with tar -C output
    assert m["sha256"] == sha(bundle) and m["bytes"] == bundle.stat().st_size
    assert m["asset"] == bundle.name and m["release"] == "courses-test"
    assert m["url"] == f"https://github.com/owner/repo/releases/download/courses-test/{bundle.name}"
    out = tmp_path / "output" / SLUG
    assert m["files"] == len(VIEWER) and m["unpacked_bytes"] == sum((out / f).stat().st_size for f in VIEWER)
    assert m["name"] == "Test Links" and m["model"] == "test_links.glb"


def test_packaging_an_unchanged_build_again_gives_the_same_checksum(tmp_path):
    built(tmp_path)
    first = package(tmp_path)["sha256"]
    (tmp_path / "release" / f"{SLUG}-viewer.tar.gz").unlink()
    assert package(tmp_path)["sha256"] == first


def test_the_model_is_the_one_viewer_json_names_else_slug_glb(tmp_path):
    """As viewer/index.html: `site.model || COURSE + '.glb'`."""
    out = built(tmp_path, model=f"{SLUG}.glb")
    (out / "viewer.json").write_text(json.dumps({"name": "Test Links"}))
    package(tmp_path)
    assert f"{SLUG}/{SLUG}.glb" in members(tmp_path / "release" / f"{SLUG}-viewer.tar.gz")


def test_a_missing_viewer_file_is_named_and_nothing_is_written(tmp_path):
    out = built(tmp_path)
    (out / "gspro" / "grass_3dg.json").unlink()
    (out / "holes.json").unlink()
    with pytest.raises(SystemExit, match=r"holes\.json.*grass_3dg\.json|grass_3dg\.json.*holes\.json"):
        package(tmp_path)
    assert not (tmp_path / "courses" / SLUG / "prebuilt.json").exists()
    assert not (tmp_path / "release").exists() or not any((tmp_path / "release").iterdir())


def test_an_unknown_course_is_refused(tmp_path):
    built(tmp_path)
    with pytest.raises(SystemExit, match="no-such-course"):
        P.main(["no-such-course", "--out", str(tmp_path / "release")], root=tmp_path)


def test_repackaging_keeps_the_hand_written_attribution(tmp_path):
    """The credit the data need is written into prebuilt.json by hand; a new bundle keeps it."""
    built(tmp_path)
    package(tmp_path)
    p = tmp_path / "courses" / SLUG / "prebuilt.json"
    p.write_text(json.dumps(dict(json.loads(p.read_text()), attribution="Contains open data")))
    (tmp_path / "output" / SLUG / "holes.json").write_text('{"holes": [1]}')
    m = package(tmp_path)
    assert m["attribution"] == "Contains open data" and m["sha256"] == sha(tmp_path / "release" / m["asset"])


# ---------------------------------------------------------------- get_course.py

def test_get_course_downloads_checks_and_unpacks_into_output(tmp_path, server, downloader, capsys):
    out = built(tmp_path)
    m = package(tmp_path)
    base, served = server
    shutil.copy(tmp_path / "release" / m["asset"], served / m["asset"])
    root = clone(tmp_path, m, f"{base}/{m['asset']}")

    G.main([SLUG], root=root)

    got = root / "output" / SLUG
    files = {p.relative_to(got).as_posix() for p in got.rglob("*") if p.is_file()}
    assert files == VIEWER | {"prebuilt.json"}
    assert all((got / f).read_bytes() == (out / f).read_bytes() for f in VIEWER)
    assert json.loads((got / "prebuilt.json").read_text())["sha256"] == m["sha256"]
    assert not list(root.rglob("*.tar.gz*"))   # the downloaded archive is deleted once unpacked
    said = capsys.readouterr().out
    assert "python3 scripts/devserver.py 8765" in said
    assert f"http://localhost:8765/viewer/?course={SLUG}" in said


def test_a_bundle_that_does_not_match_the_checksum_installs_nothing(tmp_path, server, downloader):
    built(tmp_path)
    m = package(tmp_path)
    base, served = server
    shutil.copy(tmp_path / "release" / m["asset"], served / m["asset"])
    root = clone(tmp_path, dict(m, sha256="0" * 64), f"{base}/{m['asset']}")
    with pytest.raises(SystemExit, match="sha256"):
        G.main([SLUG], root=root)
    assert not (root / "output" / SLUG).exists()
    assert not [p for p in root.rglob("*") if p.is_file() and p.name != "prebuilt.json"]   # the download is deleted


def test_a_bundle_not_published_yet_says_so(tmp_path, server, downloader):
    built(tmp_path)
    m = package(tmp_path)
    base, _ = server
    root = clone(tmp_path, m, f"{base}/{m['asset']}")   # not on the server: 404
    with pytest.raises(SystemExit, match="not published"):
        G.main([SLUG], root=root)
    assert not (root / "output" / SLUG).exists()


def test_a_local_build_is_never_overwritten(tmp_path):
    built(tmp_path)
    m = package(tmp_path)
    root = clone(tmp_path, m, "http://127.0.0.1:9/unused")
    mine = root / "output" / SLUG / "viewer.json"
    mine.parent.mkdir(parents=True)
    mine.write_text("my build")
    with pytest.raises(SystemExit, match="local build"):
        G.main([SLUG, "--file", str(tmp_path / "release" / m["asset"])], root=root)
    assert mine.read_text() == "my build"


def test_an_installed_bundle_is_not_fetched_again(tmp_path, capsys):
    built(tmp_path)
    m = package(tmp_path)
    root = clone(tmp_path, m, "http://127.0.0.1:9/unused")   # nothing listens: a download would fail
    G.main([SLUG, "--file", str(tmp_path / "release" / m["asset"])], root=root)
    capsys.readouterr()
    G.main([SLUG], root=root)
    assert "already" in capsys.readouterr().out


def test_a_damaged_install_is_fetched_again(tmp_path, server, downloader):
    built(tmp_path)
    m = package(tmp_path)
    base, served = server
    shutil.copy(tmp_path / "release" / m["asset"], served / m["asset"])
    root = clone(tmp_path, m, f"{base}/{m['asset']}")
    G.main([SLUG], root=root)
    (root / "output" / SLUG / "holes.json").unlink()
    G.main([SLUG], root=root)
    assert (root / "output" / SLUG / "holes.json").read_text() == '{"holes": []}'


def test_a_new_bundle_replaces_the_old_prebuilt_one(tmp_path):
    out = built(tmp_path)
    old = package(tmp_path)
    shutil.move(str(tmp_path / "release" / old["asset"]), str(tmp_path / "old.tar.gz"))
    root = clone(tmp_path, old, "http://127.0.0.1:9/unused")
    G.main([SLUG, "--file", str(tmp_path / "old.tar.gz")], root=root)

    (out / "maps" / "hole01_map.png").unlink()               # the rebuilt course: one map fewer, a new model
    (out / "test_links.glb").write_bytes(b"glTF rebuilt")
    new = package(tmp_path)
    (root / "courses" / SLUG / "prebuilt.json").write_text(json.dumps(new))
    G.main([SLUG, "--file", str(tmp_path / "release" / new["asset"])], root=root)

    got = root / "output" / SLUG
    assert (got / "test_links.glb").read_bytes() == b"glTF rebuilt"
    assert not (got / "maps" / "hole01_map.png").exists()
    assert not [p.name for p in (root / "output").iterdir() if p.name != SLUG]   # no temporary folders left


def test_a_bundle_on_disk_must_match_the_checksum_and_is_kept(tmp_path):
    built(tmp_path)
    m = package(tmp_path)
    bundle = tmp_path / "release" / m["asset"]
    root = clone(tmp_path, dict(m, sha256="0" * 64), "http://127.0.0.1:9/unused")
    with pytest.raises(SystemExit, match="sha256"):
        G.main([SLUG, "--file", str(bundle)], root=root)
    assert bundle.exists() and not (root / "output" / SLUG).exists()


def test_an_archive_reaching_outside_its_course_folder_is_refused(tmp_path):
    """Even with a matching checksum (a manifest and an archive made together): only <slug>/... files unpack."""
    for bad in ("../evil.txt", f"{SLUG}/../../evil.txt", "/tmp/evil.txt", "other-course/viewer.json"):
        archive = tmp_path / "bad.tar.gz"
        with tarfile.open(archive, "w:gz") as t:
            info = tarfile.TarInfo(bad)
            info.size = 4
            t.addfile(info, io.BytesIO(b"evil"))
        m = {"course": SLUG, "asset": archive.name, "url": "http://127.0.0.1:9/unused", "sha256": sha(archive),
             "bytes": archive.stat().st_size}
        root = tmp_path / "clone"
        shutil.rmtree(root, ignore_errors=True)
        (root / "courses" / SLUG).mkdir(parents=True)
        (root / "courses" / SLUG / "prebuilt.json").write_text(json.dumps(m))
        with pytest.raises(SystemExit, match="unexpected"):
            G.main([SLUG, "--file", str(archive)], root=root)
        assert not list(tmp_path.rglob("evil.txt")) and not (root / "output" / SLUG).exists()


def test_a_link_in_the_archive_is_refused(tmp_path):
    archive = tmp_path / "link.tar.gz"
    with tarfile.open(archive, "w:gz") as t:
        info = tarfile.TarInfo(f"{SLUG}/viewer.json")
        info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
        t.addfile(info)
    m = {"course": SLUG, "asset": archive.name, "url": "http://127.0.0.1:9/unused", "sha256": sha(archive),
         "bytes": archive.stat().st_size}
    root = tmp_path / "clone"
    (root / "courses" / SLUG).mkdir(parents=True)
    (root / "courses" / SLUG / "prebuilt.json").write_text(json.dumps(m))
    with pytest.raises(SystemExit, match="unexpected"):
        G.main([SLUG, "--file", str(archive)], root=root)
    assert not (root / "output" / SLUG).exists()


def test_a_course_without_a_bundle_lists_the_ones_that_have_one(tmp_path):
    built(tmp_path)
    package(tmp_path)
    (tmp_path / "courses" / "no-bundle").mkdir()
    (tmp_path / "courses" / "no-bundle" / "course.toml").write_text("")
    with pytest.raises(SystemExit, match=f"no prebuilt bundle.*{SLUG}"):
        G.main(["no-bundle"], root=tmp_path)
    with pytest.raises(SystemExit, match=f"no course.*{SLUG}"):
        G.main(["nowhere"], root=tmp_path)


def test_list_shows_each_prebuilt_course(tmp_path, capsys):
    built(tmp_path)
    package(tmp_path)
    G.main(["--list"], root=tmp_path)
    said = capsys.readouterr().out
    assert SLUG in said and "Test Links" in said
