"""3D grass ("3DG") hand-off: per-surface settings and per-vertex density masks.

GSPro's grass blades come from the Stix Games "DirectX 11 Grass Shader" (3DG), which the course designer adds in Unity
to the semi-rough / rough / deep-rough meshes (Grass Renderer + Nature Mesh Filter, layer '600m cull'); blades are
generated on the GPU from the floor mesh (research/GSPRO_COSMETICS.md). Its 'Vertex density' mode reads the mesh's
vertex colours, one channel per grass type. We therefore write, for every course-mesh vertex (glTF COLOR_1, exported to
the FBX as the 'Col' colour layer):
  R  density of grass type 1 (the mown turf blades): 1 on grass surfaces, ramping to 0 within CLEAR_M of sand, lips,
     paths, water and pavement (no blades poking into bunkers or over curbs), thinned under tree canopy
  G  density of grass type 2 (dry / dormant blades): the photo's dry-grass fraction on that spot
  B  reserved (0)
Non-grass surfaces get (0, 0, 0). The same masks drive the viewer's preview grass (viewer/grass.js).

SPEC also lists blade settings per surface. Heights and densities are our estimates for MountainGate's kikuyu /
bermuda rough (no public source gives per-surface 3DG values); the 3DG property names are from the Stix docs.
"""
import json
import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

GRASS3DG = ("semirough", "rough", "deeprough")          # "if the lawn mower goes there, 3DG" (OPCD doc)
NO_GRASS = ("bunker", "bunkerlip", "cartpath", "road", "building", "court", "water", "wateredge", "green", "tee")
CLEAR_M = (0.15, 0.6)     # no blades within 0.15 m of a no-grass surface, full density from 0.6 m
CANOPY = (3.0, 0.55)      # under canopy taller than 3 m keep 55 % of the blades

SPEC = {
    "about": "3D grass settings per OPCD surface. 3dg = Stix Games DirectX 11 Grass Shader material settings to start "
             "from (estimates, tune in Unity); viewer = our three.js preview. Masks: FBX colour layer 'Col' "
             "(R = grass type 1 density, G = grass type 2 / dry, B = 0) for 3DG 'Vertex density' mode.",
    "3dg": {
        "common": {"Density Mode": "Vertex density", "Grass Types": "2 textures (type 1 = green blades, type 2 = dry blades)",
                   "layer": "600m cull", "Density Falloff Start": 12.0, "Grass Fade End": 90.0,
                   "Lighting Mode": "Default PBR", "notes": "Target Density: smaller number = denser grass (Stix docs)"},
        "SemiRough": {"blade_height_m": [0.025, 0.045], "blade_width_m": 0.006, "relative_density": 1.0},
        "Rough":     {"blade_height_m": [0.045, 0.085], "blade_width_m": 0.007, "relative_density": 0.9},
        "DeepRough": {"blade_height_m": [0.12, 0.32], "blade_width_m": 0.008, "relative_density": 0.55},
    },
    "viewer": {
        "radius_m": 55, "full_density_m": 22, "far_density": 0.18, "tile_m": 6, "max_instances": 400000,
        "wind": {"strength": 0.35, "speed": 1.0},
        "surfaces": {
            "SemiRough": {"height": [0.03, 0.05], "width": 0.008, "density": 45, "blades": 8, "colour_tip": [1.12, 1.14, 1.0], "dry": 0.0},
            "Rough":     {"height": [0.05, 0.09], "width": 0.009, "density": 40, "blades": 9, "colour_tip": [1.15, 1.15, 0.98], "dry": 0.05},
            "DeepRough": {"height": [0.14, 0.32], "width": 0.010, "density": 14, "blades": 9, "colour_tip": [1.14, 1.10, 0.88], "dry": 0.25},
            "Pinestraw": {"height": [0.22, 0.45], "width": 0.008, "density": 7, "blades": 10, "colour_tip": [1.22, 1.12, 0.82], "dry": 0.6},
        },
    },
}


def dryness_grid(img_lin, block=8):
    """Dry-grass fraction (0..1) on a coarse grid from the linear photo: yellow/brown hues -> dry."""
    from skimage.color import rgb2lab
    H, W = img_lin.shape[:2]
    h, w = H // block, W // block
    small = img_lin[:h * block, :w * block].reshape(h, block, w, block, 3).mean((1, 3))
    srgb = np.where(small <= 0.0031308, small * 12.92, 1.055 * np.power(np.clip(small, 0, 1), 1 / 2.4) - 0.055)
    lab = rgb2lab(srgb)
    hue = np.degrees(np.arctan2(lab[..., 2], lab[..., 1]))
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    dry = np.clip((122.0 - hue) / 30.0, 0, 1) * np.clip(chroma / 14.0, 0, 1)
    return ndimage.gaussian_filter(dry.astype(np.float32), 1.0)


def vertex_masks(V, F, surf, names, chm=None, chm_T=None, dry=None, dry_T=None):
    """(nV, 3) float masks for the vertices V (UTM x, y[, z]) of faces F labelled surf (indices into names)."""
    names = list(names)
    sid = {n: i for i, n in enumerate(names)}
    grass_ids = [sid[n] for n in GRASS3DG if n in sid]
    block_ids = [sid[n] for n in NO_GRASS if n in sid]
    gf = np.isin(surf, grass_ids)
    out = np.zeros((len(V), 3), np.float32)
    gv = np.unique(F[gf])
    if not len(gv):
        return out
    bv = np.unique(F[np.isin(surf, block_ids)])
    R = np.ones(len(gv), np.float32)
    if len(bv):
        d, _ = cKDTree(V[bv, :2]).query(V[gv, :2], distance_upper_bound=CLEAR_M[1] + 0.5)
        R *= np.clip((d - CLEAR_M[0]) / (CLEAR_M[1] - CLEAR_M[0]), 0, 1)
    if chm is not None:
        c = (V[gv, 0] - chm_T.c) / chm_T.a - 0.5; r = (V[gv, 1] - chm_T.f) / chm_T.e - 0.5
        h = ndimage.map_coordinates(chm, [r, c], order=1, mode="nearest")
        R *= np.where(h > CANOPY[0], CANOPY[1], 1.0)
    G = np.zeros(len(gv), np.float32)
    if dry is not None:
        c = (V[gv, 0] - dry_T.c) / dry_T.a - 0.5; r = (V[gv, 1] - dry_T.f) / dry_T.e - 0.5
        G = ndimage.map_coordinates(dry, [r, c], order=1, mode="nearest") * R
    out[gv, 0] = R; out[gv, 1] = G
    return out


def write_spec(path):
    json.dump(SPEC, open(path, "w"), indent=1)
