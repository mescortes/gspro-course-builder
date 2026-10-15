"""The GSPro terrain size (export_gspro): Unity 2018 takes heightmaps of at most 4097 x 4097 samples."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import export_gspro as X  # noqa: E402


def test_the_heightmap_never_exceeds_4097_samples_a_side():
    """Any terrain over 2048 m made an 8193^2 heightmap at 0.5 m, which Unity 2018 cannot import (its largest
    heightmapResolution is 4097). A wider terrain keeps 4097 samples at a coarser spacing (terrain.json
    sample_spacing_m); smaller ones keep 0.5 m."""
    assert X.heightmap_resolution(2048.0) == 4097 and X.N == 4097          # Westmount: 0.5 m
    assert X.heightmap_resolution(640.0) == 2049                           # Westmount's test profile
    for size in (2049.0, 2560.0, 3072.0, 4096.0, 6000.0):
        assert X.heightmap_resolution(size) == 4097, size
    assert 4096.0 / (X.heightmap_resolution(4096.0) - 1) == 1.0
