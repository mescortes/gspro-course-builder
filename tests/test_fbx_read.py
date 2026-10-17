"""scripts/fbx_read.py on small binary FBX files written here (7400: 32-bit records, as Blender writes; 7500: 64-bit)."""
import struct, sys, zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fbx_read  # noqa: E402


def _prop(t, v):
    if t in "SR":
        return t.encode() + struct.pack("<I", len(v)) + v
    if t == "d":   # a zlib-compressed array, as FBX writers store large ones
        raw = zlib.compress(struct.pack(f"<{len(v)}d", *v))
        return b"d" + struct.pack("<III", len(v), 1, len(raw)) + raw
    if t == "i":   # an uncompressed array
        raw = struct.pack(f"<{len(v)}i", *v)
        return b"i" + struct.pack("<III", len(v), 0, len(raw)) + raw
    return t.encode() + struct.pack({"L": "<q", "I": "<i", "D": "<d"}[t], v)


def _node(name, props, children, start, wide):
    pb = b"".join(_prop(t, v) for t, v in props)
    pos = start + (24 if wide else 12) + 1 + len(name) + len(pb)
    body = b""
    for c in children:
        cb = _node(*c, pos, wide)
        body, pos = body + cb, pos + len(cb)
    null = b"\0" * (25 if wide else 13) if children else b""
    head = struct.pack("<QQQ" if wide else "<III", pos + len(null), len(props), len(pb))
    return head + bytes([len(name)]) + name.encode() + pb + body + null


def _fbx(nodes, version):
    wide, out = version >= 7500, fbx_read.MAGIC + b"\x1a\x00" + struct.pack("<I", version)
    for n in nodes:
        out += _node(*n, len(out), wide)
    return out + b"\0" * (25 if wide else 13)


SCENE = [
    ("Objects", [], [
        ("Geometry", [("L", 5), ("S", b"Tree\x00\x01Geometry"), ("S", b"Mesh")], [("Vertices", [("d", [0.0, 1.5, -2.0])], [])]),
        ("Material", [("L", 10), ("S", b"Bark_oak\x00\x01Material"), ("S", b"")], [("Properties70", [], [
            ("P", [("S", b"DiffuseColor"), ("S", b"Color"), ("S", b""), ("S", b"A"), ("D", 1.0), ("D", 0.5), ("D", 0.25)], []),
            ("P", [("S", b"Opacity"), ("S", b"double"), ("S", b"Number"), ("S", b""), ("D", 1.0)], [])])]),
        ("Material", [("L", 11), ("S", b"Foliage_oak\x00\x01Material"), ("S", b"")], []),
        # a quad and its back face, the second one in slot 1 (Foliage_oak); the last corner of a face is stored as ~index
        ("Geometry", [("L", 40), ("S", b"Card\x00\x01Geometry"), ("S", b"Mesh")], [
            ("Vertices", [("d", [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0])], []),
            ("PolygonVertexIndex", [("i", [0, 1, 2, ~3, 3, 2, 1, ~0])], []),
            ("LayerElementMaterial", [("I", 0)], [("MappingInformationType", [("S", b"ByPolygon")], []),
                                                  ("Materials", [("i", [0, 1])], [])])]),
        ("Model", [("L", 50), ("S", b"Tree_v0\x00\x01Model"), ("S", b"Mesh")], []),
        ("Texture", [("L", 20), ("S", b"Bark_oak_color\x00\x01Texture"), ("S", b"")],
         [("RelativeFilename", [("S", b"tree_prefabs.fbm/Bark_oak_color.jpg")], [])]),
        ("Video", [("L", 30), ("S", b"Bark_oak_color\x00\x01Video"), ("S", b"Clip")], [("Content", [("R", b"\xff\xd8jpeg")], [])]),
        ("Texture", [("L", 21), ("S", b"Unlinked\x00\x01Texture"), ("S", b"")], []),
    ]),
    ("Connections", [], [
        ("C", [("S", b"OO"), ("L", 30), ("L", 20)], []),
        ("C", [("S", b"OP"), ("L", 20), ("L", 10), ("S", b"DiffuseColor")], []),
        ("C", [("S", b"OP"), ("L", 21), ("L", 99), ("S", b"NormalMap")], []),   # a material that is not there
        ("C", [("S", b"OO"), ("L", 40), ("L", 50)], []),
        ("C", [("S", b"OO"), ("L", 10), ("L", 50)], []),
        ("C", [("S", b"OO"), ("L", 11), ("L", 50)], []),
    ]),
]


@pytest.mark.parametrize("version", [7400, 7500])
def test_reads_nodes_arrays_and_material_textures(tmp_path, version):
    p = tmp_path / "t.fbx"
    p.write_bytes(_fbx(SCENE, version))
    top = fbx_read.read(p)
    assert [n.name for n in top] == ["Objects", "Connections"]
    t, n, raw = top[0].find("Geometry").find("Vertices").props[0]
    assert (t, n, struct.unpack("<3d", raw)) == ("d", 3, (0.0, 1.5, -2.0))
    assert fbx_read.material_textures(top) == {"Bark_oak": {"DiffuseColor": {
        "name": "Bark_oak_color", "file": "tree_prefabs.fbm/Bark_oak_color.jpg", "content": b"\xff\xd8jpeg"}}, "Foliage_oak": {}}
    assert fbx_read.material_properties(top) == {"Bark_oak": {"DiffuseColor": (1.0, 0.5, 0.25), "Opacity": 1.0}, "Foliage_oak": {}}
    a, b, c, d = (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)
    assert fbx_read.faces_by_material(top) == {("Tree_v0", "Bark_oak"): [(a, b, c, d)], ("Tree_v0", "Foliage_oak"): [(d, c, b, a)]}


def test_a_file_that_is_not_binary_fbx_is_refused(tmp_path):
    p = tmp_path / "ascii.fbx"
    p.write_text("; FBX 7.4.0 project file\nFBXHeaderExtension:  {\n}\n")
    with pytest.raises(ValueError, match="not a binary FBX"):
        fbx_read.read(p)


def test_a_truncated_file_or_a_missing_section_is_an_error(tmp_path):
    data = _fbx(SCENE, 7400)
    p = tmp_path / "cut.fbx"
    for cut in (40, len(data) // 2):
        p.write_bytes(data[:cut])
        with pytest.raises(ValueError, match="truncated"):
            fbx_read.read(p)
    p.write_bytes(_fbx(SCENE[:1], 7400))   # no Connections
    with pytest.raises(ValueError, match="no Connections section"):
        fbx_read.material_textures(fbx_read.read(p))
