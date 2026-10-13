"""Add the 5 km imagery-draped backdrop terrain (see build_backdrop.py) to the glTF."""
import sys
import numpy as np
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C
from build_backdrop import NEAR, FAR, NEAR_IMG, FAR_IMG


def add(glb, root):
    p = C.BUILD / "backdrop_mesh.npz"
    if not p.exists():
        return
    from export_course import vertex_normals, to_model
    d = np.load(p)
    V, F, ring = d["V"], d["F"], d["ring"]
    N = vertex_normals(V, F)
    prims = []
    for rid, ext, img in ((1, NEAR, NEAR_IMG), (2, FAR, FAR_IMG)):
        sel = ring == rid
        vid, inv = np.unique(F[sel], return_inverse=True)
        P = V[vid]
        uv = np.c_[(P[:, 0] - ext["xmin"]) / (ext["xmax"] - ext["xmin"]), (ext["ymax"] - P[:, 1]) / (ext["ymax"] - ext["ymin"])]
        m = glb.material(f"Backdrop_{'near' if rid == 1 else 'far'}", base_color=str(img), rough=1.0)
        glb.g["materials"][m]["pbrMetallicRoughness"]["baseColorTexture"]["index"] = glb.texture(glb.image(str(img)), sampler=1)
        prims.append(dict(pos=to_model(P), nrm=np.c_[N[vid, 0], N[vid, 2], -N[vid, 1]], uv0=uv, idx=inv.reshape(-1, 3), material=m))
    mesh = glb.mesh("Backdrop_Terrain", prims)
    glb.node("Backdrop_Terrain", mesh=mesh, parent=root)
    print("backdrop triangles", len(F))
    import backdrop_objects
    backdrop_objects.add(glb, root)
