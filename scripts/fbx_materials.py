"""Material and mesh preparation before an FBX export, run inside Blender (export_fbx_blender.py, glb_to_fbx_blender.py).

Blender's FBX exporter writes a material's textures only from Image Texture nodes wired straight into its Principled
BSDF (node_shader_utils.PrincipledBSDFWrapper: Base Color -> DiffuseColor, Alpha -> TransparencyFactor, Normal Map ->
NormalMap), and the BSDF's Base Color value as DiffuseColor. The glTF importer feeds Base Color through a vertex-colour
multiply (a MIX node) and a cut-out alpha through a MATH node, so the FBX files carried no colour or alpha textures and
Blender's hidden default colour, 0.8, which Unity multiplies into the texture. Unity takes the trees' and the buildings'
materials from the FBX. glTF images are packed (they have no file): the FBX exporter names an embedded image after its
file path, and with none every image shared one name, so the tree prefabs embedded one image for all their materials.
"""
import os
import bpy

# the course images' JPEG quality: what export_fbx_blender.py has always written (an image Blender has not loaded is
# saved at 75 whatever file_format says), so the package's texture files stay byte for byte the same
JPEG_QUALITY = 90


def _image_output(socket, output):
    """The `output` socket ('Color' or 'Alpha') of the nearest Image Texture node upstream of `socket`, or None."""
    todo, seen = [link.from_node for link in socket.links], set()
    while todo:
        node = todo.pop(0)
        if node.name in seen:
            continue
        seen.add(node.name)
        if node.type == "TEX_IMAGE" and node.image is not None:
            return node.outputs[output]
        todo += [link.from_node for s in node.inputs for link in s.links]
    return None


def _colour_factor(socket):
    """The constant colours multiplied into an image on its way to `socket` (a glTF baseColorFactor), white if none."""
    f, node = [1.0, 1.0, 1.0, 1.0], socket.links[0].from_node
    while node is not None and node.type == "MIX" and node.blend_type == "MULTIPLY":
        nxt = None
        for s in node.inputs:
            if s.type != "RGBA" or not s.enabled:
                continue
            if not s.is_linked:
                f = [a * b for a, b in zip(f, s.default_value)]
            elif _image_output(s, "Color") is not None:
                nxt = s.links[0].from_node
        node = nxt
    return f


def _bsdf(material):
    if not material.use_nodes:
        return None
    return next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def wire_images_straight():
    """Wire each material's colour and alpha images straight into its Principled BSDF, its Base Color value set to the
    glTF colour factor. The vertex-colour multiply and the alpha math go: an FBX material has no place for them (and
    Unity's Standard shader ignores vertex colours). Returns the number of inputs rewired."""
    n = 0
    for m in bpy.data.materials:
        bsdf = _bsdf(m)
        if bsdf is None:
            continue
        for name, output in (("Base Color", "Color"), ("Alpha", "Alpha")):
            s = bsdf.inputs[name]
            image = _image_output(s, output) if s.is_linked else None
            if image is None:
                continue
            if name == "Base Color":   # also when the image is wired straight already (the value is still the default)
                s.default_value = _colour_factor(s)
            if s.links[0].from_node.type != "TEX_IMAGE":
                m.node_tree.links.new(image, s)
                n += 1
    return n


def double_sided_faces():
    """FBX has no double-sided flag and Unity's Standard shader culls back faces: give every face of a material the glTF
    marks doubleSided (Blender: backface culling off; the tree prefabs' foliage cards) a reversed twin. Returns the
    number of faces added."""
    import bmesh
    n = 0
    for mesh in bpy.data.meshes:
        two = {i for i, m in enumerate(mesh.materials) if m is not None and not m.use_backface_culling}
        if not two:
            continue
        bm = bmesh.new()
        bm.from_mesh(mesh)
        faces = [f for f in bm.faces if f.material_index in two]
        if faces:
            copies = [g for g in bmesh.ops.duplicate(bm, geom=faces)["geom"] if isinstance(g, bmesh.types.BMFace)]
            bmesh.ops.reverse_faces(bm, faces=copies)
            bm.to_mesh(mesh)
            n += len(copies)
        bm.free()
    return n


def save_course_images(directory):
    """Write every packed image to `directory` as <image name>.jpg (quality JPEG_QUALITY) and point the image at it,
    so the course FBX files reference real texture files next to them (path_mode RELATIVE). The image is loaded first:
    Blender ignores file_format on an image it has not loaded and writes its packed bytes, PNG or JPEG. Returns the
    count."""
    os.makedirs(directory, exist_ok=True)
    n = 0
    for img in bpy.data.images:
        if img.source != "FILE" or (img.filepath and os.path.isfile(bpy.path.abspath(img.filepath))):
            continue
        img.size[0]   # loads the image
        img.filepath_raw = os.path.join(directory, f"{bpy.path.clean_name(img.name)}.jpg")
        img.file_format = "JPEG"
        img.save(quality=JPEG_QUALITY)
        n += 1
    return n


def _roles():
    """{image name: '<material>_color' or '<material>_normal'}: the first material wiring it into its BSDF names it."""
    names = {}
    for m in bpy.data.materials:
        bsdf = _bsdf(m)
        if bsdf is None:
            continue
        for name, role in (("Base Color", "color"), ("Normal", "normal")):
            s = bsdf.inputs[name]
            image = _image_output(s, "Color") if s.is_linked else None
            if image is not None:
                names.setdefault(image.node.image.name, f"{m.name}_{role}")
    return names


def name_packed_images(directory):
    """Give every packed image its own file name, <material>_color / _normal with the extension of its packed bytes
    (.png or .jpg), and write it there as it is: the FBX exporter embeds the packed bytes under that name (embed_textures
    with path_mode COPY). Returns the count."""
    names = _roles()
    os.makedirs(directory, exist_ok=True)
    n = 0
    for img in bpy.data.images:
        if img.source != "FILE" or img.packed_file is None:
            continue
        ext = "png" if img.packed_file.data[:4] == b"\x89PNG" else "jpg"
        img.filepath_raw = os.path.join(directory, f"{bpy.path.clean_name(names.get(img.name, img.name))}.{ext}")
        img.save()   # not loaded: the packed bytes, unchanged
        n += 1
    return n
