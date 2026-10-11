"""Foliage-cluster card textures (RGBA) composed from CC0 Poly Haven leaf / twig sprites.

Sprites are keyed out of the black-background leaf atlases, recoloured per species and scattered along little twigs
on a transparent canvas. Output: data/textures_gen/foliage_<archetype>.png (RGBA, 1024^2, 2x2 variant atlas)
"""
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C

REF = C.DATA / "textures/leaf_refs"
OUT = C.DATA / "textures_gen"


def sprites(path, min_px=400, thresh=18):
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    lum = a.max(-1)
    m = ndimage.binary_opening(lum > thresh, iterations=1)
    lab, n = ndimage.label(m)
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        if sl is None:
            continue
        mm = lab[sl] == i
        if mm.sum() < min_px:
            continue
        rgb = a[sl].copy()
        alpha = ndimage.gaussian_filter(mm.astype(np.float32), 0.6)
        rgba = np.dstack([rgb, np.clip(alpha * 255, 0, 255)]).astype(np.uint8)
        out.append(Image.fromarray(rgba, "RGBA"))
    return out


def recolor(sp, hsv_target, rng, var=0.08):
    """Map sprite colours towards a target mean colour (keeps internal veins/shading)."""
    a = np.asarray(sp).astype(np.float32) / 255
    rgb, al = a[..., :3], a[..., 3:]
    m = al[..., 0] > 0.5
    if m.sum() == 0:
        return sp
    mean = rgb[m].mean(0)
    import colorsys
    h, s, v = hsv_target
    h = (h + rng.normal(0, 0.012)) % 1; s = np.clip(s * (1 + rng.normal(0, var)), 0, 1); v = np.clip(v * (1 + rng.normal(0, var * 1.5)), 0, 1)
    tgt = np.array(colorsys.hsv_to_rgb(h, s, v))
    lum = rgb.mean(-1, keepdims=True) / max(mean.mean(), 1e-3)
    out = np.clip(tgt * lum ** 0.9, 0, 1)
    return Image.fromarray((np.dstack([out, al]) * 255).astype(np.uint8), "RGBA")


SPEC = {
    # archetype: source sprites, target HSV, leaves per card, leaf scale (fraction of card), twig colour, extra hues
    "oak":        dict(src="island_tree_02__island_tree_02_leaves_diff_1k.jpg", hsv=(0.21, 0.58, 0.27), n=420, scale=(0.040, 0.060), twig=(70, 58, 45),
                       alt=[((0.19, 0.5, 0.36), 0.2)]),
    "sycamore":   dict(src="island_tree_02__island_tree_02_leaves_diff_1k.jpg", hsv=(0.20, 0.55, 0.45), n=90, scale=(0.10, 0.15), twig=(110, 100, 85),
                       alt=[((0.11, 0.65, 0.55), 0.12), ((0.16, 0.6, 0.5), 0.15)]),
    "eucalyptus": dict(src="island_tree_02__island_tree_02_leaves_diff_1k.jpg", hsv=(0.25, 0.25, 0.42), n=90, scale=(0.12, 0.18), twig=(120, 95, 75), alt=[]),
    "shrub":      dict(src="island_tree_02__island_tree_02_leaves_diff_1k.jpg", hsv=(0.19, 0.42, 0.30), n=380, scale=(0.035, 0.055), twig=(80, 70, 55),
                       alt=[((0.12, 0.35, 0.40), 0.15)]),
    "pine":       dict(src=None, hsv=(0.26, 0.45, 0.30), n=0, scale=(0, 0), twig=(85, 70, 55), alt=[]),
}


def make_card(spec, sps, rng, size=512, pine=False):
    card = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    cx, cy = size / 2, size * 0.55
    # twigs radiating from the base towards the edges
    tips = []
    for k in range(rng.integers(4, 7) if not pine else 1):
        ang = rng.uniform(-2.4, -0.7)
        L = size * rng.uniform(0.32, 0.45)
        x0, y0 = size / 2 + rng.normal(0, 10), size * 0.95
        pts = [(x0, y0)]
        for t in np.linspace(0.2, 1, 5):
            pts.append((x0 + np.cos(ang) * L * t + rng.normal(0, 6), y0 + np.sin(ang) * L * t * 1.6 + rng.normal(0, 6)))
        if not pine:
            d.line(pts, fill=spec["twig"] + (255,), width=3)
        tips.extend(pts[1:])
    for i in range(spec["n"]):
        sp = sps[rng.integers(len(sps))]
        col = spec["hsv"]
        for alt, frac in spec["alt"]:
            if rng.uniform() < frac:
                col = alt
        sp = recolor(sp, col, rng)
        sc = rng.uniform(*spec["scale"]) * size / max(sp.size)
        sp = sp.resize((max(2, int(sp.size[0] * sc)), max(2, int(sp.size[1] * sc))), Image.LANCZOS)
        if pine:
            ang = rng.uniform(0, 360)
            sp = sp.rotate(ang, expand=True, resample=Image.BICUBIC)
            px, py = cx + rng.normal(0, size * 0.06), cy + rng.normal(0, size * 0.06)
        else:
            tx, ty = tips[rng.integers(len(tips))]
            r = rng.uniform(0, size * 0.16)
            a = rng.uniform(0, 2 * np.pi)
            px, py = tx + r * np.cos(a), ty + r * np.sin(a)
            sp = sp.rotate(rng.uniform(0, 360), expand=True, resample=Image.BICUBIC)
        # darken leaves deeper in the cluster (cheap self-shadowing)
        depth = 1.0 - 0.35 * (i / spec["n"]) if not pine else 1.0
        if depth < 1:
            arr = np.asarray(sp).astype(np.float32); arr[..., :3] *= (0.65 + 0.35 * (i / spec["n"])); sp = Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGBA")
        card.alpha_composite(sp, (int(px - sp.size[0] / 2), int(py - sp.size[1] / 2)))
    return card


def pine_card(rng, size=512):
    """Aleppo-pine style tufts: needles in bundles along a few short twigs."""
    import colorsys
    card = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    for t in range(rng.integers(4, 7)):
        ang = rng.uniform(-2.6, -0.55)
        x0, y0 = size * 0.5 + rng.normal(0, 25), size * 0.92
        L = size * rng.uniform(0.45, 0.62)
        x1, y1 = x0 + np.cos(ang) * L, y0 + np.sin(ang) * L
        d.line([(x0, y0), (x1, y1)], fill=(92, 74, 58, 255), width=4)
        nb = rng.integers(150, 220)
        for k in range(nb):
            f = rng.uniform(0.25, 1.0) ** 0.6
            bx, by = x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
            spread = rng.normal(0, 0.75)
            a2 = ang + spread
            nl = size * rng.uniform(0.10, 0.17) * (0.6 + 0.4 * f)
            h = 0.25 + rng.normal(0, 0.02); sat = np.clip(0.42 + rng.normal(0, 0.08), 0.2, 0.7)
            v = np.clip(0.22 + 0.14 * f + rng.normal(0, 0.05), 0.10, 0.5)
            col = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h, sat, v)) + (255,)
            d.line([(bx, by), (bx + np.cos(a2) * nl, by + np.sin(a2) * nl)], fill=col, width=2)
    return card


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, spec in SPEC.items():
        rng = np.random.default_rng(sum(map(ord, name)))
        sps = sprites(REF / spec["src"], min_px=300) if name != "pine" else []
        atlas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        for k in range(4):
            card = pine_card(rng, 512) if name == "pine" else make_card(spec, sps, rng, 512)
            atlas.paste(card, ((k % 2) * 512, (k // 2) * 512))
        # bleed colour into transparent texels so mip-mapping does not produce dark halos
        a = np.asarray(atlas).astype(np.float32)
        m = a[..., 3] > 8
        idx = ndimage.distance_transform_edt(~m, return_distances=False, return_indices=True)
        rgb = a[..., :3][tuple(idx)]
        out = np.dstack([rgb, a[..., 3]]).astype(np.uint8)
        Image.fromarray(out, "RGBA").save(OUT / f"foliage_{name}.png", optimize=True)
        print("wrote", name)


if __name__ == "__main__":
    main()
