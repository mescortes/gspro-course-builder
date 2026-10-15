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


# archetype: source sprites (None = procedural needles), target HSV, leaves per card, leaf scale (fraction of card),
# twig colour, extra hues: regions/<region>.toml [foliage.<archetype>]
SPEC = {k: dict(C.as_tuples(v), src=v["src"] or None) for k, v in C.REGION["foliage"].items()}


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


def pine_card(rng, size=512, hsv=(0.30, 0.38, 0.33)):
    """White-pine style tufts: long soft needles in bundles along a few short twigs."""
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
            h = hsv[0] + rng.normal(0, 0.02); sat = np.clip(hsv[1] + rng.normal(0, 0.08), 0.2, 0.7)
            v = np.clip(hsv[2] - 0.08 + 0.14 * f + rng.normal(0, 0.05), 0.10, 0.5)
            col = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h, sat, v)) + (255,)
            d.line([(bx, by), (bx + np.cos(a2) * nl, by + np.sin(a2) * nl)], fill=col, width=2)
    return card


def spruce_card(rng, size=512, hsv=(0.37, 0.42, 0.24)):
    """Spruce sprays: a drooping branchlet with side shoots densely clothed in short, stiff needles."""
    import colorsys
    card = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    for t in range(rng.integers(2, 4)):
        x0, y0 = size * rng.uniform(0.3, 0.7), size * 0.12
        ang = np.pi / 2 + rng.normal(0, 0.35)            # main shoot hangs down the card
        L = size * rng.uniform(0.6, 0.8)
        x1, y1 = x0 + np.cos(ang) * L, y0 + np.sin(ang) * L
        shoots = [((x0, y0), (x1, y1), 1.0)]
        for k in range(rng.integers(5, 9)):                # side shoots, alternating, shorter towards the tip
            f = rng.uniform(0.1, 0.9); bx, by = x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
            a2 = ang + (1 if k % 2 else -1) * rng.uniform(0.6, 1.1)
            l2 = size * rng.uniform(0.12, 0.25) * (1.1 - f)
            shoots.append(((bx, by), (bx + np.cos(a2) * l2, by + np.sin(a2) * l2), 0.7))
        for (ax_, ay_), (bx_, by_), w in shoots:
            d.line([(ax_, ay_), (bx_, by_)], fill=(86, 66, 50, 255), width=3 if w == 1.0 else 2)
            sl = np.hypot(bx_ - ax_, by_ - ay_)
            sa = np.arctan2(by_ - ay_, bx_ - ax_)
            for k in range(int(sl * 1.6)):
                f = rng.uniform(0, 1); px_, py_ = ax_ + (bx_ - ax_) * f, ay_ + (by_ - ay_) * f
                a3 = sa + rng.choice([-1, 1]) * rng.uniform(0.5, 1.3)
                nl = size * rng.uniform(0.018, 0.032)
                h = hsv[0] + rng.normal(0, 0.015); sat = np.clip(hsv[1] + rng.normal(0, 0.07), 0.2, 0.7)
                v = np.clip(hsv[2] + 0.1 * (1 - f) * rng.uniform() + rng.normal(0, 0.04), 0.08, 0.45)
                col = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h % 1, sat, v)) + (255,)
                d.line([(px_, py_), (px_ + np.cos(a3) * nl, py_ + np.sin(a3) * nl)], fill=col, width=2)
    return card


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, spec in SPEC.items():
        rng = np.random.default_rng(sum(map(ord, name)))
        sps = sprites(REF / spec["src"], min_px=300) if spec["src"] else []
        atlas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        for k in range(4):
            if name == "pine":
                card = pine_card(rng, 512, spec["hsv"])
            elif name == "spruce":
                card = spruce_card(rng, 512, spec["hsv"])
            else:
                card = make_card(spec, sps, rng, 512)
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
