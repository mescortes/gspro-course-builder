"""Procedural, tileable PBR turf textures (albedo / normal / ORM) for the mown golf surfaces.

Each texture is a periodic canvas of individually drawn grass blades (wrap-around), so it tiles seamlessly.
Albedo is generated neutral-bright and is modulated per vertex by the aerial-imagery tint (COLOR_0) in the model.
Output: data/textures_gen/<name>/{albedo.jpg, normal.png, orm.jpg}
"""
import sys, colorsys, zlib
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C

N = 2048
OUT = C.DATA / "textures_gen"

# name: (tile metres, blades, blade length px (min,max), width px, base HSV, hue jitter, sat jitter, val jitter,
#        dry fraction, soil/gap darkness, grain direction (deg) or None, normal strength)
SPECS = {
    "green":     dict(tile=1.0, blades=900_000, length=(6, 14), width=1, hsv=(0.27, 0.62, 0.62), dh=0.020, ds=0.10, dv=0.16,
                      dry=0.01, gap=0.80, grain=None, nstrength=2.0),
    "fringe":    dict(tile=1.2, blades=650_000, length=(9, 22), width=2, hsv=(0.27, 0.60, 0.60), dh=0.025, ds=0.12, dv=0.18,
                      dry=0.02, gap=0.72, grain=None, nstrength=2.5),
    "fairway":   dict(tile=1.5, blades=600_000, length=(10, 26), width=2, hsv=(0.26, 0.58, 0.60), dh=0.03, ds=0.12, dv=0.20,
                      dry=0.03, gap=0.70, grain=None, nstrength=2.8),
    "tee":       dict(tile=1.5, blades=600_000, length=(10, 24), width=2, hsv=(0.265, 0.58, 0.60), dh=0.03, ds=0.12, dv=0.20,
                      dry=0.03, gap=0.70, grain=None, nstrength=2.8),
    "semirough": dict(tile=2.0, blades=520_000, length=(16, 40), width=2, hsv=(0.255, 0.60, 0.58), dh=0.03, ds=0.12, dv=0.22,
                      dry=0.025, gap=0.6, grain=None, nstrength=3.5),
    "rough":     dict(tile=2.5, blades=520_000, length=(20, 52), width=3, hsv=(0.25, 0.60, 0.56), dh=0.03, ds=0.12, dv=0.22,
                      dry=0.03, gap=0.55, grain=None, nstrength=4.0),
}


def periodic_noise(n, scale_px, rng, octaves=4):
    """Tileable fractal noise in [0,1] via spectral synthesis."""
    out = np.zeros((n, n))
    amp = 1.0
    for o in range(octaves):
        f = np.fft.fftfreq(n)[:, None] ** 2 + np.fft.fftfreq(n)[None, :] ** 2
        s = scale_px / (2 ** o)
        filt = np.exp(-f * (s ** 2) * 2.0)
        z = np.real(np.fft.ifft2(np.fft.fft2(rng.standard_normal((n, n))) * filt))
        out += amp * z / (z.std() + 1e-9)
        amp *= 0.5
    out -= out.min(); out /= out.max()
    return out


def draw_blades(spec, rng):
    n = N
    albedo = np.zeros((n, n, 3), np.float32)
    height = np.zeros((n, n), np.float32)
    # base layer: soil/thatch between blades
    base_h, base_s, base_v = spec["hsv"]
    thatch = np.array(colorsys.hsv_to_rgb(base_h - 0.02, base_s * 0.85, base_v * spec["gap"]), np.float32)
    patch = periodic_noise(n, 180, rng, 3)
    albedo[:] = thatch * (0.85 + 0.3 * patch[..., None])
    # blades drawn in batches onto PIL canvases (RGB + height), wrapped for tiling
    img = Image.fromarray((albedo * 255).astype(np.uint8))
    himg = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(img); dh = ImageDraw.Draw(himg)
    B = spec["blades"]
    x = rng.uniform(0, n, B); y = rng.uniform(0, n, B)
    L = rng.uniform(*spec["length"], B)
    if spec["grain"] is None:
        ang = rng.uniform(0, 2 * np.pi, B)
    else:
        ang = np.radians(spec["grain"]) + rng.normal(0, 0.6, B)
    # blades seen from above are foreshortened: most point roughly up, so the projected length varies
    L *= rng.uniform(0.25, 1.0, B)
    dx = np.cos(ang) * L; dy = np.sin(ang) * L
    lowf = periodic_noise(n, 90, rng, 3)  # clumps of slightly different colour
    clump = lowf[(y.astype(int)) % n, (x.astype(int)) % n]
    hue = base_h + rng.normal(0, spec["dh"], B) + (clump - 0.5) * 0.02
    sat = np.clip(base_s + rng.normal(0, spec["ds"], B), 0.15, 0.95)
    val = np.clip(base_v * (1 + rng.normal(0, spec["dv"], B)) * (0.9 + 0.2 * clump), 0.1, 1.0)
    dry = rng.uniform(0, 1, B) < spec["dry"]
    hue[dry] = rng.uniform(0.10, 0.16, dry.sum()); sat[dry] *= 0.6; val[dry] = np.clip(val[dry] * 1.15, 0, 1)
    # draw order: random; blades drawn later sit "on top" -> taller
    hgt = rng.uniform(0.3, 1.0, B)
    rgb = np.array([colorsys.hsv_to_rgb(h % 1.0, s, v) for h, s, v in zip(hue[:200000], sat[:200000], val[:200000])])
    if B > 200000:
        rgb = np.concatenate([rgb, rgb[rng.integers(0, 200000, B - 200000)] * rng.uniform(0.93, 1.07, (B - 200000, 1))])
    rgb = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    w = spec["width"]
    order = np.argsort(hgt)
    for i in order:
        x0, y0 = x[i], y[i]; x1, y1 = x0 + dx[i], y0 + dy[i]
        col = tuple(int(c) for c in rgb[i]); hv = int(60 + 195 * hgt[i])
        for ox in ((0,) if 2 < x0 < n - 60 else (0, -n, n)):
            for oy in ((0,) if 2 < y0 < n - 60 else (0, -n, n)):
                d.line([(x0 + ox, y0 + oy), (x1 + ox, y1 + oy)], fill=col, width=w)
                dh.line([(x0 + ox, y0 + oy), (x1 + ox, y1 + oy)], fill=hv, width=w)
    alb = np.asarray(img).astype(np.float32) / 255
    h = np.asarray(himg).astype(np.float32) / 255
    # subtle large-scale variation so repeats are less obvious
    alb *= (0.94 + 0.12 * periodic_noise(n, 300, rng, 2))[..., None]
    return alb, h


def normal_from_height(h, strength):
    hs = ndimage.gaussian_filter(h, 0.7, mode="wrap")
    gx = (np.roll(hs, -1, 1) - np.roll(hs, 1, 1)) * 0.5 * strength
    gy = (np.roll(hs, -1, 0) - np.roll(hs, 1, 0)) * 0.5 * strength
    nz = np.ones_like(hs)
    v = np.stack([-gx, gy, nz], -1)  # OpenGL convention (+Y up in tangent space)
    v /= np.linalg.norm(v, axis=-1, keepdims=True)
    return ((v * 0.5 + 0.5) * 255).astype(np.uint8)


def orm(h, base_rough):
    ao = np.clip(0.55 + 0.45 * ndimage.gaussian_filter(h, 1.5, mode="wrap") / max(h.max(), 1e-3), 0, 1)
    rough = np.clip(base_rough + 0.08 * (1 - h), 0, 1)
    return (np.stack([ao, rough, np.zeros_like(h)], -1) * 255).astype(np.uint8)


def make(name):
    spec = SPECS[name]
    rng = np.random.default_rng(zlib.crc32(name.encode()))  # not hash(name): Python salts it per process
    alb, h = draw_blades(spec, rng)
    out = OUT / name; out.mkdir(parents=True, exist_ok=True)
    Image.fromarray((np.clip(alb, 0, 1) * 255).astype(np.uint8)).save(out / "albedo.jpg", quality=92)
    Image.fromarray(normal_from_height(h, spec["nstrength"])).save(out / "normal.png", optimize=True)
    Image.fromarray(orm(h, 0.86)).save(out / "orm.jpg", quality=92)
    print("made", name, "mean albedo", alb.reshape(-1, 3).mean(0).round(3), flush=True)


if __name__ == "__main__":
    for nm in (sys.argv[1:] or SPECS):
        make(nm)
