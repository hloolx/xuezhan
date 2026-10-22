"""Isolated, idempotent Unreal 5.8 asset import from a production manifest.

Outside UE: python Tools/import_art_pilot.py --manifest <manifest> --dry-run
Inside UE: set CIVWAR_ART_MANIFEST, then execute this script via -run=pythonscript.
Optional CIVWAR_ART_REPORT overrides the JSON report path. Default import is isolated.
Set CIVWAR_ART_CREATE_PREVIEW=1 to assemble sibling layout.json in an isolated map.
Set CIVWAR_ART_UPDATE_RUNTIME=1 to register all seven verified environment mothers.
Manifest assets: id, file (project-relative), type (static_mesh/skeletal_mesh),
expected_dimensions_cm, import_materials, combine_meshes, import_scale (default 1).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspect_art_materials import audit_meshes, source_materials, apply_material_overrides, validate_material_overrides


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def token(value):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
        raise ValueError("Unsafe Unreal asset name: " + str(value))
    return value


def load_manifest(path, root=ROOT):
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    batch = token(manifest["batch_id"])
    entries = []
    seen = set()
    for raw in manifest["assets"]:
        item = dict(raw)
        aid = token(item["id"])
        if aid in seen:
            raise ValueError("Duplicate asset id: " + aid)
        seen.add(aid)
        source = (root / item["file"]).resolve()
        if not source.is_file() or source.suffix.lower() not in {".fbx", ".glb", ".gltf"}:
            raise ValueError("Missing or unsupported mesh source: " + str(source))
        item["type"] = item.get("type", "static_mesh")
        if item["type"] not in {"static_mesh", "skeletal_mesh"}:
            raise ValueError("Unsupported asset type: " + item["type"])
        scale = float(item.get("import_scale", 1))
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("import_scale must be positive and finite")
        if source.suffix.lower() != ".fbx" and scale != 1:
            raise ValueError("GLB/glTF scale must be baked in Blender before import")
        dims = item.get("expected_dimensions_cm")
        if dims is not None and (len(dims) != 3 or any(not math.isfinite(float(v)) or float(v) <= 0 for v in dims)):
            raise ValueError("expected_dimensions_cm must have 3 positive finite values")
        item["source"] = str(source)
        item["source_sha256"] = sha256(source)
        overrides = validate_material_overrides(item.get("runtime_material_overrides", {}))
        if overrides and source.suffix.lower() not in {".glb", ".gltf"}:
            raise ValueError("Explicit material overrides require the verified GLTF pipeline")
        # Settings participate in versioning: a changed import scale never reuses old data.
        settings = {k: item.get(k) for k in ["type", "import_scale", "import_materials", "combine_meshes", "skeleton", "force_front_x_axis"]}
        if overrides:
            settings["runtime_material_overrides"] = overrides
        if source.suffix.lower() in {".glb", ".gltf"}:
            settings["material_pipeline"] = "ue58_explicit_pbr_preserve_geometry_v2"
            item["source_materials"] = source_materials(source)
        fingerprint = hashlib.sha256((item["source_sha256"] + json.dumps(settings, sort_keys=True)).encode()).hexdigest()[:12]
        item["destination"] = f"/Game/ArtPilot/{batch}/{aid}/h{fingerprint}"
        entries.append(item)
    if not entries:
        raise ValueError("Manifest contains no assets")
    return manifest, entries


def vec(v):
    return [round(float(v.x), 4), round(float(v.y), 4), round(float(v.z), 4)]


def inspect_asset(unreal, obj):
    result = {"path": obj.get_path_name(), "class": obj.get_class().get_name()}
    if isinstance(obj, unreal.StaticMesh):
        bounds = obj.get_bounds()
        result.update(type="static_mesh", dimensions_cm=[round(v * 2, 4) for v in vec(bounds.box_extent)],
                      origin_cm=vec(bounds.origin), lod_count=obj.get_num_lods(),
                      triangles_lod0=obj.get_num_triangles(0), vertices_lod0=obj.get_num_vertices(0),
                      material_slots=[{"slot": str(s.material_slot_name), "material": s.material_interface.get_path_name() if s.material_interface else None}
                                      for s in obj.get_editor_property("static_materials")])
        description = obj.get_static_mesh_description(0)
        result["source_mesh_triangles_lod0"] = description.get_triangle_count() if description else None
        result["source_mesh_vertices_lod0"] = description.get_vertex_count() if description else None
        # Commandlets do not instantiate StaticMeshEditorSubsystem. Read the
        # reflected struct directly; no editor subsystem or UI is required.
        nanite = obj.get_editor_property("nanite_settings")
        result["nanite_enabled"] = bool(nanite.get_editor_property("enabled"))
        result["triangle_count_semantics"] = "triangles_lod0 is render data (Nanite fallback when enabled); source_mesh_triangles_lod0 is MeshDescription"
    elif isinstance(obj, unreal.SkeletalMesh):
        bounds = obj.get_bounds()
        skeleton = obj.get_editor_property("skeleton")
        result.update(type="skeletal_mesh", dimensions_cm=[round(v * 2, 4) for v in vec(bounds.box_extent)],
                      origin_cm=vec(bounds.origin), skeleton=skeleton.get_path_name() if skeleton else None,
                      material_slots=[{"slot": str(s.material_slot_name), "material": s.material_interface.get_path_name() if s.material_interface else None}
                                      for s in obj.get_editor_property("materials")])
    return result


def import_one(unreal, item):
    lib = unreal.EditorAssetLibrary
    existing = lib.list_assets(item["destination"], recursive=True, include_folder=False) if lib.does_directory_exist(item["destination"]) else []
    if existing:
        objects = [lib.load_asset(p) for p in existing]
        status = "reused_existing"
    else:
        task = unreal.AssetImportTask()
        for key, value in {"filename": item["source"], "destination_path": item["destination"],
                           "destination_name": item["id"], "replace_existing": False,
                           "automated": True, "save": True, "async_": False}.items():
            task.set_editor_property(key, value)
        if Path(item["source"]).suffix.lower() == ".fbx":
            # Explicit legacy FBX factory avoids project-level Interchange defaults silently
            # ignoring FbxImportUI settings; GLB uses the available Interchange importer.
            task.set_editor_property("factory", unreal.FbxFactory())
            ui = unreal.FbxImportUI()
            skeletal = item["type"] == "skeletal_mesh"
            props = {"automated_import_should_detect_type": False, "import_mesh": True,
                     "import_as_skeletal": skeletal, "import_animations": False,
                     "create_physics_asset": False, "import_materials": item.get("import_materials", True),
                     "import_textures": item.get("import_materials", True),
                     "mesh_type_to_import": unreal.FBXImportType.FBXIT_SKELETAL_MESH if skeletal else unreal.FBXImportType.FBXIT_STATIC_MESH}
            for key, value in props.items():
                ui.set_editor_property(key, value)
            data = ui.get_editor_property("skeletal_mesh_import_data" if skeletal else "static_mesh_import_data")
            for key, value in {"import_uniform_scale": float(item.get("import_scale", 1)), "convert_scene": True,
                               "convert_scene_unit": True, "force_front_x_axis": item.get("force_front_x_axis", False)}.items():
                data.set_editor_property(key, value)
            if not skeletal:
                data.set_editor_property("combine_meshes", item.get("combine_meshes", True))
                data.set_editor_property("auto_generate_collision", False)
            if item.get("skeleton"):
                skeleton = lib.load_asset(item["skeleton"])
                if not isinstance(skeleton, unreal.Skeleton):
                    raise ValueError("Skeleton missing or wrong type: " + item["skeleton"])
                if not item["skeleton"].startswith("/Game/ArtPilot/"):
                    raise ValueError("Skeleton must be isolated under /Game/ArtPilot to avoid editing production skeletons")
                ui.set_editor_property("skeleton", skeleton)
            task.set_editor_property("options", ui)
        else:
            # UE 5.8 AssetTools.cpp consumes this stack override from task.Options.
            # Instantiate defaults rather than loading user/project pipeline presets.
            # Do not turn GLB PBR into a flat fallback or reuse another asset's material.
            pipeline = unreal.InterchangeGenericAssetsPipeline()
            pipeline.set_editor_property("asset_name", item["id"])
            pipeline.set_editor_property("scene_name_sub_folder", False)
            pipeline.set_editor_property("asset_type_sub_folders", False)
            material_pipeline = pipeline.get_editor_property("material_pipeline")
            enabled = item.get("import_materials", True)
            material_pipeline.set_editor_property("import_materials", enabled)
            material_pipeline.set_editor_property("create_new_materials", enabled)
            material_pipeline.set_editor_property("reuse_existing_materials", False)
            material_pipeline.set_editor_property("material_import", unreal.InterchangeMaterialImportOption.IMPORT_AS_MATERIALS)
            material_pipeline.get_editor_property("texture_pipeline").set_editor_property("import_textures", enabled)
            mesh_pipeline = pipeline.get_editor_property("mesh_pipeline")
            skeletal = item["type"] == "skeletal_mesh"
            mesh_pipeline.set_editor_property("import_static_meshes", not skeletal)
            mesh_pipeline.set_editor_property("import_skeletal_meshes", skeletal)
            mesh_pipeline.set_editor_property("create_physics_asset", False)
            mesh_pipeline.set_editor_property("collision", False)
            if not skeletal:
                # UE 5.8 defaults BuildNanite=true with threshold=0. For these
                # already-low-poly mothers preserve ordinary LOD0 source geometry.
                mesh_pipeline.set_editor_property("build_nanite", False)
                mesh_pipeline.set_editor_property("lod_group", "None")
                behavior = unreal.InterchangeCombineStaticMeshesBehavior
                mesh_pipeline.set_editor_property("combine_static_meshes_behavior", behavior.ALL if item.get("combine_meshes", True) else behavior.DO_NOT_COMBINE)
            geometry = item["source_materials"]["geometry"]
            primitives = geometry["primitives"]
            common_meshes = pipeline.get_editor_property("common_meshes_properties")
            common_meshes.set_editor_property("remove_degenerates", False)
            common_meshes.set_editor_property("recompute_normals", not all(p["has_normals"] for p in primitives))
            common_meshes.set_editor_property("recompute_tangents", not all(p["has_tangents"] for p in primitives))
            pipeline.get_editor_property("animation_pipeline").set_editor_property("import_animations", False)
            if item.get("skeleton"):
                # This branch previously ignored skeleton entirely. Do not silently
                # create or mutate a production skeleton through an untested path.
                raise ValueError("GLB skeleton reuse is not configured; use the explicit FBX skeletal pipeline")
            stack = unreal.InterchangePipelineStackOverride()
            stack.add_pipeline(pipeline)
            task.set_editor_property("options", stack)
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        objects = list(task.get_objects())
        if not objects:
            objects = [lib.load_asset(p) for p in task.get_editor_property("imported_object_paths")]
        status = "imported"
    objects = [o for o in objects if o]
    mesh_objects = [o for o in objects if isinstance(o, (unreal.StaticMesh, unreal.SkeletalMesh))]
    overrides = item.get("runtime_material_overrides", {})
    override_evidence = apply_material_overrides(unreal, mesh_objects, overrides, item["destination"])
    inspected = [inspect_asset(unreal, obj) for obj in objects]
    meshes = [o for o in inspected if o.get("type") in {"static_mesh", "skeletal_mesh"}]
    warnings = []
    if not meshes:
        raise RuntimeError("Import produced no mesh: " + item["id"])
    if any(o["type"] != item["type"] for o in meshes):
        warnings.append("imported_mesh_type_mismatch")
    expected = item.get("expected_dimensions_cm")
    if expected and len(meshes) == 1:
        errors = [abs(a - b) / b for a, b in zip(meshes[0]["dimensions_cm"], expected)]
        if any(e > 0.05 for e in errors):
            warnings.append("dimensions_differ_over_5_percent_check_scale_and_axis")
    elif expected:
        warnings.append("multiple_meshes_require_assembly_dimension_review")
    if any(not m.get("material_slots") or any(s["material"] is None for s in m["material_slots"]) for m in meshes):
        warnings.append("missing_material_assignment")
    source_geometry = item.get("source_materials", {}).get("geometry")
    if source_geometry and len(meshes) == 1 and item["type"] == "static_mesh":
        if meshes[0]["nanite_enabled"]:
            warnings.append("unexpected_nanite_enabled_for_low_poly_mother")
        if source_geometry["mesh_count"] == source_geometry["mesh_node_count"] == 1:
            triangles = source_geometry["unique_mesh_triangles"]
            if triangles is not None and (meshes[0]["triangles_lod0"] != triangles or meshes[0]["source_mesh_triangles_lod0"] != triangles):
                warnings.append("source_and_unreal_triangle_counts_differ")
    material_audit = audit_meshes(unreal, mesh_objects, item["source"], repair=True, overrides=overrides)
    if material_audit["warnings"]:
        warnings.append("material_audit_requires_review")
    return {"id": item["id"], "status": status, "source": item["source"], "source_sha256": item["source_sha256"],
            "destination": item["destination"], "expected_type": item["type"], "expected_dimensions_cm": expected,
            "assets": inspected, "source_geometry": source_geometry, "material_audit": material_audit, "material_override_evidence": override_evidence,
            "runtime_material_overrides": overrides, "warnings": warnings, "production_approved": False}


def create_preview(unreal, manifest, results, layout_path):
    """Create an inspectable map; this never modifies the production Battlefield map."""
    layout = json.loads(layout_path.read_text(encoding="utf-8-sig"))
    if layout.get("units") != "cm":
        raise ValueError("Preview layout must declare units=cm")
    meshes = {}
    for result in results:
        imported = [a["path"] for a in result.get("assets", []) if a.get("type") == "static_mesh"]
        if len(imported) == 1:
            meshes[result["id"]] = imported[0]
    instances = layout.get("instances", []) + layout.get("preview_instances", [])
    for instance in instances:
        if instance["asset_id"] not in meshes:
            raise ValueError("Preview has no unambiguous imported mesh for " + instance["asset_id"])
        for field in ("location_cm", "rotation_deg", "scale"):
            values = instance[field]
            if len(values) != 3 or any(not math.isfinite(float(v)) for v in values):
                raise ValueError("Invalid preview transform: " + field)
    fingerprint = hashlib.sha256(json.dumps({"layout": layout, "meshes": meshes}, sort_keys=True).encode()).hexdigest()[:12]
    level_path = f"/Game/ArtPilot/{token(manifest['batch_id'])}/Preview_{fingerprint}"
    if unreal.EditorAssetLibrary.does_asset_exist(level_path):
        return {"path": level_path, "status": "reused_existing", "instance_count": len(instances)}
    level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not level_editor.new_level(level_path):
        raise RuntimeError("Could not create isolated preview map")
    actor_editor = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for instance in instances:
        position = unreal.Vector(*instance["location_cm"])
        angles = instance["rotation_deg"]
        rotation = unreal.Rotator(pitch=angles[1], yaw=angles[2], roll=angles[0])
        actor = actor_editor.spawn_actor_from_class(unreal.StaticMeshActor, position, rotation)
        actor.set_actor_label(instance["id"])
        actor.get_editor_property("static_mesh_component").set_static_mesh(unreal.EditorAssetLibrary.load_asset(meshes[instance["asset_id"]]))
        actor.set_actor_scale3d(unreal.Vector(*instance["scale"]))
    sun = actor_editor.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 3000), unreal.Rotator(pitch=-45, yaw=-35, roll=0))
    sun.set_actor_label("Preview_Sun")
    light = sun.get_component_by_class(unreal.DirectionalLightComponent)
    light.set_intensity(3.5)
    light.set_editor_property("atmosphere_sun_light", True)
    actor_editor.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))
    sky = actor_editor.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 0))
    sky.get_component_by_class(unreal.SkyLightComponent).set_editor_property("real_time_capture", True)
    camera_position = unreal.Vector(-4000, -6500, 3700)
    camera_rotation = unreal.MathLibrary.find_look_at_rotation(camera_position, unreal.Vector(0, 0, 0))
    camera = actor_editor.spawn_actor_from_class(unreal.CameraActor, camera_position, camera_rotation)
    camera.set_actor_label("Preview_OverviewCamera")
    camera.get_component_by_class(unreal.CameraComponent).set_field_of_view(45)
    if not level_editor.save_current_level():
        raise RuntimeError("Preview map could not be saved")
    return {"path": level_path, "status": "created", "instance_count": len(instances),
            "camera_actor": "Preview_OverviewCamera", "note": "Static layout review map; not a gameplay or runtime integration test."}


def write_environment_runtime_map(manifest, results, root=ROOT):
    required = {"Env_BoulderA", "Env_BoulderB", "Env_RockSlab", "Env_Shrub", "Env_Pine", "Env_Broadleaf", "Env_GrassClump"}
    candidates = {r["id"]: r for r in results if r["id"] in required}
    if set(candidates) != required:
        raise ValueError("Runtime environment registration requires all seven mother meshes")
    mapping, cook_paths = {}, []
    for aid, result in sorted(candidates.items()):
        meshes = [a for a in result.get("assets", []) if a.get("type") == "static_mesh"]
        if result.get("status") not in {"imported", "reused_existing"} or result.get("warnings") or len(meshes) != 1:
            raise ValueError("Runtime registration requires a clean single static mesh import: " + aid)
        if not result.get("expected_dimensions_cm"):
            raise ValueError("Runtime registration requires expected DCC dimensions: " + aid)
        mesh = meshes[0]
        if not mesh["path"].startswith("/Game/ArtPilot/"):
            raise ValueError("Environment mesh outside isolated art directory")
        mapping[aid] = {"object_path": mesh["path"], "source": result["source"], "source_sha256": result["source_sha256"],
                        "dimensions_cm": mesh["dimensions_cm"], "bounds_origin_cm": mesh["origin_cm"],
                        "triangles_lod0": mesh["triangles_lod0"], "runtime_material_overrides": result.get("runtime_material_overrides", {})}
        cook_paths.append(result["destination"])
    document = {"schema_version": 1, "batch_id": manifest["batch_id"], "status": "runtime_art_pilot",
                "production_approved": False, "note": "Bounds and import verified; gameplay camera review still required. Missing meshes fall back to primitives.",
                "assets": mapping}
    destination = root / "Content/Data/EnvironmentArt.json"
    config = root / "Config/DefaultGame.ini"
    config_text = config.read_text(encoding="utf-8-sig")
    start, end = "; BEGIN CIVWAR ENVIRONMENT ART COOK", "; END CIVWAR ENVIRONMENT ART COOK"
    block = start + "\n; Generated by Tools/import_art_pilot.py; mothers and their material dependencies only.\n"
    block += "\n".join('+DirectoriesToAlwaysCook=(Path="' + p + '")' for p in cook_paths) + "\n" + end
    if start in config_text:
        if end not in config_text:
            raise ValueError("Incomplete managed environment cook block")
        config_text = re.sub(re.escape(start) + r"[\s\S]*?" + re.escape(end), lambda _: block, config_text)
    else:
        section = "[/Script/UnrealEd.ProjectPackagingSettings]"
        if section not in config_text:
            config_text = config_text.rstrip() + "\n\n" + section + "\n" + block + "\n"
        else:
            # Insert directly after the correct section header, never into an unrelated section.
            config_text = config_text.replace(section, section + "\n" + block, 1)
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup_folder = root / "Saved/ArtImportBackups"
    backup_folder.mkdir(parents=True, exist_ok=True)
    backups = []
    for previous_file in (destination, config):
        if previous_file.exists():
            content = previous_file.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            backup = backup_folder / (previous_file.stem + "_" + digest[:16] + previous_file.suffix)
            if backup.exists():
                if sha256(backup) != digest:
                    raise ValueError("Existing runtime backup does not match its hash")
            else:
                with backup.open("xb") as stream:
                    stream.write(content)
            backups.append({"original": str(previous_file), "backup": str(backup), "sha256": digest})
    destination.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config.write_text(config_text, encoding="utf-8")
    return {"status": "registered", "map": str(destination), "asset_count": len(mapping), "cook_config": str(config),
            "cook_paths": cook_paths, "backups": backups, "requires_editor_target_rebuild": True, "gameplay_visual_review": "pending"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=os.environ.get("CIVWAR_ART_MANIFEST"))
    parser.add_argument("--report", default=os.environ.get("CIVWAR_ART_REPORT"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--create-preview", action="store_true", default=os.environ.get("CIVWAR_ART_CREATE_PREVIEW") == "1")
    parser.add_argument("--layout", default=os.environ.get("CIVWAR_ART_LAYOUT"))
    parser.add_argument("--update-runtime", action="store_true", default=os.environ.get("CIVWAR_ART_UPDATE_RUNTIME") == "1")
    args, _ = parser.parse_known_args()
    if not args.manifest:
        raise ValueError("Set CIVWAR_ART_MANIFEST or pass --manifest")
    path = (ROOT / args.manifest).resolve()
    manifest, entries = load_manifest(path)
    report_path = Path(args.report).resolve() if args.report else path.with_name("unreal_import_report.json")
    report = {"schema_version": 1, "batch_id": manifest["batch_id"], "manifest": str(path),
              "created_at": datetime.now(timezone.utc).isoformat(), "dry_run": args.dry_run,
              "production_approved": False, "runtime_integrated": False, "results": []}
    if args.dry_run:
        report["results"] = entries
    else:
        import unreal
        for item in entries:
            try:
                result = import_one(unreal, item)
                unreal.log("[ArtPilot] " + item["id"] + ": " + result["status"])
            except Exception as exc:
                result = {"id": item["id"], "status": "failed", "error": str(exc)}
                unreal.log_error("[ArtPilot] " + item["id"] + ": " + str(exc))
            report["results"].append(result)
        if args.create_preview and not any(r.get("status") == "failed" for r in report["results"]):
            layout_path = (ROOT / args.layout).resolve() if args.layout else path.with_name("layout.json")
            try:
                report["preview_map"] = create_preview(unreal, manifest, report["results"], layout_path)
            except Exception as exc:
                report["preview_map"] = {"status": "failed", "error": str(exc)}
                unreal.log_error("[ArtPilot] Preview: " + str(exc))
        if args.update_runtime:
            try:
                report["runtime_registration"] = write_environment_runtime_map(manifest, report["results"])
                report["runtime_integration_state"] = "registered_pending_build_and_playtest"
            except Exception as exc:
                report["runtime_registration"] = {"status": "failed", "error": str(exc)}
                unreal.log_error("[ArtPilot] Runtime mapping: " + str(exc))
    report["failed"] = (sum(r.get("status") == "failed" for r in report["results"])
                        + int(report.get("preview_map", {}).get("status") == "failed")
                        + int(report.get("runtime_registration", {}).get("status") == "failed"))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("ArtPilot report: " + str(report_path))
    if report["failed"]:
        raise RuntimeError(str(report["failed"]) + " imports failed; see report")


if __name__ == "__main__":
    main()
