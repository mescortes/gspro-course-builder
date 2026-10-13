"""Procedural tree archetypes (space colonisation skeleton + bark tubes + alpha foliage cards).

Each archetype is built at a reference size (REF_H metres tall, REF_R crown radius); instances are scaled to the
LiDAR-measured height / crown radius. Foliage-card normals point away from the crown centre (soft volumetric shading).
Output: data/trees/<archetype>_v<k>_<lod>.npz with arrays for 'bark' and 'leaf' primitives.
"""
import sys
import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C

OUT = C.DATA / "trees"

ARCH = {
    # crown envelope: kind, vertical start/end as fraction of height, horizontal radius; trunk: height fraction
    # (Southern Ontario parkland species groups, see config.TREE_ARCHETYPES)
    "maple":  dict(H=14.0, R=6.0, crown=("ovoid", 0.24, 1.0), trunk=0.24, attract=1100, seg=0.45, infl=3.6, kill=0.9,
                   tropism=(0, 0.18, 0), tip_r=0.012, exp=2.05, cards=1150, card=(1.3, 1.9), lean=0.08, nsides=10,
                   up_bias=0.6, trunk_r=0.34, clumps=24, clump_sd=0.27),
    "oak":    dict(H=13.0, R=7.0, crown=("ellipsoid", 0.24, 1.0), trunk=0.22, attract=1100, seg=0.5, infl=3.8, kill=0.95,
                   tropism=(0, 0.06, 0), tip_r=0.012, exp=2.05, cards=1000, card=(1.3, 2.0), lean=0.15, nsides=10,
                   up_bias=0.65, trunk_r=0.38, clumps=18, clump_sd=0.24),
    "pine":   dict(H=19.0, R=5.2, crown=("irregular", 0.45, 1.0), trunk=0.42, attract=900, seg=0.55, infl=5.0, kill=0.9,
                   tropism=(0, 0.12, 0), tip_r=0.014, exp=2.05, cards=950, card=(1.5, 2.2), lean=0.12, nsides=9, clumps=11,
                   clump_sd=0.14, up_bias=0.7, trunk_r=0.36, tip_depth=3),
    "spruce": dict(H=15.0, R=3.3, crown=("cone", 0.04, 1.0), trunk=0.06, attract=1000, seg=0.4, infl=2.6, kill=0.7,
                   tropism=(0, -0.05, 0), tip_r=0.010, exp=2.1, cards=1300, card=(1.0, 1.5), lean=0.02, nsides=8,
                   up_bias=0.35, trunk_r=0.26, leader=True, droop=0.25, tip_depth=4),
    "shrub":  dict(H=3.2, R=2.0, crown=("ellipsoid", 0.05, 1.0), trunk=0.05, attract=260, seg=0.25, infl=1.5, kill=0.4,
                   tropism=(0, 0.1, 0), tip_r=0.008, exp=2.1, cards=260, card=(0.8, 1.2), lean=0.0, nsides=6,
                   up_bias=0.5, trunk_r=0.06),
}


N_VARIANTS = 5   # model variants per archetype (add_vegetation picks one per tree from its id)


def variant_params(name, v):
    """Archetype parameters for variant v: variant 0 is the reference shape, the others jitter the crown proportions
    (height +/- 12 %, radius +/- 15 %), crown base, lean, card size and clumping, so trees of one species are not
    clones (three seed-only variants looked copy-pasted along the fairways)."""
    a = dict(ARCH[name])
    if v == 0:
        return a
    r = np.random.default_rng(7919 * v + sum(map(ord, name))).uniform(-1, 1, 6)
    a["H"] = a["H"] * (1 + 0.12 * r[0])
    a["R"] = a["R"] * (1 + 0.15 * r[1])
    kind, z0, z1 = a["crown"]
    a["crown"] = (kind, float(np.clip(z0 + 0.06 * r[2], 0.02, 0.6)), z1)
    a["trunk"] = float(np.clip(a["trunk"] + 0.06 * r[2], 0.02, 0.6))
    a["lean"] = a["lean"] + 0.05 * abs(r[3])
    k = 1 + 0.12 * r[4]
    a["card"] = (a["card"][0] * k, a["card"][1] * k)
    if a.get("clumps"):
        a["clumps"] = max(4, int(round(a["clumps"] * (1 + 0.3 * r[5]))))
    return a


def sample_envelope(a, rng):
    H, R = a["H"], a["R"]
    kind, z0, z1 = a["crown"]
    pts = []
    centres = None
    if a.get("clumps"):  # clumped crowns: tufted masses (pines) / sub-crowns (oaks) inside the envelope
        k = a.get("clumps", 12)
        centres = []
        while len(centres) < k:
            p = rng.uniform(-1, 1, 3)
            if np.sum(p ** 2) <= 1:
                centres.append(p)
        centres = np.array(centres)
    while len(pts) < a["attract"]:
        if centres is not None:
            c = centres[rng.integers(len(centres))]
            p = c + rng.normal(0, a.get("clump_sd", 0.22), 3)
        else:
            p = rng.uniform(-1, 1, 3)
        x, yv, z = p  # yv in [-1,1] -> vertical
        if kind == "cone":  # foliage shell of a cone (bare interior, as in real spruces): radius shrinks to the apex
            rmax = 1.0 - 0.97 * (yv + 1) / 2
            if not rmax - 0.28 <= np.hypot(x, z) <= rmax:
                continue
        elif np.sum(p ** 2) > 1:
            continue
        if kind == "ovoid" and yv < 0 and np.hypot(x, z) > 0.8 * np.sqrt(max(0, 1 - yv ** 2)):
            continue
        cy = H * (z0 + (z1 - z0) * (yv + 1) / 2)
        pts.append([x * R, cy, z * R])
    return np.array(pts)


def colonise(a, rng):
    att = sample_envelope(a, rng)
    H = a["H"]; seg = a["seg"]
    nodes = [np.zeros(3)]; parent = [-1]
    lean = np.array([rng.normal(0, a["lean"]), 1.0, rng.normal(0, a["lean"])]); lean /= np.linalg.norm(lean)
    th = (0.97 if a.get("leader") else a["trunk"]) * H
    while nodes[-1][1] < th:
        p = nodes[-1] + lean * seg + rng.normal(0, 0.03, 3) * seg
        nodes.append(p); parent.append(len(nodes) - 2)
    trop = np.array(a["tropism"], float)
    alive = np.ones(len(att), bool)
    for it in range(220):
        if not alive.any():
            break
        N = np.array(nodes)
        tree = cKDTree(N)
        d, idx = tree.query(att[alive], distance_upper_bound=a["infl"])
        ok = np.isfinite(d)
        if not ok.any():
            break
        aidx = np.flatnonzero(alive)[ok]; nidx = idx[ok]
        grow = {}
        for ai, ni in zip(aidx, nidx):
            v = att[ai] - N[ni]; v /= (np.linalg.norm(v) + 1e-9)
            grow.setdefault(ni, []).append(v)
        new = 0
        for ni, vs in grow.items():
            dvec = np.mean(vs, 0) + trop + rng.normal(0, 0.08, 3)
            if a.get("droop"):
                dvec[1] -= a["droop"] * (N[ni][1] / H) ** 2
            nrm = np.linalg.norm(dvec)
            if nrm < 1e-6:
                continue
            p = N[ni] + dvec / nrm * seg
            nodes.append(p); parent.append(ni); new += 1
        if new == 0:
            break
        N = np.array(nodes)
        dd, _ = cKDTree(N).query(att)
        alive &= dd > a["kill"]
    return np.array(nodes), np.array(parent)


def radii(nodes, parent, a):
    n = len(nodes)
    children = [[] for _ in range(n)]
    for i, p in enumerate(parent):
        if p >= 0:
            children[p].append(i)
    r = np.zeros(n)
    stack = [0]; post = []
    while stack:
        i = stack.pop(); post.append(i); stack.extend(children[i])
    for i in reversed(post):
        if not children[i]:
            r[i] = a["tip_r"]
        else:
            r[i] = np.sum(np.array([r[c] for c in children[i]]) ** a["exp"]) ** (1 / a["exp"])
    # scale so the trunk base matches the archetype's trunk radius (pipe model gives the relative taper)
    r *= a["trunk_r"] / max(r[0], 1e-6)
    r = np.maximum(r, a["tip_r"])
    r[0] *= 1.3  # flare
    return r, children


def tube_mesh(nodes, parent, r, children, a, lod):
    """Continuous bark tubes: one ring per node (parallel-transported frames), continuation child shares the parent's
    ring; side branches start with their own ring at the parent position (hidden inside the parent limb)."""
    min_r = 0.025 if lod == "hi" else 0.07
    n = len(nodes)
    P, Nn, UV, I = [], [], [], []
    vlen = np.zeros(n)
    for i in range(1, n):
        vlen[i] = vlen[parent[i]] + np.linalg.norm(nodes[i] - nodes[parent[i]])
    def sides(rr):
        k = a["nsides"] if rr > 0.2 else (max(5, a["nsides"] - 3) if rr > 0.07 else 4)
        return max(4, k - 3) if lod == "lo" else k
    def ring(c, d, u, rr, vv, k):
        v = np.cross(d, u)
        b0 = len(P)
        circ = max(1, round(2 * np.pi * rr / 0.5))
        for j in range(k + 1):
            ang = 2 * np.pi * j / k
            nr = np.cos(ang) * u + np.sin(ang) * v
            P.append(c + nr * rr); Nn.append(nr); UV.append([j / k * circ, vv / 1.0])
        return b0
    def connect(r0, r1, k):
        for j in range(k):
            a0 = r0 + j; a1 = r0 + j + 1; b0 = r1 + j; b1 = r1 + j + 1
            I.extend([[a0, b0, a1], [a1, b0, b1]])
    # iterative DFS carrying (ring start index, frame u, sides)
    d0 = nodes[1] - nodes[0] if n > 1 else np.array([0, 1, 0.])
    d0 = d0 / np.linalg.norm(d0)
    u0 = np.cross(d0, [1, 0, 0]); u0 /= np.linalg.norm(u0)
    k0 = sides(r[0])
    root_ring = ring(nodes[0], d0, u0, r[0], 0, k0)
    stack = [(0, root_ring, u0, k0)]
    while stack:
        i, rg, u, k = stack.pop()
        kids = sorted(children[i], key=lambda c: -r[c])
        for ci, c in enumerate(kids):
            if r[c] < min_r:
                continue
            d = nodes[c] - nodes[i]; L = np.linalg.norm(d)
            if L < 1e-6:
                continue
            d /= L
            # parallel transport of the frame
            uc = u - np.dot(u, d) * d
            if np.linalg.norm(uc) < 1e-6:
                uc = np.cross(d, [0, 0, 1])
            uc /= np.linalg.norm(uc)
            kc = sides(r[c])
            if ci == 0 and kc == k:
                start = rg
            else:
                start = ring(nodes[i] + d * min(r[i] * 0.5, L * 0.3), d, uc, r[c] * 1.05, vlen[i], kc)
            end = ring(nodes[c], d, uc, r[c], vlen[c], kc)
            connect(start, end, kc)
            stack.append((c, end, uc, kc))
    return np.array(P, np.float32), np.array(Nn, np.float32), np.array(UV, np.float32), np.array(I, np.uint32)


def cards(nodes, parent, r, children, a, rng, lod):
    n_cards = a["cards"] if lod == "hi" else int(a["cards"] * 0.4)
    H = a["H"]; R = a["R"]
    z0, z1 = a["crown"][1], a["crown"][2]
    centre = np.array([0, H * (z0 + z1) / 2, 0]); half_h = H * (z1 - z0) / 2
    # anchors: nodes close to branch tips (tufts at the ends of limbs), preferring the outer part of the crown
    depth = np.zeros(len(nodes), int)
    post = []; st = [0]
    while st:
        i = st.pop(); post.append(i); st.extend(children[i])
    for i in reversed(post):
        depth[i] = 0 if not children[i] else 1 + max(depth[c] for c in children[i])
    thin = np.flatnonzero((depth <= a.get("tip_depth", 6)) & (nodes[:, 1] > H * z0 * 0.9))
    if len(thin) == 0:
        thin = np.arange(len(nodes))
    rel = (nodes[thin] - centre) / np.array([R, half_h, R])
    dist = np.linalg.norm(rel, axis=1)
    w = 0.25 + np.clip(dist, 0, 1.2) ** 2
    if a["crown"][0] == "cone":  # few branch tips near the apex (the leader kills them): favour the upper whorls
        w *= 0.5 + 2.5 * np.clip(nodes[thin, 1] / H, 0, 1)
    anchors = nodes[rng.choice(thin, n_cards, p=w / w.sum())]
    P, Nn, UV, I, COL = [], [], [], [], []
    scale_up = 1.0 if lod == "hi" else 1.45
    for c, an in enumerate(anchors):
        s = rng.uniform(*a["card"]) * scale_up
        out = an - centre; out[1] *= 0.5
        out = out / (np.linalg.norm(out) + 1e-6)
        # card normal: blend of outward and up (leaves face the sky), random jitter
        nrm = (1 - a["up_bias"]) * out + a["up_bias"] * np.array([0, 1, 0]) + rng.normal(0, 0.35, 3)
        nrm /= np.linalg.norm(nrm)
        t = np.cross(nrm, rng.normal(0, 1, 3)); t /= (np.linalg.norm(t) + 1e-9)
        bvec = np.cross(nrm, t)
        if a.get("droop") and rng.uniform() < 0.6:  # hanging foliage: cards hang below the anchor
            bvec = np.array([0, -1, 0]) + rng.normal(0, 0.25, 3); bvec /= np.linalg.norm(bvec)
            t = np.cross(bvec, out); t /= (np.linalg.norm(t) + 1e-9)
        o = an + rng.normal(0, 0.15, 3)
        quad = [o - t * s / 2 - bvec * s / 2, o + t * s / 2 - bvec * s / 2, o + t * s / 2 + bvec * s / 2, o - t * s / 2 + bvec * s / 2]
        cell = rng.integers(4); cu, cv = (cell % 2) * 0.5, (cell // 2) * 0.5
        uvs = [[cu, cv + 0.5], [cu + 0.5, cv + 0.5], [cu + 0.5, cv], [cu, cv]]
        # per-card hue: sun-bleached (yellower) or shaded (blue-green) leaf masses, about +/- 8 %
        hue = rng.normal(0, 1)
        tint = np.array([1 + 0.07 * hue, 1 + 0.02 * hue, 1 - 0.09 * hue]) * rng.uniform(0.9, 1.08)
        b = len(P)
        for q, tt in zip(quad, uvs):
            rel = (q - centre) / np.array([R, half_h, R])
            d = np.clip(np.linalg.norm(rel), 0, 1)
            ao = 0.38 + 0.62 * d ** 1.4
            ao *= 0.8 + 0.2 * np.clip((q[1] - H * z0) / max(H * (z1 - z0), 1e-3), 0, 1)  # underside darker
            nq = q - centre; nq[1] *= 0.6; nq /= (np.linalg.norm(nq) + 1e-6)
            P.append(q); Nn.append(0.7 * nq + 0.3 * np.array([0, 1, 0])); UV.append(tt); COL.append(np.clip(ao * tint, 0, 1))
        I += [[b, b + 1, b + 2], [b, b + 2, b + 3]]
    Nn = np.array(Nn, np.float32); Nn /= np.linalg.norm(Nn, axis=1, keepdims=True)
    return np.array(P, np.float32), Nn, np.array(UV, np.float32), np.array(I, np.uint32), np.array(COL, np.float32)


def billboard(a, rng):
    """Distant LOD: three crossed foliage quads + a top quad over a thin trunk quad (~10 triangles)."""
    H, R = a["H"], a["R"]; z0 = a["crown"][1] * H
    P, N, UV, I, COL = [], [], [], [], []
    rot0 = rng.uniform(0, np.pi)
    for k in range(3):
        ang = rot0 + k * np.pi / 3
        d = np.array([np.cos(ang), 0, np.sin(ang)]); n = np.array([-d[2], 0, d[0]])
        cell = rng.integers(4); cu, cv = (cell % 2) * 0.5, (cell // 2) * 0.5
        b = len(P)
        for (s, t, uvx, uvy) in ((-1, z0, cu, cv + 0.5), (1, z0, cu + 0.5, cv + 0.5), (1, H, cu + 0.5, cv), (-1, H, cu, cv)):
            P.append(d * R * 1.05 * s + np.array([0, t, 0])); N.append(0.6 * n * s + np.array([0, 0.8, 0])); UV.append([uvx, uvy])
            COL.append([0.55 + 0.45 * (t - z0) / max(H - z0, 1e-3)] * 3)
        I += [[b, b + 1, b + 2], [b, b + 2, b + 3]]
    # horizontal quad at 70 % crown height so the crown reads from above
    y = z0 + 0.7 * (H - z0); b = len(P)
    for (x, z, u, v) in ((-R, -R, 0, 0.5), (R, -R, 0.5, 0.5), (R, R, 0.5, 0), (-R, R, 0, 0)):
        P.append([x * 0.9, y, z * 0.9]); N.append([0, 1, 0]); UV.append([u, v]); COL.append([0.9] * 3)
    I += [[b, b + 2, b + 1], [b, b + 3, b + 2]]
    leaf = (np.array(P, np.float32), np.array(N, np.float32) / np.linalg.norm(N, axis=1, keepdims=True).astype(np.float32),
            np.array(UV, np.float32), np.array(I, np.uint32), np.array(COL, np.float32))
    tw = max(a["trunk_r"], 0.05) * 1.6
    bp = np.array([[-tw, 0, 0], [tw, 0, 0], [tw, z0 + 0.3, 0], [-tw, z0 + 0.3, 0],
                   [0, 0, -tw], [0, 0, tw], [0, z0 + 0.3, tw], [0, z0 + 0.3, -tw]], np.float32)
    bn = np.array([[0, 0, 1]] * 4 + [[1, 0, 0]] * 4, np.float32)
    buv = np.array([[0, 0], [1, 0], [1, 3], [0, 3]] * 2, np.float32)
    bi = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]], np.uint32)
    return (bp, bn, buv, bi), leaf


def build(name, variant, lod):
    a = variant_params(name, variant)
    rng = np.random.default_rng(1000 * variant + sum(map(ord, name)))
    if lod == "bb":
        bark, leaf = billboard(a, rng)
        if a["crown"][1] < 0.1:  # shrubs: no visible trunk
            bark = tuple(np.zeros((0,) + x.shape[1:], x.dtype) for x in bark)
        OUT.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(OUT / f"{name}_v{variant}_bb.npz", bark_p=bark[0], bark_n=bark[1], bark_uv=bark[2], bark_i=bark[3],
                            bark_c=np.full((len(bark[0]), 3), 0.8, np.float32),
                            leaf_p=leaf[0], leaf_n=leaf[1], leaf_uv=leaf[2], leaf_i=leaf[3], leaf_c=leaf[4], H=a["H"], R=a["R"])
        return len(bark[3]) + len(leaf[3]), 0
    nodes, parent = colonise(a, rng)
    r, children = radii(nodes, parent, a)
    bark = tube_mesh(nodes, parent, r, children, a, lod)
    leaf = cards(nodes, parent, r, children, a, rng, lod)
    OUT.mkdir(parents=True, exist_ok=True)
    # bark ambient occlusion: limbs inside the crown are shaded
    bp = bark[0]
    z0, z1 = a["crown"][1], a["crown"][2]
    centre = np.array([0, a["H"] * (z0 + z1) / 2, 0])
    rel = (bp - centre) / np.array([a["R"], a["H"] * (z1 - z0) / 2, a["R"]]) if len(bp) else np.zeros((0, 3))
    bao = np.clip(0.45 + 0.55 * np.clip(np.linalg.norm(rel, axis=1), 0, 1) ** 1.2, 0, 1) if len(bp) else np.zeros(0)
    bao = np.where(bp[:, 1] < a["H"] * z0, 0.85, bao) if len(bp) else bao
    np.savez_compressed(OUT / f"{name}_v{variant}_{lod}.npz", bark_p=bark[0], bark_n=bark[1], bark_uv=bark[2], bark_i=bark[3],
                        bark_c=np.repeat(bao[:, None], 3, 1).astype(np.float32),
                        leaf_p=leaf[0], leaf_n=leaf[1], leaf_uv=leaf[2], leaf_i=leaf[3], leaf_c=leaf[4], H=a["H"], R=a["R"])
    return len(bark[3]) + len(leaf[3]), len(nodes)


if __name__ == "__main__":
    for name in (sys.argv[1:] or ARCH):
        for v in range(N_VARIANTS):
            for lod in ("hi", "lo", "bb"):
                tris, nn = build(name, v, lod)
                print(name, v, lod, "nodes", nn, "tris", tris, flush=True)
