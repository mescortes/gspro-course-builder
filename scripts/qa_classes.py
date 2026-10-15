import sys, numpy as np, rasterio
from PIL import Image
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent)); import config as C
PAL = {0:(0,0,0),1:(188,229,164),2:(67,229,97),3:(160,229,184),4:(229,229,170),5:(190,190,187),6:(39,132,56),7:(10,60,20),8:(200,60,60),9:(90,90,90),10:(190,117,29),11:(0,0,192)}
def colorize(c):
    out = np.zeros(c.shape+(3,), np.uint8)
    for k,v in PAL.items(): out[c==k]=v
    return out
if __name__=='__main__':
    path = sys.argv[1] if len(sys.argv)>1 else C.BUILD / 'classes.tif'
    c = rasterio.open(path).read(1)
    b = tuple(map(float, sys.argv[2:6])) if len(sys.argv)>5 else (362470,3775160,362800,3775460)
    T = rasterio.open(path).transform
    c0=int((b[0]-T.c)/T.a); c1=int((b[2]-T.c)/T.a); r0=int((b[3]-T.f)/T.e); r1=int((b[1]-T.f)/T.e)
    img = colorize(c[r0:r1, c0:c1])
    out = sys.argv[6] if len(sys.argv)>6 else C.BUILD / 'qa_classes_h1.png'
    Image.fromarray(img).save(out); print(out, img.shape)
