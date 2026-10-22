"""Fit the received Tripo pack as an independent, original-PBR back module."""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).parent))
import build_mammoth_preview as common
import prepare_stoneaxe_rig_pilot as inspection
from prepare_era_asset import read, record, digest

ROOT = Path(__file__).resolve().parents[2]


def build(source, textures_path, yaw):
    texture_report = read(textures_path)
    if texture_report["source"]["sha256"] != digest(source):
        raise ValueError("Original pack geometry/PBR source mismatch")
    output = ROOT/"RawAssets/Art/Tripo_v01/weapons/Prop_DemolitionPack"
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system, scene.unit_settings.scale_length = "METRIC", 1.
    scene.render.threads_mode, scene.render.threads = "FIXED", 2
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [obj for obj in scene.objects if obj.type == "MESH"]
    if len(meshes) != 1 or any(obj.type == "ARMATURE" for obj in scene.objects):
        raise ValueError("Expected one actual static pack")
    body = meshes[0]
    if len(body.data.materials) != len(texture_report["materials"]):
        raise ValueError("Actual pack material slots differ from original PBR")
    points = [body.matrix_world @ vertex.co for vertex in body.data.vertices]
    rotation = Matrix.Rotation(math.radians(yaw), 4, "Z")
    rotated = [rotation @ point for point in points]
    low = Vector(tuple(min(point[i] for point in rotated) for i in range(3)))
    high = Vector(tuple(max(point[i] for point in rotated) for i in range(3)))
    scale = .46/(high.z-low.z)
    # The actual body-facing surface is the +X extreme. The charge side faces
    # -X; its orientation is chosen from the rendered source, not invented anchors.
    mount = Vector((high.x, (low.y+high.y)/2, (low.z+high.z)/2))
    transform = Matrix.Scale(scale, 4) @ Matrix.Translation(-mount) @ rotation @ body.matrix_world
    body.data.transform(transform)
    body.parent = None
    body.matrix_world = Matrix.Identity(4)
    root = bpy.data.objects.new("Prop_DemolitionPack", None)
    scene.collection.objects.link(root)
    body.parent = root
    pbr = {}
    for index, row in enumerate(texture_report["materials"]):
        name = "Pack_"+row["slot_name"]
        body.data.materials[index].name = name
        row = dict(row, slot_name=name)
        pbr[name] = row
    anchor = bpy.data.objects.new("back_mount", None)
    scene.collection.objects.link(anchor)
    anchor.parent = root
    common.select([root, body, anchor])
    glb_path = output/"Prop_DemolitionPack.glb"
    bpy.ops.export_scene.gltf(filepath=str(glb_path), export_format="GLB", use_selection=True, export_animations=False)
    bpy.ops.wm.save_as_mainfile(filepath=str(output/"Prop_DemolitionPack.blend"))
    interface = {
        "asset_id": "Prop_DemolitionPack", "revision": "actual_tripo_v01",
        "status": "actual_pbr_module_pending_character_fit", "family": "body_backpack",
        "root": root.name, "units": "metres", "source": record(source),
        "pbr_source_report": record(textures_path), "pbr_materials": pbr,
        "anchors": {"back_mount": {"position_m": [0, 0, 0], "rotation_euler_deg": [0, 0, 0],
                                  "role": "Measured +X back-facing mesh extreme"}},
        "deformation_controls": [], "yaw_degrees": yaw, "height_m": .46,
        "geometry_invented": False, "production_approved": False,
    }
    (output/"interface.json").write_text(json.dumps(interface, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    if scene.world is None:
        scene.world = bpy.data.worlds.new("PackPreviewWorld")
    inspection.helper.render_setup(samples=8)
    scene.cycles.device = "CPU"
    for label, direction in (("outside", (-1, -1, .2)), ("body_contact", (1, 1, .2))):
        inspection.helper.render_view(output/(label+".png"), [body], direction, size=480, framing=.75)
    print(json.dumps({"module": str(output), "actual_tripo_source": str(source), "original_pbr": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--textures", type=Path, required=True)
    parser.add_argument("--yaw-degrees", type=float, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    build(args.source.resolve(), args.textures.resolve(), args.yaw_degrees)
