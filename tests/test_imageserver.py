"""Unit test for the ImageServer chunk layout (no network)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_imageserver as F  # noqa: E402


def test_chunks_tile_the_grid_exactly():
    W, H, wins = F.chunks(1000.0, 2000.0, 1100.0, 2064.0, 0.16, 256)
    assert (W, H) == (625, 400)
    cover = [[0] * W for _ in range(H)]
    for c0, r0, w, h, (x0, y0, x1, y1) in wins:
        assert abs((x1 - x0) - w * 0.16) < 1e-9 and abs((y1 - y0) - h * 0.16) < 1e-9
        assert abs(x0 - (1000.0 + c0 * 0.16)) < 1e-9 and abs(y1 - (2064.0 - r0 * 0.16)) < 1e-9
        for r in range(r0, r0 + h):
            for c in range(c0, c0 + w):
                cover[r][c] += 1
    assert all(v == 1 for row in cover for v in row)


def test_chunk_ground_size_is_capped_for_coarse_requests():
    assert F.chunk_size(0.16) == 2500                 # 400 m at native resolution
    assert F.chunk_size(1.25) * 1.25 <= F.MAX_CHUNK_M  # the 5 km backdrop at 1.25 m: 640 px chunks, not 3 km ones
    assert F.chunk_size(1000.0) == 64
