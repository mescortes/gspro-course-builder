"""Unit tests for the terrain mesh's constraint graph (build_terrain_mesh.build_pslg) on synthetic data."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_terrain_mesh as B  # noqa: E402


def _brambles_pinch(p=(0, 0)):
    """Brambles' cart paths touching at a vertex P with the rough's boundary passing through it, as the snapped graph had
    them (main 5f7ae32: P at E 536419.53 N 4291265.92, here origin-relative; cm offsets from P on the 1 cm grid), and a
    box round them. p moves P (cm)."""
    p0 = np.array([-530.47, -84.08])
    cm = np.array([[-31, 7], [-7, 3], list(p), [28, -12], [47, -15]])
    V = np.vstack([p0 + 0.01 * cm, p0 + 1.5 * np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]])])
    S = np.array([[0, 1], [0, 2], [1, 3], [3, 4], [5, 6], [5, 8], [6, 7], [7, 8]])   # sorted pairs, as build_pslg has them
    return np.round(V / 0.01) * 0.01, S


def test_a_vertex_snapped_onto_another_segment_splits_it():
    """Brambles' clean build on main 5f7ae32 left 912 zero-area triangles within 1 mm of a point where two cart paths
    touch: after the boundaries were simplified and snapped to the 1 cm grid, the cart paths' vertex lay exactly on the
    rough's boundary segment, which was not split there, and Triangle ran out of precision refining round it. A segment
    with a vertex of the graph exactly on it (exact on the grid's integer coordinates) is split there; a vertex beside a
    segment is left alone."""
    import triangle
    V, S = _brambles_pinch()
    S2 = B.split_at_vertices(V, S, 0.01)
    assert sorted(map(tuple, S2.tolist())) == sorted([(0, 1), (0, 2), (1, 2), (2, 3), (3, 4), (5, 6), (6, 7), (7, 8), (5, 8)])
    t = triangle.triangulate({"vertices": V, "segments": S2}, "pq25a0.03")
    T = t["vertices"][t["triangles"]]
    e1, e2 = T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]
    assert (0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) > 1e-8).all()
    V, S = _brambles_pinch((1, 0))                                  # 1 cm off the rough's segment: no split
    assert np.array_equal(B.split_at_vertices(V, S, 0.01), S)
    V, S = _brambles_pinch((-14, 6))                                # on its line, past the segment's end: no split
    assert np.array_equal(B.split_at_vertices(V, S, 0.01), S)
