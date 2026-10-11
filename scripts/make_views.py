"""Camera presets for the viewer (model frame) derived from hole 1 geometry + DEM."""
import sys, json, numpy as np, rasterio
sys.path.insert(0, 'scripts'); import config as C

def h_at(e, n):
    with rasterio.open(C.BUILD / 'dem.tif') as ds:
        r, c = ds.index(e, n); return float(ds.read(1)[r, c])

def m(e, n, dz=0.0):
    return [e - C.ORIGIN_E, h_at(e, n) - C.BASE_H + dz, -(n - C.ORIGIN_N)]

tee = (362731.6, 3775187.4); bend = (362574.0, 3775298.8); green = (362581.8, 3775414.4)
views = {
  "tee":      {"pos": m(*tee, 1.75), "target": m(362600, 3775290, 0.0), "fov": 50},
  "tee_wide": {"pos": m(362745, 3775178, 6.0), "target": m(362600, 3775320, 0.0), "fov": 60},
  "fairway":  {"pos": m(362592, 3775285, 1.75), "target": m(*green, 0.5), "fov": 45},
  "approach": {"pos": m(362582, 3775360, 1.75), "target": m(*green, 0.0), "fov": 45},
  "green":    {"pos": m(362596, 3775392, 1.7), "target": m(362582.9, 3775412.9, 0.0), "fov": 50},
  "behind_green": {"pos": m(362590, 3775445, 6.0), "target": m(362660, 3775230, 0.0), "fov": 55},
  "flag":     {"pos": m(362588, 3775398, 1.6), "target": m(362582.5, 3775411.5, 1.0), "fov": 45},
  "clubhouse":{"pos": m(362700, 3775215, 3.0), "target": m(362770, 3775165, 4.0), "fov": 55},
  "putt":     {"pos": m(362580.5, 3775406.0, 1.2), "target": m(362583.2, 3775414.5, 0.0), "fov": 55},
  "rough_lie":{"pos": m(362618, 3775300, 1.5), "target": m(362590, 3775330, 0.0), "fov": 60},
  "bunker_lie":{"pos": m(362569.0, 3775404.5, 1.5), "target": m(362582.9, 3775412.9, 0.5), "fov": 60},
  "overview": {"pos": m(362800, 3775100, 160.0), "target": m(362640, 3775310, 0.0), "fov": 45},
  "top":      {"pos": m(362650, 3775300, 420.0), "target": m(362650, 3775301, 0.0), "fov": 45},
}
json.dump(views, open('viewer/views.json', 'w'), indent=1)
print(json.dumps(views, indent=1))
