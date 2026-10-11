"""Minimal, dependency-light glTF 2.0 (.glb) writer with PBR materials, embedded images, multiple UV sets,
vertex colours and EXT_mesh_gpu_instancing."""
import json, struct, io
import numpy as np

FLOAT, UINT, USHORT, UBYTE = 5126, 5125, 5123, 5121
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963
TYPE = {1: "SCALAR", 2: "VEC2", 3: "VEC3", 4: "VEC4", 16: "MAT4"}


class GLB:
    def __init__(self):
        self.g = {"asset": {"version": "2.0", "generator": "mountain-gate course builder"},
                  "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [], "materials": [],
                  "textures": [], "images": [], "samplers": [], "accessors": [], "bufferViews": [], "buffers": []}
        self.bin = io.BytesIO()
        self.ext_used = set()
        self._img_cache = {}
        self._tex_cache = {}
        self.g["samplers"].append({"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497})  # repeat
        self.g["samplers"].append({"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071})  # clamp

    def _view(self, data: bytes, target=None):
        pad = (-self.bin.tell()) % 4
        self.bin.write(b"\0" * pad)
        off = self.bin.tell()
        self.bin.write(data)
        v = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target:
            v["target"] = target
        self.g["bufferViews"].append(v)
        return len(self.g["bufferViews"]) - 1

    def accessor(self, arr, target=None, normalized=False, minmax=False):
        arr = np.ascontiguousarray(arr)
        ncomp = 1 if arr.ndim == 1 else arr.shape[1]
        ct = {np.dtype(np.float32): FLOAT, np.dtype(np.uint32): UINT, np.dtype(np.uint16): USHORT,
              np.dtype(np.uint8): UBYTE}[arr.dtype]
        bv = self._view(arr.tobytes(), target)
        a = {"bufferView": bv, "componentType": ct, "count": int(arr.shape[0]), "type": TYPE[ncomp]}
        if normalized:
            a["normalized"] = True
        if minmax:
            a["min"] = arr.min(0).tolist() if arr.ndim > 1 else [float(arr.min())]
            a["max"] = arr.max(0).tolist() if arr.ndim > 1 else [float(arr.max())]
        self.g["accessors"].append(a)
        return len(self.g["accessors"]) - 1

    def image(self, path_or_bytes, mime=None, key=None):
        key = key or (path_or_bytes if isinstance(path_or_bytes, str) else id(path_or_bytes))
        if key in self._img_cache:
            return self._img_cache[key]
        if isinstance(path_or_bytes, (bytes, bytearray)):
            data = bytes(path_or_bytes)
        else:
            data = open(path_or_bytes, "rb").read()
            mime = mime or ("image/png" if str(path_or_bytes).lower().endswith(".png") else "image/jpeg")
        bv = self._view(data)
        self.g["images"].append({"bufferView": bv, "mimeType": mime})
        self._img_cache[key] = len(self.g["images"]) - 1
        return self._img_cache[key]

    def texture(self, img_index, sampler=0):
        k = (img_index, sampler)
        if k not in self._tex_cache:
            self.g["textures"].append({"source": img_index, "sampler": sampler})
            self._tex_cache[k] = len(self.g["textures"]) - 1
        return self._tex_cache[k]

    def material(self, name, base_color=None, normal=None, orm=None, base_factor=(1, 1, 1, 1), rough=1.0, metal=0.0,
                 normal_scale=1.0, alpha_mode=None, alpha_cutoff=0.5, double_sided=False, texcoord=0, extras=None,
                 specular=None):
        m = {"name": name, "pbrMetallicRoughness": {"baseColorFactor": list(base_factor), "metallicFactor": metal,
                                                     "roughnessFactor": rough}, "doubleSided": double_sided}
        if base_color is not None:
            m["pbrMetallicRoughness"]["baseColorTexture"] = {"index": self.texture(self.image(base_color)), "texCoord": texcoord}
        if orm is not None:
            t = self.texture(self.image(orm))
            m["pbrMetallicRoughness"]["metallicRoughnessTexture"] = {"index": t, "texCoord": texcoord}
            m["occlusionTexture"] = {"index": t, "texCoord": texcoord, "strength": 0.6}
        if normal is not None:
            m["normalTexture"] = {"index": self.texture(self.image(normal)), "texCoord": texcoord, "scale": normal_scale}
        if alpha_mode:
            m["alphaMode"] = alpha_mode
            if alpha_mode == "MASK":
                m["alphaCutoff"] = alpha_cutoff
        if extras:
            m["extras"] = extras
        if specular is not None:  # KHR_materials_specular: matte surfaces (turf) reflect far less than the 4% default
            m.setdefault("extensions", {})["KHR_materials_specular"] = {"specularFactor": float(specular)}
            self.ext_used.add("KHR_materials_specular")
        self.g["materials"].append(m)
        return len(self.g["materials"]) - 1

    def mesh(self, name, primitives):
        """primitives: list of dict(pos, nrm, uv0, uv1, col, idx, material, tangents?)"""
        prims = []
        for p in primitives:
            attrs = {"POSITION": self.accessor(p["pos"].astype(np.float32), ARRAY_BUFFER, minmax=True)}
            if p.get("nrm") is not None:
                attrs["NORMAL"] = self.accessor(p["nrm"].astype(np.float32), ARRAY_BUFFER)
            if p.get("uv0") is not None:
                attrs["TEXCOORD_0"] = self.accessor(p["uv0"].astype(np.float32), ARRAY_BUFFER)
            if p.get("uv1") is not None:
                attrs["TEXCOORD_1"] = self.accessor(p["uv1"].astype(np.float32), ARRAY_BUFFER)
            for key, attr in (("col", "COLOR_0"), ("col1", "COLOR_1")):   # COLOR_1: 3DG grass density mask
                if p.get(key) is None:
                    continue
                c = p[key]
                if c.dtype != np.uint8:
                    c = (np.clip(c, 0, 1) * 255 + 0.5).astype(np.uint8)
                if c.shape[1] == 3:
                    c = np.c_[c, np.full(len(c), 255, np.uint8)]
                attrs[attr] = self.accessor(c, ARRAY_BUFFER, normalized=True)
            idx = p["idx"].astype(np.uint32).ravel()
            prim = {"attributes": attrs, "indices": self.accessor(idx, ELEMENT_ARRAY_BUFFER), "mode": 4}
            if p.get("material") is not None:
                prim["material"] = p["material"]
            prims.append(prim)
        self.g["meshes"].append({"name": name, "primitives": prims})
        return len(self.g["meshes"]) - 1

    def node(self, name, mesh=None, children=None, translation=None, rotation=None, scale=None, instances=None,
             parent=None, extras=None, scene=0):
        n = {"name": name}
        if mesh is not None:
            n["mesh"] = mesh
        if children:
            n["children"] = list(children)
        if translation is not None:
            n["translation"] = [float(v) for v in translation]
        if rotation is not None:
            n["rotation"] = [float(v) for v in rotation]
        if scale is not None:
            n["scale"] = [float(v) for v in scale]
        if extras:
            n["extras"] = extras
        if instances is not None:
            t, r, s = instances
            self.ext_used.add("EXT_mesh_gpu_instancing")
            n["extensions"] = {"EXT_mesh_gpu_instancing": {"attributes": {
                "TRANSLATION": self.accessor(t.astype(np.float32)),
                "ROTATION": self.accessor(r.astype(np.float32)),
                "SCALE": self.accessor(s.astype(np.float32))}}}
        self.g["nodes"].append(n)
        i = len(self.g["nodes"]) - 1
        if parent is None:
            while len(self.g["scenes"]) <= scene:
                self.g["scenes"].append({"nodes": []})
            self.g["scenes"][scene]["nodes"].append(i)
        else:
            self.g["nodes"][parent].setdefault("children", []).append(i)
        return i

    def save(self, path, extras=None):
        if extras:
            self.g["scenes"][0]["extras"] = extras
        if self.ext_used:
            self.g["extensionsUsed"] = sorted(self.ext_used)
        for k in ("textures", "images", "samplers", "materials", "meshes"):
            if not self.g[k]:
                del self.g[k]
        binb = self.bin.getvalue()
        binb += b"\0" * ((-len(binb)) % 4)
        self.g["buffers"] = [{"byteLength": len(binb)}]
        js = json.dumps(self.g, separators=(",", ":")).encode()
        js += b" " * ((-len(js)) % 4)
        total = 12 + 8 + len(js) + 8 + len(binb)
        with open(path, "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, total))
            f.write(struct.pack("<II", len(js), 0x4E4F534A)); f.write(js)
            f.write(struct.pack("<II", len(binb), 0x004E4942)); f.write(binb)
        return total
