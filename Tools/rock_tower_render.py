"""Controlled editor-only RockTower assembly captures; never saves Content or starts UE."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import itertools
import json
import math
import os
from pathlib import Path
import struct
import sys
import time


sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "Unreal"))
import rock_tower_ue as rock
from render_stoneaxe_teamcolor import parse_texture_dump, textures_resident

VERSION = "rock_tower_actual_attachment_render_v2"
BASE_FRESH = rock.ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/base_stone_v01/ue_fresh_preflight/fresh_01.json"
TEAM_MATERIAL = "/Game/Art/M_CWStylized.M_CWStylized"
TEAM_COLORS = ((.10, .32, .95, 1), (.92, .16, .10, 1))
SHOTS = [
    {"label": "01_ready_blue", "team": 0, "crop": "wide", "slot": 0, "pitch": 35, "stone": True},
    {"label": "02_ready_red_yaw180", "team": 1, "crop": "wide", "slot": 0, "pitch": 35, "stone": True},
    {"label": "03_fit_front_negative_y", "team": 0, "crop": "fit", "slot": 0, "pitch": 35, "stone": True},
    {"label": "04_fit_front_positive_y", "team": 0, "crop": "fit", "slot": 1, "pitch": 35, "stone": True},
    {"label": "05_fit_rear", "team": 0, "crop": "fit", "slot": 2, "pitch": 35, "stone": True},
    {"label": "06_release_stone_hidden", "team": 0, "crop": "mechanism", "slot": 0, "pitch": 35, "stone": False},
    {"label": "07_followthrough", "team": 0, "crop": "mechanism", "slot": 0, "pitch": -40, "stone": False},
    {"label": "08_empty_return", "team": 0, "crop": "mechanism", "slot": 0, "pitch": 12.5, "stone": False},
    {"label": "09_loaded_reload", "team": 0, "crop": "mechanism", "slot": 0, "pitch": 65, "stone": True},
    {"label": "10_cup_rope_connection", "team": 0, "crop": "cup", "slot": 0, "pitch": 35, "stone": False},
    {"label": "11_flag_support_blue", "team": 0, "crop": "flag", "slot": 0, "pitch": 35, "stone": True},
    {"label": "12_flag_original_control", "team": 0, "crop": "flag", "slot": 0, "pitch": 35, "stone": True, "original_cloth": True},
]
SESSION = None


def coordinates(vector):
    return [float(vector.x), float(vector.y), float(vector.z)]


def add(first, second):
    return [left + right for left, right in zip(first, second)]


def rotate(point, yaw=0, pitch=0):
    yaw_angle, pitch_angle = math.radians(yaw), math.radians(pitch)
    forward = math.cos(pitch_angle) * point[0] - math.sin(pitch_angle) * point[2]
    up = math.sin(pitch_angle) * point[0] + math.cos(pitch_angle) * point[2]
    return [math.cos(yaw_angle) * forward - math.sin(yaw_angle) * point[1],
            math.sin(yaw_angle) * forward + math.cos(yaw_angle) * point[1], up]


def component_point(context, slot, name, point, yaw, pitch):
    platform = context["platforms"][slot]
    mount = platform["mount_ue_cm"]
    upper = add(mount, platform["upper_local_translation_cm"])
    if name.startswith("Adapter_"):
        local = add(mount, point)
    elif name in {"Frame", "Cloth"}:
        local = add(upper, point)
    elif name in {"Arm", "Stone"}:
        pivot = add(upper, context["anchors"]["ArmPivot"]["translation_cm"])
        arm_local = add(context["anchors"]["release_point"]["translation_cm"], point) if name == "Stone" else point
        local = add(pivot, rotate(arm_local, pitch=pitch))
    else:
        raise ValueError("Unknown rigid component")
    return rotate(local, yaw=yaw)


def bounds_corners(bounds):
    return list(itertools.product(*zip(bounds["min"], bounds["max"])))


def union_bounds(bounds):
    return {"min": [min(item["min"][axis] for item in bounds) for axis in range(3)],
            "max": [max(item["max"][axis] for item in bounds) for axis in range(3)]}


def fit_camera(bounds, direction, fov=38):
    target = [(low + high) / 2 for low, high in zip(bounds["min"], bounds["max"])]
    radius = max(math.dist(target, corner) for corner in bounds_corners(bounds))
    length = math.sqrt(sum(value * value for value in direction))
    if not math.isfinite(radius) or radius <= 0 or length <= 0 or not 10 <= fov <= 90:
        raise ValueError("Finite nonempty bounds, direction and safe FOV required")
    distance = radius / math.sin(math.radians(fov / 2)) * 1.12
    return {"target": target, "location": add(target, [value / length * distance for value in direction]),
            "fov": fov, "focus_bounds": bounds, "fit_sphere_radius_cm": radius, "distance_cm": distance}


def check_fresh(report, plan):
    if report.get("status") != "rock_tower_fresh_reopen_structural_checks_passed" or report.get("dry_run") is not False or not report.get("structural_checks_passed") or not report.get("validated_in_fresh_process"):
        raise ValueError("Actual successful independent RockTower fresh reopen is required")
    if not report.get("initial_process_id") or not report.get("validation_process_id") or report["initial_process_id"] == report["validation_process_id"]:
        raise ValueError("Different initial/fresh process IDs are required")
    if report.get("destination") != plan["destination"] or report.get("source_files") != plan["source_evidence"]:
        raise ValueError("Fresh report is not bound to current frozen source/tool bytes")
    if report.get("disk_dependency_validation", {}).get("status") != "passed" or report.get("package_files") != report["disk_dependency_validation"]["files"]:
        raise ValueError("Complete saved/fresh package proof required")
    expected_keys = {entry["config_key"] for entry in plan["entries"]}
    if set(report.get("meshes", {})) != expected_keys or len(set(report["meshes"].values())) != 7:
        raise ValueError("Seven unique actual mesh mappings are required")
    actual_meshes = {record["asset_path"] for record in report["package_files"] if record["class_name"] == "StaticMesh"}
    if actual_meshes != set(report["meshes"].values()):
        raise ValueError("Mesh mapping differs from saved StaticMesh packages")


def input_context(path):
    plan = rock.dry_plan()
    report = rock.read_json(path)
    check_fresh(report, plan)
    rock.check_records(report["package_files"] + report["source_files"])
    base = rock.read_json(BASE_FRESH)
    if base.get("status") != "base_stone_fresh_reopen_structural_and_coordinate_checks_passed" or not base.get("validated_in_fresh_process") or base["execution_process_id"] == base["initial_process_id"] or not base.get("source_and_all_five_packages_unchanged"):
        raise ValueError("Actual original Base fresh reopen is required")
    base_files = base["disk_dependency_validation"]["files"]
    if len(base_files) != 5:
        raise ValueError("Original Base must retain all five persisted packages")
    rock.check_records(base_files + base["source_evidence"])
    team_file = rock.ROOT / "Content/Art/M_CWStylized.uasset"
    dependencies = report["package_files"] + report["source_files"] + base_files + base["source_evidence"]
    dependencies.extend([rock.file_record(path), rock.file_record(BASE_FRESH), rock.file_record(team_file),
                         rock.file_record(__file__), rock.file_record(rock.ROOT / "Tools/Unreal/render_stoneaxe_teamcolor.py")])
    textures = [record["asset_path"] for record in base_files if record["class_name"] == "Texture2D"]
    if len(textures) != 3:
        raise ValueError("Exactly three original Base PBR textures required")
    return {"rock": report, "plan": plan, "base": base, "base_mesh": base["mesh"]["path"],
            "base_textures": textures, "dependencies": dependencies, "anchors": plan["anchors"],
            "platforms": plan["platforms"], "source_bounds": {entry["config_key"]: entry["bounds_ue_cm"] for entry in plan["entries"]}}


def validate_png(path, size):
    data = Path(path).read_bytes()
    if len(data) < 1000 or data[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", data[16:24]) != (size, size):
        raise ValueError("Actual screenshot size/PNG payload invalid")


class RockReview:
    def __init__(self, unreal, args, context):
        self.unreal, self.args, self.context = unreal, args, context
        self.started = time.monotonic()
        self.handle, self.finished, self.index, self.counter = None, False, 0, 0
        self.in_tick = False
        self.stage = "resources"
        self.report = {"version": VERSION, "status": "running", "execution_process_id": os.getpid(),
                       "created_at": datetime.now(timezone.utc).isoformat(), "fresh_report": rock.file_record(args.fresh_report),
                       "tool": rock.file_record(__file__), "images": [], "source_files": context["dependencies"],
                       "visual_approved": False, "runtime_approved": False, "production_approved": False,
                       "scope": "Controlled unsaved editor assembly with actual components/meshes, not live gameplay or production approval.",
                       "limits": ["Five StaticMeshComponents per turret are hosted by transient StaticMeshActors; runtime Actor allocation is not certified here.",
                                  "Twelve material sections per turret are structural counts, not measured draw calls.",
                                  "Controlled arm phase poses do not prove authoritative FireSeq/network timing.",
                                  "Original Base PBR retained; only turret cloth gets a transient runtime-equivalent team-color material."]}

    def spawn_mesh(self, name, asset, parent=None, location=(0, 0, 0)):
        unreal = self.unreal
        actor = self.editor.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0))
        actor.set_actor_label(name)
        component = actor.get_component_by_class(unreal.StaticMeshComponent)
        component.set_mobility(unreal.ComponentMobility.MOVABLE)
        component.set_static_mesh(asset)
        component.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        actor.set_actor_scale3d(unreal.Vector(1, 1, 1))
        if parent and not actor.attach_to_actor(parent, "", unreal.AttachmentRule.KEEP_RELATIVE, unreal.AttachmentRule.KEEP_RELATIVE, unreal.AttachmentRule.KEEP_RELATIVE, False):
            raise ValueError("Actual actor attachment failed: " + name)
        actor.set_actor_relative_location(unreal.Vector(*location), False, False)
        actor.set_actor_relative_rotation(unreal.Rotator(pitch=0, yaw=0, roll=0), False, False)
        return actor, component

    def setup(self):
        unreal = self.unreal
        command = unreal.SystemLibrary.get_command_line().lower()
        if "nullrhi" in command or "forcelogflush" not in command or not self.args.log_file or not self.args.log_file.is_file():
            raise ValueError("Actual RHI, -FORCELOGFLUSH and current log path required")
        self.world = unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
        if not self.world:
            raise ValueError("Could not create unsaved isolated editor map")
        self.editor = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        self.level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        self.level_editor.editor_set_game_view(True)
        for command in ("t.MaxFPS 15", "r.VSync 0", "r.ScreenPercentage 100", "r.DynamicGlobalIlluminationMethod 0",
                        "r.ReflectionMethod 0", "r.Shadow.Virtual.Enable 0", "r.EyeAdaptationQuality 0"):
            unreal.SystemLibrary.execute_console_command(self.world, command)
        library = unreal.EditorAssetLibrary
        plan = self.context["plan"]
        rock.check_package_set(plan, self.context["rock"]["package_files"], library.list_assets(plan["destination"], recursive=True, include_folder=False), Path(unreal.Paths.project_content_dir()).resolve())
        self.meshes = {name: library.load_asset(path) for name, path in self.context["rock"]["meshes"].items()}
        base_mesh = library.load_asset(self.context["base_mesh"])
        if not isinstance(base_mesh, unreal.StaticMesh) or not all(isinstance(mesh, unreal.StaticMesh) for mesh in self.meshes.values()):
            raise ValueError("Persisted real Base/RockTower meshes failed to load")
        self.base_actor, self.base_component = self.spawn_mesh("RockTowerReview_OriginalTripoBase", base_mesh)
        self.stylized = library.load_asset(TEAM_MATERIAL)
        if not isinstance(self.stylized, unreal.Material):
            raise ValueError("Actual runtime cloth material is unavailable; no fallback")
        vectors = set(map(str, unreal.MaterialEditingLibrary.get_vector_parameter_names(self.stylized)))
        scalars = set(map(str, unreal.MaterialEditingLibrary.get_scalar_parameter_names(self.stylized)))
        if "Color" not in vectors or not {"Roughness", "Metallic", "Emissive"} <= scalars:
            raise ValueError("Runtime material parameters do not match C++ CWVisual::MakeMaterial")
        self.slots = []
        for slot, platform in enumerate(self.context["platforms"]):
            mount = platform["mount_ue_cm"]
            upper = add(mount, platform["upper_local_translation_cm"])
            adapter_name = "Adapter_" + platform["id"]
            components = {adapter_name: self.spawn_mesh(f"Slot{slot}_{adapter_name}", self.meshes[adapter_name], self.base_actor, mount)}
            for name in ("Frame", "Cloth"):
                components[name] = self.spawn_mesh(f"Slot{slot}_{name}", self.meshes[name], self.base_actor, upper)
            components["Arm"] = self.spawn_mesh(f"Slot{slot}_Arm", self.meshes["Arm"], self.base_actor, add(upper, self.context["anchors"]["ArmPivot"]["translation_cm"]))
            components["Stone"] = self.spawn_mesh(f"Slot{slot}_Stone", self.meshes["Stone"], components["Arm"][0], self.context["anchors"]["release_point"]["translation_cm"])
            mid = components["Cloth"][1].create_dynamic_material_instance(0, self.stylized, f"RockTowerClothReview{slot}")
            if not isinstance(mid, unreal.MaterialInstanceDynamic):
                raise ValueError("Transient cloth material creation failed")
            for name, value in (("Roughness", .6600000262260437), ("Metallic", 0), ("Emissive", 0)):
                mid.set_scalar_parameter_value(name, value)
            self.slots.append({"components": components, "mid": mid})
        ground, ground_component = self.spawn_mesh("RockTowerReviewGround", library.load_asset("/Engine/BasicShapes/Plane"), location=(0, 0, -.3))
        ground.set_actor_scale3d(unreal.Vector(28, 28, 1))
        for pitch, yaw, intensity, shadow in ((-45, -35, 4.0, True), (-30, 140, 1.5, True), (-18, 125, 2.0, False)):
            light = self.editor.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 600), unreal.Rotator(pitch=pitch, yaw=yaw, roll=0))
            component = light.get_component_by_class(unreal.DirectionalLightComponent)
            component.set_intensity(intensity)
            component.set_cast_shadows(shadow)
        self.camera = self.editor.spawn_actor_from_class(unreal.CameraActor, unreal.Vector(1000, -850, 600))
        self.camera_component = self.camera.get_component_by_class(unreal.CameraComponent)
        self.camera_component.set_editor_property("constrain_aspect_ratio", False)
        self.required_paths = set(self.context["base_textures"])
        unreal.SystemLibrary.execute_console_command(self.world, "Editor.AsyncAssetCompilationFinishAll")
        for path in self.required_paths:
            library.load_asset(path).set_force_mip_levels_to_be_resident(self.args.timeout + 20, 0)
        self.base_component.prestream_textures(self.args.timeout + 20, True, 0)
        self.resource_started = self.last_request = time.monotonic()
        self.dump = self.request_dump()
        self.report["resource_preparation"] = {"compile_flush": "Editor.AsyncAssetCompilationFinishAll",
            "required_texture_paths": sorted(self.required_paths), "source": "Only original Base3 PBR textures; RockTower has no texture payloads.",
            "stream_request_seconds": self.args.timeout + 20, "texture_settings_modified": False}
        unreal.EditorPythonScripting.set_keep_python_script_alive(True)
        self.handle = unreal.register_slate_post_tick_callback(self.tick)

    def request_dump(self):
        if self.finished:
            raise ValueError("Finished session cannot queue work")
        self.counter += 1
        token = f"ROCK_TOWER_BASE_RESIDENCY_{os.getpid()}_{self.counter}"
        self.unreal.log(token + "_BEGIN")
        self.unreal.SystemLibrary.execute_console_command(self.world, "ListTextures -CSV")
        self.unreal.log(token + "_END")
        return token + "_BEGIN", token + "_END"

    def actor_bounds(self, actor):
        origin, extent = actor.get_actor_bounds(False, False)
        return {"min": [value - radius for value, radius in zip(coordinates(origin), coordinates(extent))],
                "max": [value + radius for value, radius in zip(coordinates(origin), coordinates(extent))]}

    def prepare(self):
        unreal = self.unreal
        self.shot = SHOTS[self.index]
        self.yaw = self.shot["team"] * 180
        self.base_actor.set_actor_rotation(unreal.Rotator(pitch=0, yaw=self.yaw, roll=0), False)
        for slot, item in enumerate(self.slots):
            pitch = self.shot["pitch"] if slot == self.shot["slot"] else 35
            stone_visible = self.shot["stone"] if slot == self.shot["slot"] else True
            item["components"]["Arm"][0].set_actor_relative_rotation(unreal.Rotator(pitch=pitch, yaw=0, roll=0), False, False)
            item["components"]["Stone"][1].set_visibility(stone_visible, False)
            color = TEAM_COLORS[self.shot["team"]]
            item["mid"].set_vector_parameter_value("Color", unreal.LinearColor(*color))
            cloth = self.meshes["Cloth"].get_material(0) if self.shot.get("original_cloth") else item["mid"]
            item["components"]["Cloth"][1].set_material(0, cloth)
        self.phase_started, self.tick_count, self.stage = time.monotonic(), 0, "settle"

    def audit_components(self):
        unreal = self.unreal
        base_transform = self.base_component.get_world_transform()
        if max(abs(value - 1) for value in coordinates(base_transform.scale3d)) > 1e-6 or math.dist(coordinates(base_transform.translation), (0, 0, 0)) > .001:
            raise ValueError("Base origin/scale changed; no extra bottom alignment permitted")
        records = []
        for slot, item in enumerate(self.slots):
            pitch = self.shot["pitch"] if slot == self.shot["slot"] else 35
            stone_visible = self.shot["stone"] if slot == self.shot["slot"] else True
            components = []
            for name, (actor, component) in item["components"].items():
                transform = component.get_world_transform()
                scale = coordinates(transform.scale3d)
                if max(abs(value - 1) for value in scale) > 1e-6:
                    raise ValueError("All Base/turret transforms must have positive unit scales")
                parent = item["components"]["Arm"][1] if name == "Stone" else self.base_component
                if component.get_attach_parent() != parent or component.get_editor_property("mobility") != unreal.ComponentMobility.MOVABLE:
                    raise ValueError("Real component attachment/mobility differs from planned rigid chain")
                actual_points, errors = [], []
                for point in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)):
                    actual = coordinates(unreal.MathLibrary.transform_location(transform, unreal.Vector(*point)))
                    wanted = component_point(self.context, slot, name, point, self.yaw, pitch)
                    actual_points.append(actual)
                    errors.append(math.dist(actual, wanted))
                if max(errors) > .001:
                    raise ValueError("Actual world rigid basis differs from physical mount/pivot: " + name)
                expected_points = [component_point(self.context, slot, name, point, self.yaw, pitch) for point in bounds_corners(self.context["source_bounds"][name])]
                expected = {"min": [min(point[axis] for point in expected_points) for axis in range(3)],
                            "max": [max(point[axis] for point in expected_points) for axis in range(3)]}
                actual_bounds = self.actor_bounds(actor)
                bounds_error = max(abs(actual - wanted) for side in ("min", "max") for actual, wanted in zip(actual_bounds[side], expected[side]))
                if bounds_error > .002:
                    raise ValueError("Actual component world bounds changed: " + name)
                mesh = component.get_editor_property("static_mesh")
                if mesh != self.meshes[name] or any(component.get_material(index) is None for index in range(len(mesh.get_editor_property("static_materials")))):
                    raise ValueError("Component mesh or material assignment differs")
                visible = bool(component.is_visible())
                if visible != (stone_visible if name == "Stone" else True):
                    raise ValueError("Actual stone/component visibility disagrees with sampled phase")
                components.append({"name": name, "actor": actor.get_path_name(), "mesh": mesh.get_path_name(),
                    "actual_world_translation_cm": coordinates(transform.translation), "actual_world_scale": scale,
                    "actual_origin_xyz_basis_points_cm": actual_points, "max_basis_error_cm": max(errors),
                    "actual_world_bounds_cm": actual_bounds, "max_bounds_error_cm": bounds_error, "actual_visible": visible,
                    "triangles_lod0": mesh.get_num_triangles(0), "sections_lod0": mesh.get_num_sections(0),
                    "actual_materials": [component.get_material(index).get_path_name() for index in range(len(mesh.get_editor_property("static_materials")))]})
            if len(components) != 5 or sum(row["sections_lod0"] for row in components) != 12:
                raise ValueError("Expected five mesh components and twelve sections per slot")
            arm_transform = item["components"]["Arm"][1].get_world_transform()
            release = coordinates(unreal.MathLibrary.transform_location(arm_transform, unreal.Vector(*self.context["anchors"]["release_point"]["translation_cm"])))
            stone_origin = coordinates(item["components"]["Stone"][1].get_world_transform().translation)
            if math.dist(release, stone_origin) > .001:
                raise ValueError("Actual loaded stone origin no longer coincides with actual release point")
            cloth_component = item["components"]["Cloth"][1]
            if not self.shot.get("original_cloth"):
                actual_color = item["mid"].get_vector_parameter_value("Color")
                observed = [float(actual_color.r), float(actual_color.g), float(actual_color.b), float(actual_color.a)]
                if cloth_component.get_material(0) != item["mid"] or max(abs(left - right) for left, right in zip(observed, TEAM_COLORS[self.shot["team"]])) > 1e-6 or abs(item["mid"].get_scalar_parameter_value("Roughness") - .6600000262260437) > 1e-6 or item["mid"].get_scalar_parameter_value("Metallic") != 0:
                    raise ValueError("Actual transient cloth parameters differ from source PBR/runtime color")
            elif cloth_component.get_material(0) != self.meshes["Cloth"].get_material(0):
                raise ValueError("Original cloth control must retain imported native material")
            records.append({"slot": slot, "platform_id": self.context["platforms"][slot]["id"], "pitch": pitch,
                            "actual_arm_pivot_world_cm": coordinates(arm_transform.translation), "actual_release_point_world_cm": release,
                            "actual_stone_origin_world_cm": stone_origin, "components": components,
                            "actual_component_count": len(components), "actual_section_count": 12})
        return {"team": self.shot["team"], "yaw": self.yaw, "base_actor_world_bounds_cm": self.actor_bounds(self.base_actor),
                "base_translation_cm": coordinates(base_transform.translation), "base_scale": coordinates(base_transform.scale3d),
                "slots": records, "actual_texture_residency": self.residency, "no_runtime_timing_claim": True}

    def position_camera(self, audit):
        selected = audit["slots"][self.shot["slot"]]
        crop = self.shot["crop"]
        if crop == "wide":
            bounds = union_bounds([audit["base_actor_world_bounds_cm"]] + [component["actual_world_bounds_cm"] for slot in audit["slots"] for component in slot["components"]])
            direction = (1.2, -1.5, .85)
        elif crop in {"fit", "mechanism"}:
            bounds = union_bounds([row["actual_world_bounds_cm"] for row in selected["components"]])
            direction = ((1.4, 1.4, .85), (1.4, -1.4, .85), (-1.5, -.45, .9))[self.shot["slot"]]
        elif crop == "cup":
            center = selected["actual_release_point_world_cm"]
            bounds = {"min": add(center, (-18, -25, -18)), "max": add(center, (18, 25, 18))}
            direction = (-1.2, 1.8, 1.1)
        else:
            cloth = next(row for row in selected["components"] if row["name"] == "Cloth")["actual_world_bounds_cm"]
            bounds = {"min": add(cloth["min"], (-7, -7, -7)), "max": add(cloth["max"], (7, 7, 7))}
            direction = (1.6, 1.1, .55)
        fitted = fit_camera(bounds, direction)
        location, target = self.unreal.Vector(*fitted["location"]), self.unreal.Vector(*fitted["target"])
        self.camera.set_actor_location(location, False, False)
        self.camera.set_actor_rotation(self.unreal.MathLibrary.find_look_at_rotation(location, target), False)
        self.camera_component.set_field_of_view(fitted["fov"])
        fitted["crop"] = crop
        fitted["closeup_scope"] = "cup/flag crops intentionally frame their connection region, not entire surrounding tower"
        return fitted

    def dispatch_capture(self):
        self.stage = "screenshot_dispatch"
        self.image_path = self.args.output / (self.shot["label"] + ".png")
        attempt = {"label": self.shot["label"], "actual_check": self.actual,
                   "request_frame": self.unreal.SystemLibrary.get_frame_count(),
                   "path": str(self.image_path), "dispatch_delay_seconds": 0,
                   "post_dispatch_timeout_seconds": 20}
        self.report.setdefault("capture_attempts", []).append(attempt)
        self.unreal.log("ROCK_TOWER_CAPTURE_REQUEST " + self.shot["label"] + " frame=" + str(attempt["request_frame"]))
        before = time.monotonic()
        self.task = self.unreal.AutomationLibrary.take_high_res_screenshot(self.args.size, self.args.size, str(self.image_path), self.camera, delay=0.0)
        returned = time.monotonic()
        attempt.update(synchronous_dispatch_seconds=returned - before,
                       return_frame=self.unreal.SystemLibrary.get_frame_count(),
                       task_valid=bool(self.task and self.task.is_valid_task()))
        if not attempt["task_valid"]:
            raise ValueError("Actual viewport screenshot task is unavailable")
        self.phase_started = self.last_poll = self.last_invalidation = returned
        self.stage = "screenshot"
        self.level_editor.editor_invalidate_viewports()
        self.unreal.log("ROCK_TOWER_CAPTURE_QUEUED " + json.dumps({key: value for key, value in attempt.items() if key != "actual_check"}))

    def tick(self, delta_seconds):
        if self.finished or getattr(self, "in_tick", False):
            return
        self.in_tick = True
        try:
            self.advance(delta_seconds)
        finally:
            self.in_tick = False

    def advance(self, delta_seconds):
        try:
            now = time.monotonic()
            if now - self.started > self.args.timeout:
                raise TimeoutError("Bounded RockTower editor review timed out")
            if self.stage == "resources":
                records = parse_texture_dump(self.args.log_file.read_text(encoding="utf-8-sig", errors="replace"), *self.dump, self.required_paths)
                if now - self.resource_started > 20:
                    raise TimeoutError("Original Base textures did not become resident")
                if records is None:
                    return
                if not textures_resident(records, self.required_paths):
                    if self.counter >= 4:
                        raise TimeoutError("Four native dumps did not prove Base3 residency")
                    if now - self.last_request >= .5:
                        self.report.setdefault("residency_attempts", []).append(records)
                        self.dump, self.last_request = self.request_dump(), now
                    return
                self.residency = records
                self.report["verified_residency_markers"] = self.dump
                self.stage = "prepare"
            elif self.stage == "prepare":
                self.prepare()
            elif self.stage == "settle":
                self.tick_count += 1
                if self.tick_count < 8 or now - self.phase_started < .6:
                    return
                self.actual = self.audit_components()
                self.actual["camera"] = self.position_camera(self.actual)
                self.phase_started, self.stage = now, "camera_settle"
            elif self.stage == "camera_settle":
                if now - self.phase_started < .4:
                    return
                self.dispatch_capture()
            elif self.stage == "screenshot":
                task_done, file_exists = bool(self.task.is_task_done()), self.image_path.is_file()
                if not task_done or not file_exists:
                    if now - self.last_poll >= 2:
                        observation = {"elapsed_after_dispatch_seconds": now - self.phase_started,
                                       "frame": self.unreal.SystemLibrary.get_frame_count(),
                                       "task_valid": bool(self.task.is_valid_task()), "task_done": task_done, "file_exists": file_exists}
                        self.report["capture_attempts"][-1].setdefault("observations", []).append(observation)
                        self.unreal.log("ROCK_TOWER_CAPTURE_PENDING " + json.dumps(observation))
                        self.last_poll = now
                    if now - self.phase_started > 20:
                        raise TimeoutError("Actual screenshot task did not complete within20seconds after dispatch returned")
                    if now - self.last_invalidation >= .5:
                        self.level_editor.editor_invalidate_viewports()
                        self.last_invalidation = now
                    return
                validate_png(self.image_path, self.args.size)
                self.report["capture_attempts"][-1].update(completed=True, complete_frame=self.unreal.SystemLibrary.get_frame_count(),
                                                          elapsed_after_dispatch_seconds=now - self.phase_started)
                self.report["images"].append({"shot": self.shot, **rock.file_record(self.image_path), "actual_check": self.actual})
                self.index += 1
                if self.index == len(SHOTS):
                    self.finish("actual12images_captured_pending_root_visual_review")
                else:
                    self.stage = "prepare"
        except Exception as error:
            self.report["error"] = str(error)
            self.finish("failed")

    def finish(self, status):
        global SESSION
        if self.finished:
            return
        self.finished, self.stage = True, "finished"
        if self.handle is not None:
            self.unreal.unregister_slate_post_tick_callback(self.handle)
            self.handle = None
        try:
            rock.check_records(self.context["dependencies"])
            self.report["all_frozen_packages_sources_and_tools_unchanged"] = True
        except Exception as error:
            self.report["preservation_error"], status = str(error), "failed"
        self.report.update(status=status, actual_images=len(self.report["images"]), elapsed_seconds=time.monotonic() - self.started)
        try:
            rock.write_new(self.args.output / "ue_render_report.json", self.report)
        finally:
            self.unreal.EditorPythonScripting.set_keep_python_script_alive(False)
            SESSION = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh-report", type=Path, default=os.environ.get("CIVWAR_ROCK_TOWER_RENDER_FRESH", str(rock.DELIVERY / "ue_fresh_01.json")))
    parser.add_argument("--output", type=Path, default=os.environ.get("CIVWAR_ROCK_TOWER_RENDER_OUTPUT", str(rock.BASE / "ue_render_01")))
    parser.add_argument("--log-file", type=Path, default=os.environ.get("CIVWAR_ROCK_TOWER_RENDER_LOG"))
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=160)
    parser.add_argument("--dry-run", action="store_true")
    args, _ = parser.parse_known_args()
    if args.output.exists() or not args.output.resolve().is_relative_to(rock.BASE.resolve()) or not 256 <= args.size <= 768 or not 30 <= args.timeout <= 180:
        raise ValueError("Fresh owned output directory, 256..768 size and bounded30..180s timeout required")
    context = input_context(args.fresh_report)
    if args.dry_run:
        print(json.dumps({"status": "inputs_only_no_ue", "planned_images": len(SHOTS), "shots": SHOTS, "meshes": context["rock"]["meshes"], "base_mesh": context["base_mesh"], "actual_images": 0, "production_approved": False}))
        return
    args.output.mkdir(parents=True)
    import unreal
    global SESSION
    SESSION = RockReview(unreal, args, context)
    try:
        SESSION.setup()
    except Exception as error:
        SESSION.report["error"] = str(error)
        SESSION.finish("failed_before_capture")
        raise


if __name__ == "__main__":
    main()
