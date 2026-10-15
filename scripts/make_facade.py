"""Procedural facade texture: stucco wall with a storey of windows (tiles 4 m wide x 3.5 m tall)."""
import sys, numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent)); import config as C
W, H = 1024, 896  # 4 m x 3.5 m at 256 px/m
base = Image.open(C.DATA / 'textures/white_stucco/diffuse.jpg').convert('RGB').resize((1024, 1024)).crop((0, 0, W, H))
a = np.asarray(base).astype(np.float32)
a = a * np.array([1.0, 0.97, 0.9]) * 0.95  # warm off-white stucco
img = Image.fromarray(a.clip(0, 255).astype(np.uint8)); d = ImageDraw.Draw(img)
# window: 2.4 m wide, 1.7 m tall, sill at 0.9 m; dark frame; glass with sky reflection gradient
x0, x1 = int(0.8 * 256), int(3.2 * 256); y1 = H - int(0.9 * 256); y0 = y1 - int(1.7 * 256)
d.rectangle([x0 - 10, y0 - 10, x1 + 10, y1 + 10], fill=(70, 66, 60))
g = np.zeros((y1 - y0, x1 - x0, 3), np.float32)
t = np.linspace(0, 1, y1 - y0)[:, None]
g[..., 0] = 60 + 50 * (1 - t); g[..., 1] = 75 + 55 * (1 - t); g[..., 2] = 90 + 70 * (1 - t)
img.paste(Image.fromarray(g.astype(np.uint8)), (x0, y0))
d.rectangle([(x0 + x1) // 2 - 5, y0, (x0 + x1) // 2 + 5, y1], fill=(70, 66, 60))
# eave shadow band at the top
arr = np.asarray(img).astype(np.float32); arr[:40] *= np.linspace(0.6, 1, 40)[:, None, None]
out = C.DATA / 'textures_gen/facade'; out.mkdir(parents=True, exist_ok=True)
Image.fromarray(arr.clip(0, 255).astype(np.uint8)).save(out / 'albedo.jpg', quality=90)
# normal: flat with window recess edges
n = np.zeros((H, W, 3), np.uint8); n[..., 0] = 128; n[..., 1] = 128; n[..., 2] = 255
Image.fromarray(n).save(out / 'normal.png')
print('facade ok')
