"""config.py on a fresh clone (build/ and output/ are git-ignored, so they don't exist yet)."""
import os, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_config_creates_the_build_and_output_dirs(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/config.py", tmp_path / "scripts/config.py")
    env = dict(os.environ, MG_PROFILE="course")
    subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); import config"], cwd=tmp_path,
                   env=env, check=True)
    assert (tmp_path / "build").is_dir() and (tmp_path / "output").is_dir()
