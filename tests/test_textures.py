"""make_textures.py: the procedural turf textures are the same on every build (synthetic, scaled down)."""
import os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RUN = """
import sys; from pathlib import Path
sys.path.insert(0, {scripts!r})
import make_textures as M
M.N = 96; M.OUT = Path({out!r})
M.SPECS = {{"green": dict(M.SPECS["green"], blades=3000)}}
M.make("green")
"""


def test_turf_textures_do_not_depend_on_the_process_hash_seed(tmp_path):
    """The texture seed came from hash(name), which Python salts per process: every build drew different turf, so
    the glTF never rebuilt byte for byte."""
    for seed in ("1", "2"):
        code = RUN.format(scripts=str(ROOT / "scripts"), out=str(tmp_path / seed))
        subprocess.run([sys.executable, "-c", code], check=True, capture_output=True,
                       env=dict(os.environ, PYTHONHASHSEED=seed))
    for f in ("albedo.jpg", "normal.png", "orm.jpg"):
        assert (tmp_path / "1/green" / f).read_bytes() == (tmp_path / "2/green" / f).read_bytes(), f
