"""Unit tests for the procedural tree models (make_trees): variant spread and foliage colour."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import make_trees as M  # noqa: E402


def test_variants_differ_in_shape_not_just_seed():
    """Three seed-only variants per species made crowns of one species look cloned: five variants with their own
    proportions, crown base, lean and card size, all within plausible bounds."""
    assert M.N_VARIANTS >= 5
    for name, base in M.ARCH.items():
        ps = [M.variant_params(name, v) for v in range(M.N_VARIANTS)]
        aspect = np.array([p["H"] / p["R"] for p in ps])
        assert np.ptp(aspect) / aspect.mean() > 0.15, name
        assert len({round(p["crown"][1], 3) for p in ps}) >= 3, name
        for p in ps:
            assert 0.75 * base["H"] <= p["H"] <= 1.25 * base["H"] and 0.7 * base["R"] <= p["R"] <= 1.3 * base["R"]
            assert 0.0 <= p["crown"][1] < p["crown"][2] <= 1.0
            assert p["card"][0] < p["card"][1]


def test_foliage_cards_vary_in_hue(tmp_path, monkeypatch):
    """Grey-only card AO made every crown one flat green: each card carries a small yellow / blue-green shift."""
    monkeypatch.setattr(M, "OUT", tmp_path)
    M.build("shrub", 1, "lo")
    d = np.load(tmp_path / "shrub_v1_lo.npz")
    c = d["leaf_c"].reshape(-1, 4, 3)[:, 0]                      # one colour per card
    warm = c[:, 0] / np.maximum(c[:, 2], 1e-6)
    assert warm.std() > 0.04 and 0.8 < np.median(warm) < 1.2
