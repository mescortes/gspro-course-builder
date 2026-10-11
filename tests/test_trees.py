"""Unit tests for LiDAR tree detection on synthetic canopy height models (leaf-off speckle) and archetype rules."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import detect_trees as D  # noqa: E402

RES = 0.5


def dome(n, cy, cx, radius_m, height, rng, holes=0.0):
    yy, xx = np.mgrid[:n, :n]
    d = np.hypot(yy - cy, xx - cx) * RES
    z = np.where(d < radius_m, height * np.sqrt(np.clip(1 - (d / radius_m) ** 2, 0, 1)) ** 0.6, 0.0)
    if holes:
        z = np.where(rng.random(z.shape) < holes, 0.0, z)   # leaf-off: many first returns reach the ground
    return z.astype(np.float32)


def test_one_big_leaf_off_crown_is_one_tree():
    rng = np.random.default_rng(1)
    chm = dome(120, 60, 60, 7.0, 21.0, rng, holes=0.45)
    tops, lab = D.segment_crowns(chm, RES, leaf_off=True)
    assert len(tops[0]) == 1, f"{len(tops[0])} tops for one crown"
    area = (lab == 1).sum() * RES * RES
    assert 0.7 * np.pi * 7 ** 2 < area < 1.3 * np.pi * 7 ** 2


def test_two_neighbouring_crowns_stay_two():
    rng = np.random.default_rng(2)
    chm = np.maximum(dome(140, 70, 40, 6.0, 18.0, rng, 0.3), dome(140, 70, 100, 6.0, 20.0, rng, 0.3))
    tops, _ = D.segment_crowns(chm, RES, leaf_off=True)
    assert len(tops[0]) == 2


def test_archetype_rules_separate_conifers_from_bare_hardwoods():
    rows = []
    rng = np.random.default_rng(3)
    for k in range(60):   # leaf-off hardwoods: open (high penetration), sparse CHM, low crown NDVI (bare branches over litter)
        rows.append(dict(height=rng.uniform(12, 24), crown_r=rng.uniform(4, 7), crown_base=rng.uniform(3, 6), sharpness=rng.uniform(0.6, 1.4),
                         penetration=rng.uniform(0.35, 0.6), L=rng.uniform(32, 42), A=1.0, B=8.0, ndvi=rng.uniform(0.05, 0.2), solidity=rng.uniform(0.3, 0.55)))
    for k in range(8):    # spruces: dense, solid, green, narrow, peaked, branches to the ground
        rows.append(dict(height=rng.uniform(14, 20), crown_r=rng.uniform(2.2, 3.2), crown_base=rng.uniform(0.5, 1.5), sharpness=rng.uniform(2.5, 4),
                         penetration=rng.uniform(0.05, 0.15), L=rng.uniform(24, 29), A=-6.0, B=6.0, ndvi=rng.uniform(0.35, 0.5), solidity=rng.uniform(0.85, 0.98)))
    for k in range(5):    # white pines: tall, green, solid-ish, high crown base, flatter top
        rows.append(dict(height=rng.uniform(22, 28), crown_r=rng.uniform(4, 6), crown_base=rng.uniform(10, 14), sharpness=rng.uniform(0.8, 1.6),
                         penetration=rng.uniform(0.15, 0.25), L=rng.uniform(26, 31), A=-5.0, B=7.0, ndvi=rng.uniform(0.3, 0.45), solidity=rng.uniform(0.7, 0.9)))
    rows.append(dict(height=3.5, crown_r=1.2, crown_base=1.0, sharpness=0.7, penetration=0.4, L=35, A=0, B=7, ndvi=0.2, solidity=0.6))
    feats = [{"properties": dict(r)} for r in rows]
    D.assign_archetypes(feats)
    got = [f["properties"]["archetype"] for f in feats]
    assert all(a in ("maple", "oak") for a in got[:60]), got[:60]
    assert got[60:68].count("spruce") >= 7, got[60:68]
    assert got[68:73].count("pine") >= 4, got[68:73]
    assert got[73] == "shrub"
    assert 0.2 < got[:60].count("oak") / 60 < 0.8      # both hardwood groups are used
