"""Read a binary FBX file (version 7.x): its node tree, and the textures each material carries, as Unity imports them.

A node record is (end offset, property count, property bytes, name length, name), 32-bit fields before version 7500 and
64-bit ones from it, then its properties and child records, closed by an all-zero record. Blender writes version 7400."""
import struct, zlib
from pathlib import Path

MAGIC = b"Kaydara FBX Binary  \x00"
_SCALAR = {"Y": "<h", "C": "<?", "I": "<i", "F": "<f", "D": "<d", "L": "<q"}


class Node:
    __slots__ = ("name", "props", "children")

    def __init__(self, name, props, children):
        self.name, self.props, self.children = name, props, children

    def find(self, name):
        return next((c for c in self.children if c.name == name), None)

    def all(self, name):
        return [c for c in self.children if c.name == name]


def _props(b, i, n):
    out = []
    for _ in range(n):
        t = chr(b[i]); i += 1
        if t in _SCALAR:
            out.append(struct.unpack_from(_SCALAR[t], b, i)[0]); i += struct.calcsize(_SCALAR[t])
        elif t in "fdlib":   # array: (type, length, raw little-endian bytes)
            length, encoding, size = struct.unpack_from("<III", b, i); i += 12
            raw = b[i:i + size]; i += size
            out.append((t, length, zlib.decompress(raw) if encoding else raw))
        elif t in "SR":
            size = struct.unpack_from("<I", b, i)[0]; i += 4
            out.append(b[i:i + size]); i += size
        else:
            raise ValueError(f"FBX property type {t!r} at byte {i - 1}")
    return out, i


def _node(b, i, wide):
    head = "<QQQ" if wide else "<III"
    if i + struct.calcsize(head) + 1 > len(b):
        raise ValueError(f"FBX file truncated at byte {i}")
    end, nprops, _ = struct.unpack_from(head, b, i); i += struct.calcsize(head)
    nlen = b[i]; i += 1
    if end == 0:
        return None, i   # the null record that closes a list of nodes
    if end > len(b):
        raise ValueError(f"FBX file truncated: a node ends at byte {end} of {len(b)}")
    name = b[i:i + nlen].decode("ascii", "replace"); i += nlen
    props, i = _props(b, i, nprops)
    children = []
    while i < end:
        child, i = _node(b, i, wide)
        if child is None:
            break
        children.append(child)
    return Node(name, props, children), end


def read(path):
    """The top-level nodes of a binary FBX file (ValueError for anything else, e.g. an ASCII FBX)."""
    b = Path(path).read_bytes()
    if not b.startswith(MAGIC):
        raise ValueError(f"{path}: not a binary FBX file")
    wide = struct.unpack_from("<I", b, 23)[0] >= 7500
    i, top = 27, []
    while i < len(b):
        node, i = _node(b, i, wide)
        if node is None:
            break
        top.append(node)
    return top


def _name(node):
    """An object's name without its '\\x00\\x01Class' suffix."""
    return node.props[1].split(b"\x00\x01")[0].decode("utf-8", "replace")


def _top(top, name):
    node = next((n for n in top if n.name == name), None)
    if node is None:
        raise ValueError(f"FBX file has no {name} section")
    return node


def array(prop):
    """The values of an array property (type, length, raw bytes)."""
    t, n, raw = prop
    return struct.unpack(f"<{n}{dict(d='d', f='f', i='i', l='q', b='?')[t]}", raw)


def material_properties(top):
    """{material: {Properties70 entry (DiffuseColor, ...): its value, or a tuple of its values}}."""
    out = {}
    for n in _top(top, "Objects").all("Material"):
        p70 = n.find("Properties70")
        out[_name(n)] = {p.props[0].decode("utf-8", "replace"): p.props[4] if len(p.props) == 5 else tuple(p.props[4:])
                         for p in (p70.all("P") if p70 is not None else [])}
    return out


def faces_by_material(top):
    """{(model, material): [face as a tuple of its corners' positions, in winding order]} of every mesh, positions in
    the geometry's own frame."""
    objects, links = _top(top, "Objects"), [c.props for c in _top(top, "Connections").all("C")]
    geoms = {n.props[0]: n for n in objects.all("Geometry")}
    models = {n.props[0]: _name(n) for n in objects.all("Model")}
    materials = {n.props[0]: _name(n) for n in objects.all("Material")}
    geometry, slots = {}, {}
    for p in links:   # Geometry -> Model; Material -> Model, in slot order
        if p[0] == b"OO" and p[2] in models:
            if p[1] in geoms:
                geometry[p[2]] = geoms[p[1]]
            elif p[1] in materials:
                slots.setdefault(p[2], []).append(materials[p[1]])
    out = {}
    for mid, g in geometry.items():
        v = array(g.find("Vertices").props[0])
        corners = [tuple(v[k:k + 3]) for k in range(0, len(v), 3)]
        faces, face = [], []
        for k in array(g.find("PolygonVertexIndex").props[0]):   # the last corner of a face is stored as ~index
            face.append(~k if k < 0 else k)
            if k < 0:
                faces.append(face); face = []
        layer = g.find("LayerElementMaterial")
        per_face = layer is not None and layer.find("MappingInformationType").props[0] != b"AllSame"
        index = array(layer.find("Materials").props[0]) if layer is not None else (0,)
        names = slots.get(mid, [None])
        for fi, f in enumerate(faces):
            out.setdefault((models[mid], names[index[fi] if per_face else index[0]]), []).append(tuple(corners[c] for c in f))
    return out


def material_textures(top):
    """{material: {material property (DiffuseColor, TransparencyFactor, NormalMap, ...): texture}} of an FBX's nodes,
    a texture being {"name", "file" (its RelativeFilename, else FileName), "content" (the embedded image, b"" if none)}."""
    objects, links = _top(top, "Objects"), [c.props for c in _top(top, "Connections").all("C")]
    materials = {n.props[0]: _name(n) for n in objects.all("Material")}
    textures = {}
    for n in objects.all("Texture"):
        f = n.find("RelativeFilename") or n.find("FileName")
        textures[n.props[0]] = {"name": _name(n), "file": f.props[0].decode("utf-8", "replace") if f else "", "content": b""}
    videos = {}
    for n in objects.all("Video"):
        c = n.find("Content")
        videos[n.props[0]] = c.props[0] if c is not None and c.props and isinstance(c.props[0], bytes) else b""
    for p in links:   # Video -> Texture: the embedded image
        if p[0] == b"OO" and p[1] in videos and p[2] in textures:
            textures[p[2]]["content"] = videos[p[1]]
    out = {m: {} for m in materials.values()}
    for p in links:   # Texture -> Material property
        if p[0] == b"OP" and p[1] in textures and p[2] in materials:
            out[materials[p[2]]][p[3].decode("utf-8", "replace")] = textures[p[1]]
    return out
