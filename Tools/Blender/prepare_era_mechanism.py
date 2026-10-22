"""Prepare articulated Tripo mechanisms without regenerating their bodies.

Lightweight: python this.py --plan plan.json --stage inspect|textures
Leased Blender only: blender -b -t 2 --python-exit-code 1 --python this.py --
    --plan plan.json --stage prepare [--render]

Selectors use the ORIGINAL glTF XYZ coordinates (Y up). They assign whole
source triangles, preserving their original normals, UVs and material indices.
Only explicitly selected fused string triangles are replaced. DCC string
segments are independent, fixed-length parts; runtime rotations/translation
follow measured arm tips and a constant-length slack curve.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct
import sys
import zlib

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("mechanism_static", Path(__file__).with_name("prepare_era_asset.py"))
static = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(static)


def output_folder(plan, entry):
    identity = {"entry": entry, "source_sha256": static.digest(static.absolute(entry["source"])),
                "tool_sha256": static.digest(__file__), "version": 1}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    return static.absolute(plan["output_root"]) / entry["asset_id"] / ("h" + fingerprint)


def source_geometry(entry):
    """These first canonical mechanisms each contain one identity mesh node."""
    result = static.inspect(entry)
    if result["errors"] or not result["full_pbr"] or result["skins"]:
        raise ValueError("Expected intact opaque PBR static source: " + str(result))
    d, binary = static.glb(static.absolute(entry["source"]))
    nodes = [n for n in d.get("nodes", []) if "mesh" in n]
    if len(nodes) != 1 or len(d.get("nodes", [])) != 1 or any(k in nodes[0] for k in ("matrix", "translation", "rotation", "scale")):
        raise ValueError("Source node transform/multiple meshes require explicit normalization support")

    def accessor(index):
        a = d["accessors"][index]
        if "sparse" in a or a.get("normalized"):
            raise ValueError("Unsupported sparse/normalized accessor")
        v = d["bufferViews"][a["bufferView"]]
        count = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
        dtype = np.dtype({5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}[a["componentType"]])
        offset = a.get("byteOffset", 0) + v.get("byteOffset", 0)
        stride = v.get("byteStride", count * dtype.itemsize)
        if offset + (a["count"] - 1) * stride + count * dtype.itemsize > len(binary):
            raise ValueError("Accessor outside binary payload")
        return np.ndarray((a["count"], count), dtype=dtype, buffer=binary,
                          offset=offset, strides=(stride, dtype.itemsize)).copy()

    vertices, normals, uvs, faces, materials = [], [], [], [], []
    offset = 0
    for p in d["meshes"][nodes[0]["mesh"]]["primitives"]:
        if "NORMAL" not in p["attributes"]:
            raise ValueError("Source normals are required")
        positions = accessor(p["attributes"]["POSITION"])
        indices = accessor(p["indices"]).reshape(-1, 3).astype(np.int64)
        vertices.extend(positions)
        normals.extend(accessor(p["attributes"]["NORMAL"]))
        uvs.extend(accessor(p["attributes"]["TEXCOORD_0"]))
        faces.extend(indices + offset)
        materials.extend([p["material"]] * len(indices))
        offset += len(positions)
    return {"inspection": result, "vertices": np.array(vertices, dtype=float),
            "normals": np.array(normals, dtype=float), "uvs": np.array(uvs),
            "faces": np.array(faces), "materials": np.array(materials)}


def normalized_basis(entry, vertices):
    # glTF (X,Y,Z) -> Blender (X,-Z,Y), then an explicit authoring yaw.
    angle = math.radians(entry["yaw_degrees"])
    yaw = np.array([[math.cos(angle), -math.sin(angle), 0],
                    [math.sin(angle), math.cos(angle), 0], [0, 0, 1]])
    basis = yaw @ np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]])
    points = vertices @ basis.T
    low, high = points.min(0), points.max(0)
    extent = high - low
    measured = extent[2] if entry["measure"] == "height" else max(extent[:2])
    scale = float(entry["target_cm"]) / 100 / measured
    centre = np.array([(low[0] + high[0]) / 2, (low[1] + high[1]) / 2, low[2]])
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid physical normalization")
    return basis, scale, centre


def normalized_point(point, basis):
    rotation, scale, centre = basis
    return (np.asarray(point) @ rotation.T - centre) * scale


def ue(point):
    return [float(point[0] * 100), float(-point[1] * 100), float(point[2] * 100)]


def inside(points, selector):
    selected = np.ones(len(points), dtype=bool)
    if "minimum" in selector:
        selected &= np.all(points >= np.asarray(selector["minimum"]), axis=1)
    if "maximum" in selector:
        selected &= np.all(points <= np.asarray(selector["maximum"]), axis=1)
    # Plane convention dot(normal, p) >= offset; permits angled exclusions.
    for plane in selector.get("planes", []):
        selected &= points @ np.asarray(plane[:3]) >= plane[3]
    if "segment" in selector:
        a, b = map(np.asarray, selector["segment"])
        ab = b - a
        t = np.clip((points - a) @ ab / np.dot(ab, ab), 0, 1)
        selected &= np.linalg.norm(points - (a + t[:, None] * ab), axis=1) <= selector["radius"]
    return selected


def partition(entry, geometry):
    centroids = geometry["vertices"][geometry["faces"]].mean(1)
    labels = np.full(len(centroids), entry.get("remainder_part", "frame"), dtype=object)
    claimed = np.zeros(len(centroids), dtype=bool)
    for selection in entry.get("selections", []):
        mask = np.zeros(len(centroids), dtype=bool)
        for region in selection["regions"]:
            mask |= inside(centroids, region)
        mask &= ~claimed
        if not mask.any():
            raise ValueError("Empty source partition: " + selection["part"])
        labels[mask] = selection["part"]
        claimed |= mask
    return labels


def cut_boundary_loops(geometry, selected):
    """Close only boundaries created by splitting; original source holes stay."""
    _, representatives, weld = np.unique(np.round(geometry["vertices"], 6), axis=0,
                                         return_index=True, return_inverse=True)
    faces = weld[geometry["faces"]]
    def edges(triangles):
        return [(int(t[i]), int(t[(i+1)%3])) for t in triangles for i in range(3)]
    all_counts = Counter(tuple(sorted(e)) for e in edges(faces))
    selected_edges = edges(faces[selected])
    counts = Counter(tuple(sorted(e)) for e in selected_edges)
    direction = {tuple(sorted(e)): e for e in selected_edges}
    remaining = {e for e, count in counts.items() if count == 1 and all_counts[e] == 2}
    adjacency = defaultdict(set)
    for a, b in remaining:
        adjacency[a].add(b)
        adjacency[b].add(a)
    loops = []
    while remaining:
        a, b = next(iter(remaining))
        chain = [a]
        current = a
        while adjacency[current]:
            nxt = min(adjacency[current])
            key = tuple(sorted((current, nxt)))
            remaining.remove(key)
            adjacency[current].remove(nxt)
            adjacency[nxt].remove(current)
            if nxt in chain:
                start = chain.index(nxt)
                loop = chain[start:]
                if len(loop) >= 3:
                    first = tuple(sorted((loop[0], loop[1])))
                    if direction[first] == (loop[0], loop[1]):
                        loop.reverse()  # Cap faces face opposite the cut edge.
                    loops.append([int(representatives[i]) for i in loop])
                chain = chain[:start+1]
            else:
                chain.append(nxt)
            current = nxt
    return loops


def top_surface(geometry, point, basis):
    """Actual vertical triangle intersection, not a bounds-based platform."""
    positions = normalized_point(geometry["vertices"], basis)
    tri = positions[geometry["faces"]]
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    x, y = point[:2]
    den = (b[:, 1]-c[:, 1])*(a[:, 0]-c[:, 0]) + (c[:, 0]-b[:, 0])*(a[:, 1]-c[:, 1])
    valid = np.abs(den) > 1e-10
    den = np.where(valid, den, 1)
    wa = ((b[:, 1]-c[:, 1])*(x-c[:, 0]) + (c[:, 0]-b[:, 0])*(y-c[:, 1]))/den
    wb = ((c[:, 1]-a[:, 1])*(x-c[:, 0]) + (a[:, 0]-c[:, 0])*(y-c[:, 1]))/den
    wc = 1-wa-wb
    valid &= (wa >= -1e-8) & (wb >= -1e-8) & (wc >= -1e-8)
    if not valid.any():
        raise ValueError("No actual platform surface under sample")
    heights = wa*a[:, 2] + wb*b[:, 2] + wc*c[:, 2]
    return float(heights[valid].max())


def projection(geometry, labels, path):
    """Small geometry diagnostic; no Blender/render slot is used."""
    from PIL import Image, ImageDraw
    palette = {"frame": "#a1a3a9", "arm_left": "#497dca", "arm_right": "#d39a4e",
               "bolt": "#dc6459", "replace_string": "#bc65bf", "platform": "#a7ab9d"}
    v, f = geometry["vertices"], geometry["faces"]
    image = Image.new("RGB", (1800, 650), "#f5f5f5")
    draw = ImageDraw.Draw(image)
    for panel, (a, c, depth, title) in enumerate(((0, 1, 2, "front X/Y"), (2, 1, 0, "side Z/Y"), (0, 2, 1, "top X/Z"))):
        lower, upper = v[:, [a, c]].min(0), v[:, [a, c]].max(0)
        scale = 530/max(upper-lower)
        centre = (lower+upper)/2
        order = np.argsort(v[f][:, :, depth].mean(1))
        for i in order:
            polygon = [(panel*600+300+(p[a]-centre[0])*scale, 325-(p[c]-centre[1])*scale) for p in v[f[i]]]
            draw.polygon(polygon, fill=palette.get(labels[i], "#86ab9c"))
        draw.text((panel*600+12, 12), title, fill="black")
    draw.text((12, 625), "blue/orange: arms | red: source bolt | purple: replaced fused strings | gray: original frame", fill="black")
    image.save(path)


def inspect_entry(plan, entry):
    geometry = source_geometry(entry)
    basis = normalized_basis(entry, geometry["vertices"])
    labels = partition(entry, geometry)
    folder = output_folder(plan, entry)
    folder.mkdir(parents=True, exist_ok=True)
    projection(geometry, labels, folder/"partition.png")
    points = normalized_point(geometry["vertices"], basis)
    result = {"asset_id": entry["asset_id"], "status": "source_partition_plan_only",
              "source": geometry["inspection"]["source"], "full_pbr": True,
              "source_triangles": len(labels), "dimensions_cm": ((points.max(0)-points.min(0))*100).tolist(),
              "parts": {str(k): int(np.count_nonzero(labels == k)) for k in np.unique(labels)},
              "notes": ["No Blender geometry or Unreal packages produced by inspect."]}
    if entry.get("crew_samples_cm"):
        samples = []
        for x, y in entry["crew_samples_cm"]:
            z = top_surface(geometry, [x/100, -y/100], basis) * 100
            samples.append([x, y, z])
        result["crew_surface_samples_cm"] = samples
        result["crew_anchor_cm"] = [0, 0, max(p[2] for p in samples)]
    static.write(folder/"inspection.json", result)
    static.write(folder/"input_spec.json", entry)
    return result


def platform_entry(entry):
    geometry = source_geometry(entry)
    basis = normalized_basis(entry, geometry["vertices"])
    highest = max(top_surface(geometry, [x/100, -y/100], basis)*100
                  for x, y in entry["crew_samples_cm"])
    return dict(entry, mechanism={"status": "platform_only_requires_independent_skeletal_archer"},
                anchors_cm={"crew": [0, 0, highest]})


def constant_png(path, rgb):
    # Keep Blender self-contained; no ABI-specific Pillow extension is needed.
    def chunk(kind, payload):
        return struct.pack(">I", len(payload))+kind+payload+struct.pack(">I", zlib.crc32(kind+payload))
    payload = (b"\0"+bytes(rgb)*2)*2
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))+
                          chunk(b"IDAT", zlib.compress(payload))+chunk(b"IEND", b""))


def limb_point(point, pivot, angle):
    a = math.radians(angle)
    rotation = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    return (point-pivot) @ rotation.T + pivot


def rope_segments(a, b, total_length, segments):
    """Equal arc-length sampling of a downward curve; no stretching controls."""
    if np.linalg.norm(b-a) > total_length + 1e-5:
        raise ValueError("String end distance exceeds authored length")
    ts = np.linspace(0, 1, 513)
    def curve(sag):
        points = a + ts[:, None]*(b-a)
        points[:, 2] -= sag*np.sin(math.pi*ts)
        return points
    low, high = 0., total_length
    for _ in range(28):
        middle = (low+high)/2
        length = np.linalg.norm(np.diff(curve(middle), axis=0), axis=1).sum()
        if length < total_length:
            low = middle
        else:
            high = middle
    path = curve((low+high)/2)
    distances = np.r_[0., np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
    values = np.linspace(0, distances[-1], segments+1)
    return np.array([np.interp(values, distances, path[:, i]) for i in range(3)]).T


def direction_rotation(direction):
    # Blender XYZ Euler [0,pitch,yaw] rotates +X onto this vector.
    v = direction / np.linalg.norm(direction)
    return [0., -math.asin(float(v[2])), math.atan2(float(v[1]), float(v[0]))]


def sampled_keys(keys, duration):
    times = sorted(set([round(float(t), 8) for t in np.linspace(0, duration, 101)] +
                       [float(k[0]) for k in keys]))
    result = []
    for time in times:
        for index in range(1, len(keys)):
            a, b = keys[index-1], keys[index]
            if time <= b[0]+1e-8:
                t = max(0., min(1., (time-a[0])/(b[0]-a[0])))
                result.append((time, a[1]+(b[1]-a[1])*t*t*(3-2*t)))
                break
    return result


def prepare_entry(plan, entry, render=False):
    import bpy
    from mathutils import Euler, Matrix, Vector
    if entry["profile"] == "archer_platform":
        # The static helper retains exact PBR and reports pending crew assembly.
        platform = platform_entry(entry)
        return static.prepare_geometry(platform, plan["output_root"], render)
    if entry["profile"] != "ballista":
        raise ValueError("No mechanical preparation profile for this asset yet")
    geometry = source_geometry(entry)
    basis = normalized_basis(entry, geometry["vertices"])
    labels = partition(entry, geometry)
    folder = output_folder(plan, entry)
    folder.mkdir(parents=True, exist_ok=True)
    if (folder/"mechanism_manifest.json").exists():
        raise ValueError("Prepared candidate exists; use a new revision rather than overwrite")
    texture_report = static.read(static.folder(entry, plan["output_root"])/"textures.json")
    if texture_report["source"]["sha256"] != geometry["inspection"]["source"]["sha256"]:
        raise ValueError("Texture source does not match geometry")
    materials = texture_report["materials"]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system, scene.unit_settings.scale_length = "METRIC", 1
    scene.render.threads_mode, scene.render.threads = "FIXED", 2
    # Import only to obtain the existing Blender PBR graphs; source mesh arrays
    # below preserve original per-corner UV and normals without re-unwrapping.
    bpy.ops.import_scene.gltf(filepath=str(static.absolute(entry["source"])))
    original_materials = []
    for row in materials:
        material = bpy.data.materials.get(row["source_name"])
        if material is None:
            raise ValueError("Source PBR material name was not imported")
        material.name = row["slot_name"]
        original_materials.append(material)
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    vertices = normalized_point(geometry["vertices"], basis)
    normals = geometry["normals"] @ basis[0].T
    objects, exports, parts = {}, {}, []
    pivots = {name: normalized_point(value, basis) for name, value in entry["pivots_gltf"].items()}

    def export_mesh(obj, identifier, rows):
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        # Export local geometry at identity; runtime supplies the measured pivot.
        saved = obj.matrix_world.copy()
        obj.matrix_world = Matrix.Identity(4)
        bpy.context.view_layer.update()
        path = folder/("SM_"+entry["asset_id"]+"_"+identifier+".fbx")
        bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, object_types={"MESH"},
                                apply_unit_scale=True, apply_scale_options="FBX_SCALE_UNITS",
                                axis_forward="X", axis_up="Z", use_mesh_modifiers=False,
                                bake_anim=False, path_mode="STRIP", embed_textures=False)
        points = np.array([v.co[:] for v in obj.data.vertices])
        low, high = points.min(0), points.max(0)
        obj.data.calc_loop_triangles()
        record = {"id": identifier, "exports": {"fbx": static.record(path)},
                  "materials": rows, "triangles": len(obj.data.loop_triangles),
                  "bounds_cm": {"minimum": [low[0]*100, -high[1]*100, low[2]*100],
                                "maximum": [high[0]*100, -low[1]*100, high[2]*100]}}
        exports[identifier] = record
        obj.matrix_world = saved
        return record

    for name in ("frame", "arm_left", "arm_right", "bolt"):
        selected = np.flatnonzero(labels == name)
        if not len(selected):
            raise ValueError("Required actual source part empty: "+name)
        source_faces = geometry["faces"][selected]
        used, remap = np.unique(source_faces, return_inverse=True)
        pivot = pivots.get(name, np.zeros(3))
        local_vertices = (vertices[used]-pivot).tolist()
        local_faces = remap.reshape(-1, 3).tolist()
        cap_count = 0
        cap_uvs = []
        if entry.get("cap_cut_boundaries"):
            for loop in cut_boundary_loops(geometry, selected):
                ring = vertices[loop]-pivot
                centre = ring.mean(0)
                start = len(local_vertices)
                local_vertices.extend(ring.tolist())
                local_vertices.append(centre.tolist())
                centre_index = start+len(loop)
                # Small nonplanar cut loops form a closed fan. These new caps
                # never replace source faces or alter their UV/normal records.
                uv_mean = geometry["uvs"][loop].mean(0).tolist()
                for i in range(len(loop)):
                    local_faces.append([start+i, start+(i+1)%len(loop), centre_index])
                    cap_uvs.append(uv_mean)
                    cap_count += 1
        data = bpy.data.meshes.new("Source_"+name)
        data.from_pydata(local_vertices, [], local_faces)
        data.update()
        uv = data.uv_layers.new(name="UVMap")
        for m in original_materials:
            data.materials.append(m)
        corner_normals = []
        for polygon, face_id in zip(data.polygons, selected):
            polygon.material_index = int(geometry["materials"][face_id])
            polygon.use_smooth = True
            for loop_index, source_index in zip(polygon.loop_indices, geometry["faces"][face_id]):
                # glTF UV image origin differs from Blender's convention.
                u, v = geometry["uvs"][source_index]
                uv.data[loop_index].uv = (u, 1-v)
                corner_normals.append(normals[source_index])
        for polygon, (u, v) in zip(list(data.polygons)[len(selected):], cap_uvs):
            polygon.material_index = 0
            polygon.use_smooth = False
            for loop_index in polygon.loop_indices:
                uv.data[loop_index].uv = (u, 1-v)
                corner_normals.append(np.array(polygon.normal))
        data.normals_split_custom_set([normal.tolist() for normal in corner_normals])
        obj = bpy.data.objects.new(name, data)
        scene.collection.objects.link(obj)
        obj.location = Vector(pivot)
        objects[name] = obj
        export_mesh(obj, name, materials)["authored_cut_cap_triangles"] = cap_count
        parts.append({"id": name, "mesh_id": name, "translation_cm": ue(pivot)})

    # One reusable straight cylinder mesh per side; segment transforms animate
    # the continuous curve. Procedural rope is separate from the original PBR.
    tex = folder/"rope_base_color.png"
    constant_png(tex, (112, 89, 54))
    rope_row = {"slot_name": "M_AuthoredString", "source_name": "M_AuthoredString",
                "textures": {"base_color": static.record(tex)}, "double_sided": False,
                "base_color_factor": [1, 1, 1, 1], "roughness_factor": .93,
                "metallic_factor": 0., "normal_scale": 1., "occlusion_strength": 1.,
                "emissive_factor": [0, 0, 0]}
    rope_material = bpy.data.materials.new(rope_row["slot_name"])
    rope_material.diffuse_color = (.16, .1, .04, 1)
    rope_material.use_nodes = True
    shader = rope_material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (.16, .1, .04, 1)
    shader.inputs["Roughness"].default_value = .93
    duration = entry["duration"]
    channels = []
    for side, sign in (("left", -1), ("right", 1)):
        arm_id = "arm_"+side
        motion_keys = sampled_keys(entry["arm_angle_keys"], duration)
        frames = [{"time": t, "rotation_degrees": [0, -sign*angle, 0]}
                  for t, angle in motion_keys]
        channels.append({"part": arm_id, "keyframes": frames})
        tip = normalized_point(entry["string_gltf"][side], basis)
        centre = normalized_point(entry["string_gltf"]["centre"], basis)
        pivot = pivots[arm_id]
        count = entry.get("string_segments_per_side", 12)
        total_length = np.linalg.norm(tip-centre)*1.004
        segment_length = total_length/count
        bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=entry["string_radius_cm"]/100,
                                            depth=segment_length*1.025)
        template = bpy.context.object
        template.name = "string_"+side
        template.rotation_euler = (0, math.pi/2, 0)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        for vertex in template.data.vertices:
            vertex.co.x += segment_length/2
        template.data.materials.append(rope_material)
        export_mesh(template, "string_"+side, [rope_row])
        bpy.data.objects.remove(template, do_unlink=True)
        reference = rope_segments(tip, centre, total_length, count)
        segment_objects = []
        for index in range(count):
            name = "string_%s_%02d" % (side, index)
            # Mesh is loaded from the just-exported shared cylinder data below.
            # Keep a local cylinder copy for DCC inspection/animation rendering.
            bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=entry["string_radius_cm"]/100,
                                                depth=segment_length*1.025)
            obj = bpy.context.object
            obj.name = name
            obj.rotation_euler = (0, math.pi/2, 0)
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
            for vertex in obj.data.vertices:
                vertex.co.x += segment_length/2
            obj.data.materials.append(rope_material)
            ready_rotation = Euler(direction_rotation(reference[index+1]-reference[index]), "XYZ")
            obj.location = Vector(reference[index])
            obj.rotation_euler = ready_rotation
            segment_objects.append(obj)
            # Euler with roll=0: UE pitch reverses Blender Y, yaw reverses Z.
            parts.append({"id": name, "mesh_id": "string_"+side,
                          "translation_cm": ue(reference[index]),
                          "rotation_degrees": [-math.degrees(ready_rotation.y),
                                               -math.degrees(ready_rotation.z), 0]})
        segment_frames = [[] for _ in range(count)]
        draw_keys = sampled_keys(entry["nock_forward_keys_cm"], duration)
        for time, angle in motion_keys:
            actual_tip = limb_point(tip, pivot, sign*angle)
            # The nock travels toward the released bow plane, then is drawn
            # back; endpoints are physical part coordinates, not screen hacks.
            draw = float(np.interp(time, [k[0] for k in draw_keys], [k[1] for k in draw_keys]))/100
            actual_centre = centre + np.array([draw, 0, 0])
            curve = rope_segments(actual_tip, actual_centre, total_length, count)
            for index in range(count):
                ready_rotation = Euler(direction_rotation(reference[index+1]-reference[index]), "XYZ").to_quaternion()
                rotation = Euler(direction_rotation(curve[index+1]-curve[index]), "XYZ").to_quaternion()
                # Runtime composes ReadyRotation * DeltaRotation.
                delta = (ready_rotation.inverted() @ rotation).to_euler("XYZ")
                segment_frames[index].append({"time": time,
                    "translation_cm": ue(curve[index]-reference[index]),
                    "rotation_degrees": [-math.degrees(delta.y), -math.degrees(delta.z), math.degrees(delta.x)]})
        for obj, frames in zip(segment_objects, segment_frames):
            channels.append({"part": obj.name, "keyframes": frames})
    # The canonical visible metal bolt tip is retained. Its shaft is fused into
    # the rail in the source, so add only the necessary independent wooden shaft.
    if entry.get("bolt_shaft_gltf"):
        a, b = [normalized_point(p, basis) for p in entry["bolt_shaft_gltf"]]
        centre = (a+b)/2
        bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=entry["bolt_shaft_radius_cm"]/100,
                                            depth=float(np.linalg.norm(b-a)))
        shaft = bpy.context.object
        shaft.name = "bolt_shaft"
        shaft.rotation_euler = Vector(b-a).to_track_quat("Z", "Y").to_euler()
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        shaft.data.materials.append(rope_material)
        shaft.location = Vector(centre)
        export_mesh(shaft, "bolt_shaft", [rope_row])
        parts.append({"id": "bolt_shaft", "mesh_id": "bolt_shaft", "parent_part": "bolt",
                      "translation_cm": ue(centre-pivots["bolt"])})
        shaft.parent = objects["bolt"]
        shaft.location = Vector(centre-pivots["bolt"])
    channels.append({"part": "bolt", "keyframes": [{"time": 0, "visible": False},
                     {"time": duration*.72, "visible": False},
                     {"time": duration*.78, "visible": True}, {"time": duration, "visible": True}]})
    if len(channels) > 48:
        raise ValueError("Runtime motion channel limit exceeded")
    fire_animation = {"duration": duration, "channels": channels}
    runtime_parts = parts
    muzzle_point = normalized_point(entry["muzzle_gltf"], basis)
    manifest = {"schema_version": 1, "asset_id": entry["asset_id"], "kind": "mechanical_turret",
                "status": "mechanism_prepared_pending_unreal", "source": geometry["inspection"]["source"],
                "tool": static.record(__file__), "meshes": list(exports.values()),
                "parts": runtime_parts, "muzzle": {"part": "frame", "translation_cm": ue(muzzle_point)},
                "fire_animation": fire_animation,
                "source_partition": {str(k): int(np.count_nonzero(labels == k)) for k in np.unique(labels)},
                "source_surface_policy": "All original triangles retained except explicit fused-string selection; original per-corner UV and normals copied.",
                "authored_geometry": "Two reusable rope cylinder meshes and an independent wooden bolt shaft; original metal tip retained.",
                "remaining": ["actual_DCC_shape_and_source_partition", "actual_Unreal_import", "actual_gameplay"],
                "production_approved": False}
    # Pose every DCC part using the very same exported runtime data.
    by_name = {o.name: o for o in scene.objects if o.type == "MESH"}
    for part in parts:
        obj = by_name[part["id"]]
        ready = obj.matrix_world.copy()
        matching = [c for c in channels if c["part"] == part["id"]]
        if not matching:
            continue
        for frame in matching[0]["keyframes"]:
            delta_t = frame.get("translation_cm", [0, 0, 0])
            pitch, yaw, roll = frame.get("rotation_degrees", [0, 0, 0])
            rotation = Euler((math.radians(roll), -math.radians(pitch), -math.radians(yaw)), "XYZ").to_quaternion()
            obj.location = ready.translation + Vector((delta_t[0]/100, -delta_t[1]/100, delta_t[2]/100))
            obj.rotation_mode = "QUATERNION"
            obj.rotation_quaternion = ready.to_quaternion() @ rotation
            f = round(frame["time"]*60)
            obj.keyframe_insert("location", frame=f)
            obj.keyframe_insert("rotation_quaternion", frame=f)
            for visible_part in [obj] + list(obj.children_recursive):
                visible_part.hide_render = not frame.get("visible", True)
                visible_part.keyframe_insert("hide_render", frame=f)
    scene.render.fps = 60
    scene.frame_end = round(duration*60)
    scene.frame_set(scene.frame_end)
    blend = folder/(entry["asset_id"]+"_mechanism.blend")
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    manifest["blend"] = static.record(blend)
    if render:
        # Reuse root's established camera/light helper once on a temporary
        # joined copy at Ready. Animating components remain intact in the blend.
        copies = []
        for obj in by_name.values():
            copy = obj.copy()
            copy.data = obj.data.copy()
            copy.animation_data_clear()
            scene.collection.objects.link(copy)
            copies.append(copy)
            obj.hide_render = True
        bpy.ops.object.select_all(action="DESELECT")
        for obj in copies:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = copies[0]
        bpy.ops.object.join()
        joined = bpy.context.object
        static.render_preview(bpy, joined, folder)
        bpy.data.objects.remove(joined, do_unlink=True)
        for obj in by_name.values():
            obj.hide_render = False
        scene.frame_set(0)
        scene.render.filepath = str(folder/"preview_release_back.png")
        bpy.ops.render.render(write_still=True)
    static.write(folder/"mechanism_manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--stage", choices=("inspect", "textures", "prepare"), default="inspect")
    parser.add_argument("--render", action="store_true")
    argv = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else sys.argv[1:]
    args = parser.parse_args(argv)
    plan = static.read(args.plan)
    results = []
    for entry in plan["entries"]:
        if args.stage == "inspect":
            result = inspect_entry(plan, entry)
        elif args.stage == "textures":
            texture_entry = platform_entry(entry) if entry["profile"] == "archer_platform" else entry
            result = static.prepare_textures(texture_entry, plan["output_root"])
        else:
            result = prepare_entry(plan, entry, args.render)
        output = output_folder(plan, entry)
        if entry["profile"] == "archer_platform" and args.stage == "prepare":
            output = Path(result["exports"]["fbx"]["path"]).parent
        results.append({"asset_id": entry["asset_id"], "status": result["status"], "output": str(output),
                        "manifest": str(output/("manifest.json" if entry["profile"] == "archer_platform" else "mechanism_manifest.json"))
                        if args.stage == "prepare" else None})
    static.write(args.plan.with_name(args.plan.stem+"_"+args.stage+".json"), {"results": results})
    print(json.dumps(results))


if __name__ == "__main__":
    main()
