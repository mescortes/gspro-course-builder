"""build_all.py and measure_registration.py: a newcomer's wrong step name, missing Blender or white-sand course used to
be a bare traceback, the Blender one after an hour of steps (no data, nothing is built: subprocess is stubbed)."""
import sys
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
    monkeypatch.setattr(B.subprocess, "run", lambda cmd, **k: runs.append(cmd))
    monkeypatch.setattr(B, "find_blender", lambda: None)
    with pytest.raises(SystemExit) as e:
        B.main([])
    assert runs == [] and "BLENDER" in str(e.value) and "register prefabs" in str(e.value)
    B.main(["maps", "views"])                                        # no Blender needed after the fbx step
    assert [Path(c[1]).name for c in runs] == ["make_maps.py", "make_views.py"]


def test_registration_with_too_few_bunkers_says_so_and_prints_the_shift_to_paste():
    """No bunker passing the sand gate (white sand) crashed with IndexError: too many indices for array."""
    import measure_registration as M
    core = dict(xmin=0.0, ymin=0.0, xmax=100.0, ymax=100.0)
    lines, shift = M.bunker_shift(np.zeros((0, 5)), core, (0.0, -0.25))
    assert shift is None and any("registration_sand" in l and "3" in l for l in lines)
    A = np.array([[10.0, 10.0, 0.5, 0.25, 1.3], [80.0, 20.0, 0.5, 0.25, 1.2], [20.0, 80.0, 0.25, 0.5, 1.4],
                  [70.0, 70.0, 0.5, 0.25, 1.1]])
    lines, shift = M.bunker_shift(A, core, (0.0, -0.25))       # the registered photo is measured: shifts add up
    assert shift == (0.5, 0.0) and any(l.startswith("shift = [0.50, 0.00]") for l in lines)
