"""Prepare a real Base_Stone GLB without merging its source mesh parts.

Default mode only validates the preparation contract and reports missing evidence.
Run --execute inside Blender only after root grants the single heavy-process slot.
This tool never submits provider work, imports into Unreal, or approves production.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
OWNED = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/base_stone_v01"
DEFAULT_SPEC = OWNED / "preparation_spec.json"
RAW = ROOT / "RawAssets/Art/Tripo_v01/tripo_raw/Base_Stone"
VIEW_DIRECTIONS = {
    "preview": (2, -3, 1.6), "front": (1, 0, 0), "left": (0, -1, 0),
    "back": (-1, 0, 0), "right": (0, 1, 0), "top": (0, 0, 1),
}


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def relative(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def resolve_inside(value, directory):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("Path escapes the assigned asset directory: " + str(path))
    return path


def validate_contract(spec):
    if spec.get("schema_version") != 1 or spec.get("asset_id") != "Base_Stone":
        raise ValueError("Expected Base_Stone preparation contract version 1")
    if spec.get("production_approved") is not False:
        raise ValueError("Preparation must not claim production approval")
    normalization = spec["normalization"]
    if normalization["measure"] != "horizontal_max" or normalization["target_cm"] != 640:
        raise ValueError("First diagnostic fit must use uniform 640 cm horizontal maximum")
    if normalization["forward"] != "+X" or normalization["up"] != "+Z":
        raise ValueError("The project basis must remain +X forward and +Z up")
    if normalization["origin_is_gameplay_final"] is not False:
        raise ValueError("Whole-mesh center is only a provisional diagnostic origin")
    review = spec["review"]
    if review["threads"] != 2 or review["resolution"] != 512 or review["samples"] != 8:
        raise ValueError("Keep the agreed two-thread, 512 px, eight-sample review limits")
    if review["views"] != list(VIEW_DIRECTIONS):
        raise ValueError("Review must include four orthographic faces, preview and top")
    if spec["parts_policy"] != "preserve_source_mesh_boundaries_no_join_no_automatic_split":
        raise ValueError("The architecture pass must preserve source mesh boundaries")
    if spec["import_policy"]["runtime_registration"] is not False:
        raise ValueError("This pass cannot register a runtime base")


def validate_inputs(spec, require_axis=True):
    validate_contract(spec)
    for role, record in spec["canonical_inputs"].items():
        path = resolve_inside(record["file"], ROOT / "RawAssets/Art/Tripo_v01/prepared_tripo_canonical/Base_Stone")
        if not path.is_file() or digest(path) != record["sha256"]:
            raise ValueError("Canonical reference changed: " + role)
    source = spec.get("source")
    if source is None:
        return {"ready": False, "status": "waiting_for_real_download_no_input_fabricated", "missing": ["source"]}
    required = ["file", "sha256", "task_id", "task_file", "submission_file"]
    missing = ["source." + field for field in required if not source.get(field)]
    if missing:
        return {"ready": False, "status": "incomplete_source_evidence", "missing": missing}
    path = resolve_inside(source["file"], RAW)
    if path.suffix.lower() != ".glb" or not path.is_file():
        raise ValueError("A real downloaded Base_Stone GLB is required")
    if not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]) or digest(path) != source["sha256"]:
        raise ValueError("Source GLB hash mismatch")
    task_path = resolve_inside(source["task_file"], RAW)
    receipt_path = resolve_inside(source["submission_file"], RAW)
    if task_path.parent != path.parent or receipt_path.parent != path.parent:
        raise ValueError("Task, receipt and source must belong to one raw version")
    task, receipt = read_json(task_path), read_json(receipt_path)
    if task.get("task_id") != source["task_id"] or receipt.get("task_id") != source["task_id"]:
        raise ValueError("Task ID and submission receipt do not match")
    if task.get("status") != "success" or task.get("type") not in {"multiview_to_model", "image_to_model"}:
        raise ValueError("Expected a successful provider geometry task")
    provider_input = task.get("input", {})
    if provider_input.get("texture") is not False or provider_input.get("pbr") is not False:
        raise ValueError("This first pass expects the approved bare-geometry task")
    provider_model = provider_input.get("model_version", provider_input.get("model"))
    if provider_model != spec["planned_generation"]["model"]:
        raise ValueError("Provider model differs from the saved generation contract")
    evidence = {"source": str(path), "task_id": source["task_id"], "source_sha256": source["sha256"]}
    if not require_axis:
        return {"ready": True, "status": "source_verified_axis_probe_only", **evidence, "missing": []}
    axis = spec["normalization"]["axis_review"]
    yaw = spec["normalization"].get("yaw_degrees")
    if not axis.get("reviewed") or axis.get("source_sha256") != source["sha256"] or not axis.get("evidence"):
        return {"ready": False, "status": "source_verified_axis_review_pending", **evidence,
                "missing": ["source-specific +X axis review"]}
    if isinstance(yaw, bool) or not isinstance(yaw, (int, float)) or not math.isfinite(yaw):
        raise ValueError("A visually verified finite source yaw is required; do not assume zero")
    for record in axis["evidence"]:
        evidence_path = (ROOT / record["file"]).resolve()
        if not evidence_path.is_relative_to(ROOT) or not evidence_path.is_file() or digest(evidence_path) != record["sha256"]:
            raise ValueError("Axis review evidence is missing or changed")
    return {"ready": True, "status": "ready_for_root_scheduled_diagnostic_pass", **evidence, "missing": []}


def load_shared_helpers():
    path = ROOT / "Tools/Blender/prepare_tripo_environment.py"
    module_spec = importlib.util.spec_from_file_location("base_stone_shared_helpers", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def execute(spec, readiness, render, device, axis_probe=False):
    if not readiness["ready"]:
        raise ValueError("Preparation blocked: " + readiness["status"])
    import bpy
    from mathutils import Vector

    shared = load_shared_helpers()
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:12]
    output = OWNED / ("h" + fingerprint + ("_axis_probe" if axis_probe else ""))
    output.mkdir(parents=True, exist_ok=False)
    source = Path(readiness["source"])
    (output / "source").mkdir()
    shutil.copy2(source, output / "source/original.glb")
    shared.write_json(output / "input_spec.json", spec)
    shared.write_json(output / "checkpoint.json", {"status": "started", "production_approved": False,
                      "source_sha256": readiness["source_sha256"], "repeat_policy": "Do not overwrite this partial directory; inspect it before any repeat."})
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1
    bpy.context.scene.render.threads_mode = "FIXED"
    bpy.context.scene.render.threads = 2
    bpy.ops.import_scene.gltf(filepath=str(source))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not objects or any(obj.type == "ARMATURE" for obj in bpy.context.scene.objects) or any(obj.data.shape_keys for obj in objects):
        raise ValueError("Expected static, non-morphing source geometry")
    source_hierarchy = [{"name": obj.name, "type": obj.type, "parent": obj.parent.name if obj.parent else None}
                        for obj in bpy.context.scene.objects]
    before = shared.geometry_report(objects)
    before_uv = shared.uv_signature(objects)
    before_materials = shared.material_report(objects)
    textures = shared.extract_original_textures(objects, output / "textures")
    yaw = 0 if axis_probe else spec["normalization"]["yaw_degrees"]
    normalization = shared.normalize(objects, "horizontal_max", 640, yaw)
    after = shared.geometry_report(objects)
    after_uv = shared.uv_signature(objects)
    after_materials = shared.material_report(objects)
    for field in ["mesh_count", "vertices", "polygons", "triangles"]:
        if before[field] != after[field]:
            raise RuntimeError("Unexpected geometry change: " + field)
    if before_uv != after_uv or before_materials != after_materials:
        raise RuntimeError("Source UVs or materials changed during normalization")
    low, high = shared.bounds(objects)
    dimensions = list((high - low) * 100)
    if abs(low.z) > 1e-5:
        raise RuntimeError("Provisional bottom origin did not reach Z=0")
    root = bpy.data.objects.new("Base_Stone_SOURCE_PARTS", None)
    bpy.context.scene.collection.objects.link(root)
    for obj in objects:
        obj.parent = root
    selected = objects + [root]
    shared.select(selected)
    glb = output / "Base_Stone_geometry.glb"
    fbx = output / "Base_Stone_geometry.fbx"
    blend = output / "Base_Stone_geometry.blend"
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", use_selection=True, export_apply=False,
                              export_yup=True, export_extras=True, export_image_format="AUTO", export_animations=False)
    bpy.ops.export_scene.fbx(filepath=str(fbx), use_selection=True, object_types={"MESH", "EMPTY"},
                            apply_unit_scale=True, apply_scale_options="FBX_SCALE_UNITS", axis_forward="X", axis_up="Z",
                            use_mesh_modifiers=False, bake_anim=False, path_mode="COPY", embed_textures=True)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    views = []
    if render:
        centre, span = (low + high) * .5, max(high - low)
        camera, centre, span = shared.setup_render(objects[0], device, (centre, span))
        scene = bpy.context.scene
        scene.render.threads_mode = "FIXED"
        scene.render.threads = 2
        scene.cycles.samples = 8
        scene.render.resolution_x = scene.render.resolution_y = 512
        neutral = bpy.data.materials.new("REVIEW_ONLY_Base_Stone_Neutral")
        neutral.use_nodes = True
        shader = neutral.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = (.4, .4, .4, 1)
        shader.inputs["Metallic"].default_value = 0
        shader.inputs["Roughness"].default_value = .8
        bpy.context.view_layer.material_override = neutral
        for name, direction in VIEW_DIRECTIONS.items():
            camera.location = centre + Vector(direction) * span * 2
            camera.rotation_euler = (centre - camera.location).to_track_quat("-Z", "Y").to_euler()
            camera.data.ortho_scale = span * (1.55 if name == "preview" else 1.25)
            image = output / (name + ".png")
            scene.render.filepath = str(image)
            bpy.ops.render.render(write_still=True)
            views.append({"view": name, "file": relative(image), "sha256": digest(image)})
    roundtrip = shared.verify_roundtrip(glb, dimensions, after["triangles"], len(after_materials),
                                       any(part["uv_layers"] for part in after["meshes"]))
    roundtrip["mesh_part_count_preserved"] = roundtrip["geometry"]["mesh_count"] == after["mesh_count"]
    if not roundtrip["mesh_part_count_preserved"]:
        roundtrip["errors"].append("source_mesh_part_count_changed")
        roundtrip["pass"] = False
    report = {"asset_id": "Base_Stone", "status": "diagnostic_geometry_only_architecture_acceptance_pending",
              "updated_at": datetime.now(timezone.utc).isoformat(), "source": readiness, "source_hierarchy": source_hierarchy,
              "hierarchy_policy": "Source mesh boundaries preserved; static transforms baked and meshes attached to a new identity root. Original complete source bytes are retained.",
              "source_geometry": before, "processed_geometry": after, "normalization": normalization,
              "axis_probe_only": axis_probe, "front_is_verified_positive_x": not axis_probe,
              "origin_is_gameplay_final": False, "dimensions_cm": dimensions, "uv_unchanged": before_uv == after_uv,
              "source_materials_preserved": True, "original_textures": textures, "renders": views,
              "glb_roundtrip": roundtrip, "parts_semantically_separated": False, "socket_positions_measured": False,
              "gate_clearance_measured": False, "approved_for_ue_import": False, "production_approved": False,
              "pending_architecture_checks": spec["architecture_acceptance"]}
    shared.write_json(output / "inspection.json", report)
    if not roundtrip["pass"]:
        raise RuntimeError("GLB round-trip failed; inspect the retained diagnostic report")
    if digest(source) != readiness["source_sha256"]:
        raise RuntimeError("Raw source bytes changed during this pass")
    if axis_probe:
        shared.write_json(output / "checkpoint.json", {"status": "source_axis_probe_complete_not_game_axis_approved",
                          "source_sha256": readiness["source_sha256"], "renders": views,
                          "view_names_mean_camera_axis_only": True, "production_approved": False})
        return {"status": "axis_probe_only_no_import_manifest", "inspection": relative(output / "inspection.json")}
    manifest = {"schema_version": 1, "batch_id": "tripo_base_stone_v01", "units": "cm", "source": "Tripo",
                "status": "diagnostic_import_manifest_not_runtime_or_production_approval", "production_approved": False,
                "assets": [{"id": "Base_Stone", "role": "base_geometry_candidate", "file": relative(glb),
                            "fbx": relative(fbx), "blend": relative(blend), "type": "static_mesh",
                            "expected_dimensions_cm": dimensions, "import_scale": 1, "import_materials": True,
                            "combine_meshes": False, "source_stage": "geometry_only", "task_id": readiness["task_id"],
                            "source_sha256": readiness["source_sha256"], "sha256": digest(glb),
                            "inspection": relative(output / "inspection.json"), "assembly_required": True,
                            "approved_for_ue_import": False, "production_approved": False}]}
    shared.write_json(output / "manifest.json", manifest)
    shared.write_json(output / "checkpoint.json", {"status": "diagnostic_preparation_complete_review_pending",
                      "source_sha256": readiness["source_sha256"], "model_sha256": digest(glb), "renders": views,
                      "active_processes": [], "production_approved": False})
    return {"status": "prepared_diagnostic_only", "manifest": relative(output / "manifest.json"),
            "inspection": relative(output / "inspection.json"), "production_approved": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--probe-axis", action="store_true")
    parser.add_argument("--device", choices=["CPU", "HIP"], default="HIP")
    args = parser.parse_args(argv)
    spec_path = resolve_inside(str(args.spec), OWNED)
    spec = read_json(spec_path)
    readiness = validate_inputs(spec, require_axis=not args.probe_axis)
    if args.render and not args.execute:
        parser.error("--render requires explicit --execute inside Blender")
    if args.probe_axis and not (args.execute and args.render):
        parser.error("--probe-axis requires --execute --render; it is a diagnostic render, not an axis approval")
    result = execute(spec, readiness, args.render, args.device, args.probe_axis) if args.execute else readiness
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    raise SystemExit(main(arguments))
