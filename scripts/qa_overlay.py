"""Draw class-map boundaries (or polygon files) over imagery for a UTM window."""
import sys, json, numpy as np, rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from PIL import Image, ImageDraw
from skimage.segmentation import find_boundaries
sys.path.insert(0,'scripts'); import config as C
from qa_classes import PAL
from qa_crops import grid

def imagery(b, res):
    with rasterio.open(C.IMAGERY) as ds:
        W=int(round((b[2]-b[0])/res)); H=int(round((b[3]-b[1])/res))
        a=ds.read([1,2,3], window=from_bounds(*b, transform=ds.transform), out_shape=(3,H,W), resampling=Resampling.bilinear)
    return Image.fromarray(np.moveaxis(a,0,-1))

def class_overlay(im, b, res, path='build/classes.tif'):
    with rasterio.open(path) as ds:
        W, H = im.size
        c = ds.read(1, window=from_bounds(*b, transform=ds.transform), out_shape=(H,W), resampling=Resampling.nearest)
    bd = find_boundaries(c, mode='inner')
    a = np.array(im)
    for k,v in PAL.items():
        m = bd & (c==k)
        a[m] = v
    return Image.fromarray(a)

def poly_overlay(im, b, res, geojson):
    d = ImageDraw.Draw(im)
    gj = json.load(open(geojson))
    for f in gj['features']:
        col = tuple(int(f['properties'].get('stroke','#ff00ff')[i:i+2],16) for i in (1,3,5))
        g = f['geometry']
        rings = g['coordinates'] if g['type']=='Polygon' else [r for p in g['coordinates'] for r in p] if g['type']=='MultiPolygon' else [g['coordinates']]
        for ring in rings:
            pts=[((x-b[0])/res,(b[3]-y)/res) for x,y in ring]
            d.line(pts, fill=col, width=2)
    return im

if __name__=='__main__':
    b=tuple(map(float,sys.argv[1:5])); res=float(sys.argv[5]); out=sys.argv[6]; src=sys.argv[7] if len(sys.argv)>7 else 'classes'
    im = imagery(b,res)
    im = class_overlay(im,b,res) if src=='classes' else poly_overlay(im,b,res,src)
    grid(im,b,res,step=10 if (b[2]-b[0])<150 else 25).save(out); print(out, im.size)
