"""Render a GeoJSON surface partition as filled colours (optionally blended with imagery)."""
import sys, json, numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from qa_overlay import imagery
from qa_crops import grid
FILL = {"deeprough":(22,75,32),"green":(188,229,164),"fringe":(150,200,130),"fairway":(67,229,97),"semirough":(54,183,77),"rough":(39,132,56),
        "tee":(160,229,184),"bunker":(240,235,170),"cartpath":(190,190,187),"native":(190,117,29),"road":(85,85,85),
        "building":(200,60,60),"court":(51,85,170),"water":(0,0,192)}
b=tuple(map(float,sys.argv[1:5])); res=float(sys.argv[5]); src=sys.argv[6]; out=sys.argv[7]; alpha=float(sys.argv[8]) if len(sys.argv)>8 else 1.0
W=int(round((b[2]-b[0])/res)); H=int(round((b[3]-b[1])/res))
canvas=Image.new('RGB',(W,H),(255,0,255)); d=ImageDraw.Draw(canvas)
gj=json.load(open(src))
order=["rough","deeprough","semirough","native","fairway","fringe","court","building","road","cartpath","water","tee","bunker","green"]
def px(c): return [((x-b[0])/res,(b[3]-y)/res) for x,y in c]
for s in order:
    for f in gj['features']:
        if f['properties']['surface']!=s: continue
        g=f['geometry']; polys=[g['coordinates']] if g['type']=='Polygon' else g['coordinates']
        for poly in polys:
            # draw exterior then punch holes with magenta-free approach: draw holes later via mask
            mask=Image.new('L',(W,H),0); md=ImageDraw.Draw(mask)
            md.polygon(px(poly[0]),fill=255)
            for hole in poly[1:]: md.polygon(px(hole),fill=0)
            canvas.paste(FILL[s], mask=mask)
if alpha<1:
    canvas=Image.blend(imagery(b,res),canvas,alpha)
grid(canvas,b,res,step=25).save(out); print(out)
