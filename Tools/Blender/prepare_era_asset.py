"""Prepare existing Tripo static assets without generating or replacing geometry.

Ordinary Python:
  python Tools/Blender/prepare_era_asset.py --plan plan.json --stage inspect
  python Tools/Blender/prepare_era_asset.py --plan plan.json --stage textures
Leased Blender process (two threads):
  blender -b -t 2 --python-exit-code 1 --python Tools/Blender/prepare_era_asset.py -- --plan plan.json --stage prepare

Plan entries require asset_id, kind, source, target_cm, measure (height or
horizontal_max), yaw_degrees. Optional ground_offset_cm, anchors_cm and
team_color ("blue_chroma" or "none"). Anchors are explicit final UE centimetres,
never inferred from the bounds. Human, rider, vehicle, mech and mount inputs are
classified by their actual GLB contents; this tool does not invent five clips.
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
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/era_assets_v01"
STATIC_KINDS = {"base", "turret", "prop", "weapon", "environment"}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def absolute(path):
    path = Path(path)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(path):
    path = Path(path).resolve()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}


def glb(path):
    data = Path(path).read_bytes()
    if len(data) < 20 or struct.unpack_from("<III", data) != (0x46546C67, 2, len(data)):
        raise ValueError("Expected a complete GLB2: " + str(path))
    document, binary, cursor = None, b"", 12
    while cursor < len(data):
        size, kind = struct.unpack_from("<II", data, cursor)
        cursor += 8
        if cursor + size > len(data):
            raise ValueError("Truncated GLB chunk")
        payload = data[cursor:cursor + size]
        cursor += size
        if kind == 0x4E4F534A:
            document = json.loads(payload.rstrip(b" \0"))
        elif kind == 0x004E4942:
            binary = payload
    if document is None:
        raise ValueError("GLB JSON missing")
    return document, binary


def inspect(entry):
    source = absolute(entry["source"])
    source_record = record(source)
    if entry.get("source_sha256") and entry["source_sha256"] != source_record["sha256"]:
        raise ValueError("Source changed: " + str(source))
    document, _ = glb(source)
    primitives = [p for mesh in document.get("meshes", []) for p in mesh["primitives"]]
    triangles = sum(document["accessors"][p["indices"]]["count"] // 3 if "indices" in p
                    else document["accessors"][p["attributes"]["POSITION"]]["count"] // 3
                    for p in primitives if p.get("mode", 4) == 4)
    materials = []
    for i, material in enumerate(document.get("materials", [])):
        pbr = material.get("pbrMetallicRoughness", {})
        materials.append({"index": i, "name": material.get("name"),
                          "base_color": "baseColorTexture" in pbr,
                          "normal": "normalTexture" in material,
                          "metallic_roughness": "metallicRoughnessTexture" in pbr,
                          "alpha_mode": material.get("alphaMode", "OPAQUE")})
    skinned = bool(document.get("skins"))
    kind = entry["kind"]
    route = ("skeletal_source_requires_authored_actions" if skinned else
             "static_ready_for_preparation" if kind in STATIC_KINDS else
             "mechanical_articulation_required" if kind in {"vehicle", "mech"} else
             "rig_and_authored_actions_required")
    errors = []
    if not primitives:
        errors.append("no_mesh_primitives")
    if any(p.get("mode", 4) != 4 for p in primitives):
        errors.append("non_triangle_primitive")
    if any("TEXCOORD_0" not in p.get("attributes", {}) for p in primitives):
        errors.append("missing_uv")
    if not materials or not all(m["base_color"] for m in materials):
        errors.append("missing_textured_base_color")
    if any(m["alpha_mode"] != "OPAQUE" for m in materials):
        errors.append("transparent_material_requires_separate_policy")
    return {"asset_id": entry["asset_id"], "kind": kind, "source": source_record,
            "route": route, "triangles": triangles, "skins": len(document.get("skins", [])),
            "source_animations": [a.get("name", str(i)) for i, a in enumerate(document.get("animations", []))],
            "materials": materials, "full_pbr": bool(materials) and all(
                m["normal"] and m["metallic_roughness"] for m in materials),
            "errors": errors, "production_approved": False}


def folder(entry, output_root):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", entry["asset_id"]):
        raise ValueError("Unsafe asset id")
    fingerprint_input = dict(entry, source_sha256=digest(absolute(entry["source"])), pipeline_version=1)
    fingerprint = hashlib.sha256(json.dumps(fingerprint_input, sort_keys=True).encode()).hexdigest()[:16]
    return absolute(output_root) / entry["asset_id"] / ("h" + fingerprint)


def extract_image(document, binary, texture_info, source):
    if texture_info.get("texCoord", 0) != 0 or texture_info.get("extensions"):
        raise ValueError("Nonzero or transformed UV set requires explicit handling")
    tex = document["textures"][texture_info["index"]]
    image = document["images"][tex["source"]]
    if "bufferView" in image:
        view = document["bufferViews"][image["bufferView"]]
        if view.get("buffer", 0) != 0:
            raise ValueError("External GLB buffer unsupported")
        offset = view.get("byteOffset", 0)
        payload = binary[offset:offset + view["byteLength"]]
    else:
        path = (source.parent / image["uri"]).resolve()
        if not path.is_relative_to(source.parent):
            raise ValueError("Image URI leaves source directory")
        payload = path.read_bytes()
    if payload.startswith(b"\x89PNG"):
        extension = ".png"
    elif payload.startswith(b"\xff\xd8"):
        extension = ".jpg"
    else:
        raise ValueError("Expected original PNG/JPEG texture")
    return payload, extension


def prepare_textures(entry, output_root, textures_only=False):
    """Lightweight stage: exact original image payloads plus optional red copy."""
    from PIL import Image
    result = inspect(entry)
    if result["errors"]:
        raise ValueError(str(result["errors"]))
    if result["route"] != "static_ready_for_preparation" and not textures_only:
        return result
    output = folder(entry, output_root)
    texture_report = output / "textures.json"
    if texture_report.exists():
        previous = read(texture_report)
        for row in previous["materials"]:
            for rec in row["textures"].values():
                if digest(rec["path"]) != rec["sha256"]:
                    raise ValueError("Prepared texture changed")
            if row.get("team_cloth"):
                for key in ("mask", "red_base_color"):
                    rec = row["team_cloth"][key]
                    if digest(rec["path"]) != rec["sha256"]:
                        raise ValueError("Prepared team texture changed")
        return previous
    output.mkdir(parents=True, exist_ok=True)
    source = absolute(entry["source"])
    document, binary = glb(source)
    material_rows = []
    for index, material in enumerate(document["materials"]):
        pbr = material.get("pbrMetallicRoughness", {})
        directory = output / "materials" / ("m%03d" % index)
        directory.mkdir(parents=True, exist_ok=True)
        channels = {
            "base_color": pbr.get("baseColorTexture"),
            "metallic_roughness": pbr.get("metallicRoughnessTexture"),
            "normal": material.get("normalTexture"),
            "occlusion": material.get("occlusionTexture"),
            "emissive": material.get("emissiveTexture"),
        }
        textures = {}
        for channel, info in channels.items():
            if info is None:
                continue
            payload, extension = extract_image(document, binary, info, source)
            path = directory / (channel + extension)
            path.write_bytes(payload)
            textures[channel] = dict(record(path), dimensions=list(Image.open(path).size))
        row = {"source_index": index, "slot_name": "M_Source_%03d" % index,
               "source_name": material.get("name", "Material_%d" % index),
               "textures": textures, "double_sided": material.get("doubleSided", False),
               "base_color_factor": pbr.get("baseColorFactor", [1, 1, 1, 1]),
               "roughness_factor": pbr.get("roughnessFactor", 1),
               "metallic_factor": pbr.get("metallicFactor", 1),
               "normal_scale": material.get("normalTexture", {}).get("scale", 1),
               "occlusion_strength": material.get("occlusionTexture", {}).get("strength", 1),
               "emissive_factor": material.get("emissiveFactor", [0, 0, 0])}
        if entry.get("team_color", "none") == "blue_chroma":
            # Reuse the shipped stone-era exact luminance/selection policy.
            helper_path = Path(__file__).with_name("prepare_beast_rider_team_masks.py")
            spec = importlib.util.spec_from_file_location("era_team_mask", helper_path)
            helper = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(helper)
            scratch = directory / "team_input.json"
            write(scratch, {"textures": textures})
            helper.prepare(scratch)
            row["team_cloth"] = read(scratch)["team_cloth"]
            row["team_cloth"]["semantic_visual_review"] = "pending_actual_asset_image"
        material_rows.append(row)
    result.update(materials=material_rows, output=str(output), entry=entry,
                  status="textures_prepared", geometry_prepared=False)
    write(output / "input_spec.json", entry)
    write(texture_report, result)
    return result


def prepare_geometry(entry, output_root, render=False):
    import bpy
    from mathutils import Matrix, Vector
    inspection = inspect(entry)
    if inspection["errors"] or inspection["route"] != "static_ready_for_preparation":
        raise ValueError("Static preparation cannot serve this source: " + str(inspection))
    output = folder(entry, output_root)
    textures = read(output / "textures.json")
    if (output / "manifest.json").exists():
        result = read(output / "manifest.json")
        for rec in result["exports"].values():
            if digest(rec["path"]) != rec["sha256"]:
                raise ValueError("Existing prepared bundle changed")
        return result
    if textures["source"]["sha256"] != inspection["source"]["sha256"]:
        raise ValueError("Texture and geometry source differ")
    target = float(entry["target_cm"])
    if not math.isfinite(target) or target <= 0:
        raise ValueError("Positive physical target required")
    if entry["measure"] not in {"height", "horizontal_max"}:
        raise ValueError("Unknown physical measure")
    helper_spec = importlib.util.spec_from_file_location(
        "era_static_helpers", Path(__file__).with_name("prepare_tripo_environment.py"))
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 2
    bpy.ops.import_scene.gltf(filepath=str(absolute(entry["source"])))
    objects = [o for o in scene.objects if o.type == "MESH"]
    if any(o.type == "ARMATURE" for o in scene.objects):
        raise ValueError("Unexpected armature in static pipeline")
    material_rows = textures["materials"]
    for material in [m for m in bpy.data.materials if m.users]:
        matching = [row for row in material_rows if row["source_name"] == material.name]
        if len(matching) != 1:
            # A single-material unnamed GLB has an unambiguous fallback.
            if len(material_rows) == 1 and len([m for m in bpy.data.materials if m.users]) == 1:
                matching = material_rows
            else:
                raise ValueError("Ambiguous GLB material mapping: " + material.name)
        material.name = matching[0]["slot_name"]
    before_triangles = sum(len(o.data.loop_triangles) for o in objects)
    for obj in objects:
        obj.data.calc_loop_triangles()
    before_triangles = sum(len(o.data.loop_triangles) for o in objects)
    before_uv = helper.uv_signature(objects)
    rotation = Matrix.Rotation(math.radians(float(entry["yaw_degrees"])), 4, "Z")
    matrices = {o: rotation @ o.matrix_world.copy() for o in objects}
    for obj, matrix in matrices.items():
        obj.parent = None
        obj.matrix_world = matrix
    lower, upper = helper.bounds(objects)
    size = upper - lower
    ratio = (target / 100) / (size.z if entry["measure"] == "height" else max(size.x, size.y))
    bottom_centre = Vector(((lower.x + upper.x) / 2, (lower.y + upper.y) / 2, lower.z))
    ground_offset = float(entry.get("ground_offset_cm", 0)) / 100
    normalization = Matrix.Translation(Vector((0, 0, ground_offset))) @ Matrix.Scale(ratio, 4) @ Matrix.Translation(-bottom_centre)
    for obj in objects:
        obj.matrix_world = normalization @ obj.matrix_world
    helper.select(objects)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    terrain_profile = None
    if entry.get("terrain_profile"):
        profile_spec = importlib.util.spec_from_file_location(
            "era_terrain_profile", Path(__file__).with_name("terrain_tile_profile.py"))
        profile_module = importlib.util.module_from_spec(profile_spec)
        profile_spec.loader.exec_module(profile_module)
        terrain_profile = profile_module.apply(objects, entry["terrain_profile"])
    if helper.uv_signature(objects) != before_uv:
        raise ValueError("Normalization changed UVs")
    low, high = helper.bounds(objects)
    # Join only after source slots are named, preserving UVs and material indices.
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    mesh = bpy.context.object
    mesh.name = "SM_" + entry["asset_id"]
    mesh.data.calc_loop_triangles()
    if len(mesh.data.loop_triangles) != before_triangles:
        raise ValueError("Unexpected topology change during join")
    slot_names = [m.name for m in mesh.data.materials]
    dimensions = list((high - low) * 100)
    exports = {}
    for extension in ("fbx", "glb"):
        path = output / (mesh.name + "." + extension)
        if extension == "fbx":
            bpy.ops.export_scene.fbx(
                filepath=str(path), use_selection=True, object_types={"MESH"},
                apply_unit_scale=True, apply_scale_options="FBX_SCALE_UNITS",
                axis_forward="X", axis_up="Z", use_mesh_modifiers=False,
                bake_anim=False, path_mode="STRIP", embed_textures=False)
        else:
            bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB",
                                      use_selection=True, export_animations=False,
                                      export_yup=True, export_apply=False)
        exports[extension] = record(path)
    blend = output / (entry["asset_id"] + ".blend")
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    exports["blend"] = record(blend)
    if render:
        render_preview(bpy, mesh, output)
    result = {
        "schema_version": 1, "asset_id": entry["asset_id"], "kind": entry["kind"],
        "status": "static_prepared_pending_unreal", "source": inspection["source"],
        "tool": record(Path(__file__)), "exports": exports,
        "materials": material_rows, "material_slot_order": slot_names,
        "triangles": before_triangles, "full_pbr": inspection["full_pbr"],
        "units": "cm", "import_uniform_scale": 1,
        "dimensions_cm": dimensions,
        "bounds_cm": {"minimum": [low.x*100, -high.y*100, low.z*100],
                      "maximum": [high.x*100, -low.y*100, high.z*100]},
        "normalization": {"target_cm": target, "measure": entry["measure"],
                          "yaw_degrees": entry["yaw_degrees"], "uniform_scale": ratio,
                          "source_bottom_centre_after_yaw_m": list(bottom_centre),
                          "ground_offset_cm": ground_offset*100,
                          "source_blender_to_final_blender_matrix": [list(row) for row in normalization @ rotation]},
        "anchors_cm": entry.get("anchors_cm", {}),
        "terrain_profile": terrain_profile,
        "anchors_are_explicit_measured_input": bool(entry.get("anchors_cm")),
        "mechanism": entry.get("mechanism", {"status": "not_authored" if entry["kind"] == "turret" else "static"}),
        "animations": {}, "gameplay_approved": False, "production_approved": False,
        "remaining": (["normal_and_metallic_roughness_maps_absent"] if not inspection["full_pbr"] else []) +
                     (["turret_mechanism_and_release_attachment_required"] if entry["kind"] == "turret" else []) +
                     (["three_measured_turret_platforms_required"] if entry["kind"] == "base" and not entry.get("anchors_cm") else []) +
                     ["actual_game_view"],
    }
    if digest(absolute(entry["source"])) != inspection["source"]["sha256"]:
        raise ValueError("Source changed while preparing")
    write(output / "manifest.json", result)
    return result


def render_preview(bpy, mesh, output):
    """Two small real DCC views, no expensive film/repeated gallery renders."""
    from mathutils import Vector
    scene = bpy.context.scene
    points = [mesh.matrix_world @ v.co for v in mesh.data.vertices]
    low = Vector([min(p[i] for p in points) for i in range(3)])
    high = Vector([max(p[i] for p in points) for i in range(3)])
    centre = (low + high) / 2
    span = max(high - low)
    try:
        scene.render.engine = "BLENDER_EEVEE"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    if scene.world is None:
        scene.world = bpy.data.worlds.new("EraStaticPreviewWorld")
    scene.world.color = (.22, .22, .22)
    scene.view_settings.view_transform = "Standard"
    light_data = bpy.data.lights.new("Preview_Key", "AREA")
    light = bpy.data.objects.new("Preview_Key", light_data)
    scene.collection.objects.link(light)
    light.location = centre + Vector((span, -span, span*2))
    light.rotation_euler = (centre-light.location).to_track_quat("-Z", "Y").to_euler()
    light_data.energy = 200*span*span
    light_data.size = span*1.5
    camera_data = bpy.data.cameras.new("Preview_Camera")
    camera = bpy.data.objects.new("Preview_Camera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = span*1.5
    for name, direction in (("front", (2, -3, 1.7)), ("back", (-2, 3, 1.7))):
        camera.location = centre + Vector(direction)*span
        camera.rotation_euler = (centre-camera.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(output / ("preview_" + name + ".png"))
        bpy.ops.render.render(write_still=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--stage", choices=("inspect", "textures", "prepare"), default="inspect")
    parser.add_argument("--render", action="store_true")
    argv = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else sys.argv[1:]
    args = parser.parse_args(argv)
    plan = read(args.plan)
    output_root = plan.get("output_root", str(DEFAULT_OUTPUT))
    results = []
    for entry in plan["entries"]:
        if args.stage == "inspect":
            result = inspect(entry)
        elif args.stage == "textures":
            result = prepare_textures(entry, output_root)
        else:
            result = prepare_geometry(entry, output_root, args.render)
        results.append({"asset_id": entry["asset_id"], "status": result.get("status", result.get("route")),
                        "full_pbr": result.get("full_pbr"), "output": str(folder(entry, output_root)),
                        "errors": result.get("errors", [])})
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "stage": args.stage, "results": results}
    write(args.plan.with_name(args.plan.stem + "_" + args.stage + ".json"), report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
