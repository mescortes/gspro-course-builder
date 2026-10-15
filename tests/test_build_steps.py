"""build_all.py and measure_registration.py: a newcomer's wrong step name, missing Blender or white-sand course used to
be a bare traceback, the Blender one after an hour of steps (no data, nothing is built: subprocess is stubbed)."""
import os, sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_an_unknown_build_step_lists_the_step_names():
    """build_all.py surfaces export was a bare "ValueError: 'surfaces' is not in list"."""
    import build_all as B
    names = [n for n, _ in B.STEPS]
    assert B.step_range([]) == (0, len(names) - 1) and B.step_range(["mesh"]) == (names.index("mesh"), len(names) - 1)
    assert B.step_range(["register", "mesh"]) == (0, names.index("mesh"))
    for args in (["surfaces", "export"], ["register", "exports"], ["mesh", "register"]):
        with pytest.raises(SystemExit) as e:
            B.step_range(args)
        assert "register" in str(e.value) and "views" in str(e.value), args
    with pytest.raises(SystemExit) as e:
        B.step_range(["--list"])
    assert e.value.code in (0, None)


def test_a_missing_blender_stops_the_build_before_the_first_step(monkeypatch, tmp_path):
    """Blender not on PATH failed at step 18 of 20, after an hour of steps, and maps / views never ran."""
    import build_all as B
    find = B.find_blender
    exe = tmp_path / "blender"; exe.write_text("#!/bin/sh\n"); exe.chmod(0o755)
    assert find(env={"BLENDER": str(exe)}, which=lambda n: None, defaults=()) == str(exe)
    assert find(env={}, which=lambda n: None, defaults=(str(exe),)) == str(exe)      # e.g. /Applications/Blender.app
    assert find(env={}, which=lambda n: None, defaults=(str(tmp_path / "none"),)) is None
    with pytest.raises(SystemExit, match="BLENDER"):
        find(env={"BLENDER": str(tmp_path / "none")}, which=lambda n: None, defaults=())
    runs = []
    monkeypatch.setattr(B, "run", lambda cmd, **k: runs.append(cmd))
    monkeypatch.setattr(B, "find_blender", lambda: None)
    with pytest.raises(SystemExit) as e:
        B.main([])
    assert runs == [] and "BLENDER" in str(e.value) and "register prefabs" in str(e.value)
    B.main(["maps", "views"])                                        # no Blender needed after the fbx step
    assert [Path(c[1]).name for c in runs] == ["make_maps.py", "make_views.py"]


def test_each_step_reports_its_peak_memory(monkeypatch, capsys):
    """docs/PLAYBOOK.md promised each step's peak memory (16 GB, a Claude cloud session, is at the edge for an 18-hole
    build), but build_all printed only the time. Each step runs as a child whose own rusage (os.wait4) gives its peak:
    getrusage(RUSAGE_CHILDREN) grows only when a step sets a new maximum."""
    import subprocess
    import build_all as B
    if not hasattr(os, "wait4"):
        pytest.skip("no os.wait4 (Windows): the build prints the times only")
    peak = B.run([sys.executable, "-c", "b = b'x' * (400 * 2 ** 20)"])
    assert 0.35 < peak < 2.0, peak
    with pytest.raises(subprocess.CalledProcessError):
        B.run([sys.executable, "-c", "raise SystemExit(3)"])
    peaks = iter([1.52, 6.31])
    monkeypatch.setattr(B, "run", lambda cmd, **k: next(peaks))
    B.main(["maps", "views"])
    out = capsys.readouterr().out
    assert "maps done in" in out and "peak memory 1.5 GB" in out and "peak memory 6.3 GB" in out
    assert out.strip().splitlines()[-1] == "peak memory 6.3 GB (views)"
    monkeypatch.setattr(B, "run", lambda cmd, **k: None)                 # no wait4: times only
    B.main(["maps", "views"])
    assert "peak" not in capsys.readouterr().out


def _fake_blender_app(tmp_path, version):
    import plistlib
    app = tmp_path / "Blender.app/Contents"
    (app / "MacOS").mkdir(parents=True)
    exe = app / "MacOS/Blender"; exe.write_text("#!/bin/sh\n"); exe.chmod(0o755)   # prints no version when started
    with open(app / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleShortVersionString": version}, f)
    return str(exe)


def test_the_build_says_which_blender_it_uses_and_warns_on_another_version(monkeypatch, tmp_path, capsys):
    """find_blender falls back to /Applications/Blender.app: a Mac with Blender 4.5 there built the FBX with another
    exporter without a word, and fingerprint.py, which looked only at BLENDER and PATH, recorded no Blender at all.
    The version is read without starting Blender (a sandboxed macOS shell crashes it at start)."""
    import build_all as B, fingerprint as FP
    exe = _fake_blender_app(tmp_path, "4.5.3")
    assert B.blender_version(exe) == "4.5.3"
    assert B.blender_version("C:/Program Files/Blender Foundation/Blender 4.2/blender.exe") == "4.2"
    assert B.blender_version("/opt/blender-4.2.23-linux-x64/blender") == "4.2.23"
    assert B.blender_version("/usr/bin/blender") is None
    note = B.blender_note(exe)
    assert note.startswith("!!") and exe in note and "4.5.3" in note and "4.2 LTS" in note and "BLENDER" in note
    assert not B.blender_note("/opt/blender-4.2.23-linux-x64/blender").startswith("!!")
    assert "version" in B.blender_note("/usr/bin/blender") and not B.blender_note("/usr/bin/blender").startswith("!!")
    monkeypatch.setattr(B, "run", lambda cmd, **k: None)
    monkeypatch.setattr(B, "find_blender", lambda: exe)
    B.main(["fbx", "fbx"])
    out = capsys.readouterr().out
    assert out.index("4.5.3") < out.index("== fbx")                       # said before the first step
    assert FP._blender() == "4.5.3"                                        # the program the build uses
    monkeypatch.setattr(B, "find_blender", lambda: sys.exit("BLENDER=/x is not a program"))
    assert FP._blender() is None


def test_registration_with_too_few_bunkers_says_so_and_prints_the_shift_to_paste():
    """No bunker passing the sand gate (white sand) crashed with IndexError: too many indices for array."""
    import measure_registration as M
    core = dict(xmin=0.0, ymin=0.0, xmax=100.0, ymax=100.0)
    lines, shift = M.bunker_shift(np.zeros((0, 5)), core, (0.0, -0.25))
    assert shift is None and any("[tuning.sand]" in l and "3" in l for l in lines)
    A = np.array([[10.0, 10.0, 0.5, 0.25, 1.3], [80.0, 20.0, 0.5, 0.25, 1.2], [20.0, 80.0, 0.25, 0.5, 1.4],
                  [70.0, 70.0, 0.5, 0.25, 1.1]])
    lines, shift = M.bunker_shift(A, core, (0.0, -0.25))       # the registered photo is measured: shifts add up
    assert shift == (0.5, 0.0) and any(l.startswith("shift = [0.50, 0.00]") for l in lines)
