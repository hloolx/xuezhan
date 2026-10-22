"""Four fixed-camera source/ground-placement previews with real spawned units."""
import importlib.util
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


measure = load("base_measurements", ROOT / "Tools/base_stone_diagnose.py")
shared = load("base_render_helpers", ROOT / "Tools/Blender/prepare_tripo_environment.py")
FRONT_ONLY = "--front-only" in sys.argv
OUTPUT = measure.OWNED / ("origin_front_elevated_v04_renders" if FRONT_ONLY else "origin_comparison_v03_renders")
OUTPUT.mkdir(exist_ok=False)
for path, expected in ((measure.SOURCE, measure.SOURCE_SHA), (measure.PROBE, measure.PROBE_SHA), (measure.BODY, measure.BODY_SHA)):
    if measure.digest(path) != expected:
        raise ValueError("Frozen source changed: " + str(path))

bpy.ops.wm.open_mainfile(filepath=str(measure.BODY))
armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
originals = list(bpy.context.scene.objects)
parts = [obj for obj in originals if obj.type == "MESH"]
unit_records = []
for row_y, action in ((-85, "Move"), (0, "Idle"), (85, "Move")):
    armature.animation_data.action = bpy.data.actions["CW_StoneAxe_" + action]
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    for original in parts:
        evaluated = original.evaluated_get(graph)
        mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=graph)
        copied = bpy.data.objects.new("REVIEW_UNIT_" + str(row_y) + "_" + original.name, mesh)
        bpy.context.scene.collection.objects.link(copied)
        copied.matrix_world = evaluated.matrix_world.copy()
        copied.location += Vector((2.6, row_y / 100, 0))
    unit_records.append({"spawn_cm": [260, row_y, 0], "clip": action, "frame": 1,
                         "nominal_height_cm": 150, "scale_factor": 1, "independent_weapon_included": True})
for original in originals:
    bpy.data.objects.remove(original, do_unlink=True)

bpy.ops.import_scene.gltf(filepath=str(measure.PROBE))
base = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and not obj.name.startswith("REVIEW_UNIT_")]
neutral = bpy.data.materials.new("REVIEW_ONLY_BASE_GREY")
neutral.use_nodes = True
shader = neutral.node_tree.nodes.get("Principled BSDF")
shader.inputs["Base Color"].default_value = (.4, .4, .4, 1)
shader.inputs["Metallic"].default_value = 0
shader.inputs["Roughness"].default_value = .8
for obj in base:
    obj.data.materials.clear()
    obj.data.materials.append(neutral)

bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, 0))
ground = bpy.context.object
ground.name = "REVIEW_GAME_GROUND_Z_ZERO"
material = bpy.data.materials.new("REVIEW_ONLY_GROUND")
material.use_nodes = True
shader = material.node_tree.nodes.get("Principled BSDF")
shader.inputs["Base Color"].default_value = (.14, .19, .16, 1)
shader.inputs["Roughness"].default_value = .9
ground.data.materials.append(material)
centre = Vector((.3, 0, 1.5))
camera, centre, span = shared.setup_render(base[0], "HIP", (centre, 6.4))
scene = bpy.context.scene
scene.render.threads_mode = "FIXED"
scene.render.threads = 2
scene.cycles.samples = 8
scene.render.resolution_x = scene.render.resolution_y = 512
scene.render.film_transparent = False
renders = []
original_matrices = {obj.name: obj.matrix_world.copy() for obj in base}
for label, vertical_offset in (("baseline", 0), ("buried31cm", -.31)):
    for obj in base:
        obj.matrix_world = original_matrices[obj.name].copy()
        obj.matrix_world.translation += Vector((0, 0, vertical_offset))
    views = (("front_elevated", (1, 0, .3)),) if FRONT_ONLY else (("front", (1, 0, 0)), ("oblique", (2, -3, 1.6)))
    for view, direction in views:
        camera.location = centre + Vector(direction) * span * 2
        camera.rotation_euler = (centre - camera.location).to_track_quat("-Z", "Y").to_euler()
        camera.data.ortho_scale = 8
        path = OUTPUT / (label + "_" + view + ".png")
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        renders.append({"candidate": label, "base_z_offset_cm": vertical_offset * 100, "view": view, **measure.record(path)})
result = {"asset_id": "Base_Stone", "status": "actual_unit_ground_comparison_images_pending_review",
          "source": measure.record(measure.SOURCE), "diagnostic_model": measure.record(measure.PROBE), "actor": measure.record(measure.BODY),
          "units": unit_records, "ground_z_cm": 0, "same_cameras_lights_and_meshes": True,
          "base_grey_material_only_in_memory": True, "base_geometry_parts_hidden": False, "mesh_exported": False,
          "base_source_bytes_unchanged": measure.digest(measure.SOURCE) == measure.SOURCE_SHA,
          "actor_source_bytes_unchanged": measure.digest(measure.BODY) == measure.BODY_SHA,
          "threads": 2, "gpu": "HIP", "resolution": [512, 512], "samples": 8, "renders": renders, "front_elevated": FRONT_ONLY,
          "final_origin_approved": False, "approved_for_texture": False, "approved_for_ue_import": False, "production_approved": False}
(OUTPUT / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
