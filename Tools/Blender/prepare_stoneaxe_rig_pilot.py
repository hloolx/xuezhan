from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector


ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "RawAssets/Art/Tripo_v01"
OUTPUT = ART / "tripo_processed/stoneaxe_rig_pilot"
SOURCE = ART / "tripo_raw/Unit_StoneAxe/textured_v03_canonical/model.fbx"
GEOMETRY = ART / "tripo_raw/Unit_StoneAxe/v03_canonical/model.fbx"
helper_spec = importlib.util.spec_from_file_location("character_geometry", Path(__file__).with_name("prepare_tripo_character.py"))
helper = importlib.util.module_from_spec(helper_spec)
helper_spec.loader.exec_module(helper)


def import_model(path):
    before = set(bpy.data.objects)
    if path.suffix.lower() == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path), use_anim=True)
    elif path.suffix.lower() in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
    else:
        raise ValueError(path.suffix)
    bpy.context.view_layer.update()
    return [obj for obj in bpy.data.objects if obj not in before]


def material_report(objects):
    rows = []
    for material in sorted({slot.material for obj in objects for slot in obj.material_slots if slot.material}, key=lambda item: item.name):
        nodes = []
        for node in material.node_tree.nodes if material.node_tree else []:
            entry = {"name": node.name, "type": node.type}
            if node.type == "TEX_IMAGE" and node.image:
                entry.update({"image": node.image.name, "size": list(node.image.size), "channels": node.image.channels,
                              "color_space": node.image.colorspace_settings.name, "packed": bool(node.image.packed_file),
                              "filepath": node.image.filepath, "has_data": node.image.has_data,
                              "outputs": [{"socket": link.to_socket.name, "node": link.to_node.name} for output in node.outputs for link in output.links]})
            nodes.append(entry)
        rows.append({"name": material.name, "nodes": nodes})
    return rows


def skeleton_report(armature, objects):
    groups = {obj.name: {group.index: group.name for group in obj.vertex_groups} for obj in objects}
    rows = []
    for bone in armature.data.bones:
        rows.append({"name": bone.name, "parent": bone.parent.name if bone.parent else None,
                     "head": helper.vector(armature.matrix_world @ bone.head_local),
                     "tail": helper.vector(armature.matrix_world @ bone.tail_local), "deform": bone.use_deform})
    weights = []
    for obj in objects:
        weighted = [vertex for vertex in obj.data.vertices if any(group.weight > 0 for group in vertex.groups)]
        weights.append({"object": obj.name, "vertices": len(obj.data.vertices), "weighted_vertices": len(weighted),
                        "maximum_influences": max((len(vertex.groups) for vertex in weighted), default=0),
                        "minimum_weight_sum": min((sum(group.weight for group in vertex.groups) for vertex in weighted), default=0),
                        "maximum_weight_sum": max((sum(group.weight for group in vertex.groups) for vertex in weighted), default=0),
                        "groups": list(groups[obj.name].values())})
    return {"name": armature.name, "bone_count": len(rows), "bones": rows, "weights": weights}


def render_setup(device, samples):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.cycles.device = "CPU"
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 2
    if device == "HIP":
        preferences = bpy.context.preferences.addons["cycles"].preferences
        preferences.compute_device_type = "HIP"
        preferences.get_devices()
        for device_info in preferences.devices:
            device_info.use = device_info.type == "HIP"
        scene.cycles.device = "GPU"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.world.color = (.36, .36, .36)
    scene.view_settings.view_transform = "AgX"
    camera = bpy.data.objects.new("PilotCamera", bpy.data.cameras.new("PilotCamera"))
    scene.collection.objects.link(camera)
    camera.data.type = "ORTHO"
    scene.camera = camera
    for index in range(3):
        light = bpy.data.objects.new("PilotLight" + str(index), bpy.data.lights.new("PilotLight" + str(index), "AREA"))
        scene.collection.objects.link(light)


def normalize(objects, armatures):
    minimum, maximum = helper.bounds(objects)
    factor = 1.5 / (maximum.z - minimum.z)
    origin = Vector(((minimum.x + maximum.x) / 2, (minimum.y + maximum.y) / 2, minimum.z))
    transform = Matrix.Scale(factor, 4) @ Matrix.Translation(-origin)
    roots = [obj for obj in objects + armatures if not obj.parent or obj.parent not in objects + armatures]
    for obj in roots:
        obj.matrix_world = transform @ obj.matrix_world
    bpy.context.view_layer.update()
    return {"factor": factor, "matrix": [list(row) for row in transform], "height_m": 1.5, "front": "+X", "bottom_z": 0}


def inspect(args):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.context.scene.unit_settings.system = "METRIC"
    imported = import_model(args.source)
    meshes = [obj for obj in imported if obj.type == "MESH"]
    armatures = [obj for obj in imported if obj.type == "ARMATURE"]
    source_stats = helper.mesh_stats(meshes)
    report = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
              "source": str(args.source), "source_sha256": helper.sha(args.source), "blender": bpy.app.version_string,
              "source_statistics": source_stats, "materials": material_report(meshes), "armatures": [],
              "production_approved": False, "grip_approved": False, "animation_approved": False, "in_game_approved": False}
    for armature in armatures:
        report["armatures"].append(skeleton_report(armature, meshes))
    if not armatures:
        source_positions = [obj.matrix_world @ vertex.co for obj in meshes for vertex in obj.data.vertices]
        reference = import_model(GEOMETRY)
        reference_meshes = [obj for obj in reference if obj.type == "MESH"]
        reference_positions = [obj.matrix_world @ vertex.co for obj in reference_meshes for vertex in obj.data.vertices]
        report["geometry_comparison"] = {"source": str(GEOMETRY), "source_sha256": helper.sha(GEOMETRY),
                                         "vertex_count_equal": len(source_positions) == len(reference_positions),
                                         "maximum_indexed_vertex_difference_m": max(((current - previous).length for current, previous in zip(source_positions, reference_positions)), default=0)}
        for obj in reference:
            bpy.data.objects.remove(obj, do_unlink=True)
    report["normalization"] = normalize(meshes, armatures)
    minimum, maximum = helper.bounds(meshes)
    report["normalized_bounds_cm"] = {"minimum": helper.vector(minimum * 100), "maximum": helper.vector(maximum * 100), "dimensions": helper.vector((maximum - minimum) * 100)}
    textures = args.output / "textures"
    textures.mkdir(parents=True, exist_ok=True)
    for image in bpy.data.images:
        if image.has_data and image.type == "IMAGE":
            image.filepath_raw = str(textures / (image.name.split(".")[0] + ".png"))
            image.file_format = "PNG"
            image.save()
    helper.write(args.output / "inspection.json", report)
    helper.select(meshes + armatures)
    bpy.ops.export_scene.gltf(filepath=str(args.output / "Unit_StoneAxe_textured_normalized.glb"), export_format="GLB", use_selection=True,
                              export_yup=True, export_apply=False, export_animations=False, export_skins=True, export_morph=False)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output / "Unit_StoneAxe_textured_normalized.blend"))
    if args.render:
        render_setup(args.device, args.samples)
        for name, direction in [("front", (1, 0, 0)), ("right", (0, 1, 0)), ("back", (-1, 0, 0)), ("left", (0, -1, 0)), ("preview", (1, 1.3, .4))]:
            helper.render_view(args.output / (name + ".png"), meshes, direction, size=args.size)
        for name, direction in [("hand_right_front", (1, .65, .15)), ("hand_right_rear", (-1, .65, .15))]:
            helper.render_view(args.output / (name + ".png"), meshes, direction, size=args.size, framing=.38, target=(0, .42, .69))
    print("STONEAXE_INSPECTION " + json.dumps({"output": str(args.output), "source_sha256": report["source_sha256"], "armatures": len(armatures)}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT / "textured_inspection")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--device", choices=["CPU", "HIP"], default="CPU")
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--size", type=int, default=768)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    args.output.mkdir(parents=True, exist_ok=True)
    inspect(args)


if __name__ == "__main__":
    main()
