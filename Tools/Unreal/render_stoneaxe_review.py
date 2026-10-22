from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import time


VERSION = "stoneaxe_actual_ue_world_rotation_skin_review_v5"
SHOTS = [
    ("idle", "Idle", 0.0, 0, "body"),
    ("idle_reverse", "Idle", 0.0, 180, "body"),
    ("move_0", "Move", 0.0, 0, "body"),
    ("move_15", "Move", .15, 0, "body"),
    ("move_30", "Move", .30, 0, "body"),
    ("windup", "Attack", 13 / 60, 0, "body"),
    ("contact", "Attack", .35, 0, "body"),
    ("recovery", "Attack", .45, 0, "body"),
    ("contact_reverse", "Attack", .35, 180, "body"),
    ("hit", "Hit", .15, 0, "body"),
    ("death", "Death", 1.2, 0, "body"),
    ("death_reverse", "Death", 1.2, 180, "body"),
    ("grip_idle", "Idle", 0.0, 0, "hand"),
    ("grip_contact", "Attack", .35, 0, "hand"),
    ("grip_contact_reverse", "Attack", .35, 180, "hand"),
]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_inputs(args):
    imported = read(args.import_report)
    fitted = read(args.socket_report)
    disk = imported.get("result", {}).get("disk_dependency_validation", {})
    if imported.get("status") != "isolated_import_fresh_reopen_structural_review_only" or imported.get("dry_run") or not imported["result"].get("structural_checks_passed"):
        raise ValueError("Actual successful fresh UE reopen report is mandatory")
    if disk.get("status") != "passed" or disk.get("validated_in_fresh_process") is not True or disk.get("initial_process_id") == disk.get("validation_process_id"):
        raise ValueError("Initial in-memory import is not durable asset approval")
    absolute = imported["result"].get("absolute_motion_validation", {})
    if absolute.get("status") != "passed" or absolute.get("frames") != 323 or not absolute.get("reference_and_each_clip_checked"):
        raise ValueError("Reference and all323 actual UE animation frames must pass absolute physical bone/scale checks")
    precision = imported["result"].get("skin_weight_precision", {})
    if not precision.get("use_high_precision_skin_weights") or not precision.get("verified_after_fresh_reopen"):
        raise ValueError("LOD0 high-precision skin weights must be verified from actual fresh asset settings")
    if not fitted.get("numeric_socket_pass") or fitted.get("status") != "numeric_socket_pass_pending_actual_assembly_render_grip_review":
        raise ValueError("Actual applied and saved socket calibration must pass before assembly rendering")
    if Path(fitted["import_report"]).resolve() != args.import_report.resolve():
        raise ValueError("Socket calibration and actual UE import report differ")
    body = imported["result"]["body"]
    weapon = imported["result"]["weapon"]["path"]
    if fitted["result"]["body"] != body or fitted["result"]["weapon"] != weapon:
        raise ValueError("Socket calibration targets different actual assets")
    body_record = fitted["result"].get("body_package_record", {})
    if body_record.get("asset_path") != body or body_record.get("class_name") != "SkeletalMesh":
        raise ValueError("Post-socket-save actual body package evidence is mandatory")
    for original in disk.get("files", []):
        record = body_record if original["asset_path"] == body else original
        package = Path(record["package_file"])
        if not package.is_file() or sha(package) != record["sha256"]:
            raise ValueError("Actual persisted assembly dependency changed: " + str(package))
    manifest = read(imported["manifest"])
    calibration = manifest["weapon"]["calibration"]
    if sha(calibration["path"]) != calibration["sha256"]:
        raise ValueError("Actual exported calibration file changed")
    motion = manifest["physical_motion_reference"]
    if sha(motion["path"]) != motion["sha256"]:
        raise ValueError("Actual physical skin reference file changed")
    return imported, fitted, read(calibration["path"])


def coordinates(value):
    return [float(value.x), float(value.y), float(value.z)]


def distance(first, second):
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(coordinates(first), coordinates(second))))


def rotation_distance(first, second):
    dot = first.x * second.x + first.y * second.y + first.z * second.z + first.w * second.w
    return math.degrees(2 * math.acos(min(1.0, abs(dot))))


class ReviewSession:
    def __init__(self, unreal, args, imported, fitted, calibration):
        self.unreal = unreal
        self.args = args
        self.imported = imported
        self.fitted = fitted
        self.calibration = calibration
        manifest = read(imported["manifest"])
        self.motion_record = manifest["physical_motion_reference"]
        self.motion = read(self.motion_record["path"])
        self.skin_correspondence = None
        self.started = time.monotonic()
        self.shots = [shot for shot in SHOTS if not args.labels or shot[0] in set(args.labels.split(","))]
        if not self.shots:
            raise ValueError("No requested shot labels")
        self.index = 0
        self.stage = "prepare"
        self.task = None
        self.handle = None
        self.report = {"version": VERSION, "status": "running_actual_ue_assembly_review", "created_at": datetime.now(timezone.utc).isoformat(),
                       "import_report": str(args.import_report), "socket_report": str(args.socket_report), "process_id": os.getpid(),
                       "source": "actual persisted UE SkeletalMesh and single-clip AnimSequences with independent StaticMesh attached to fitted mesh-owned socket",
                       "images": [], "visual_approved": False, "runtime_approved": False, "production_approved": False,
                       "physical_skin_source": self.motion_record,
                       "pose_refresh": "Public OverrideAnimationData invokes native TickAnimation(0,false) then RefreshBoneTransforms; do not rely on stopped editor viewport animation ticks",
                       "limits": ["Editor assembly capture, not live server/client game-camera acceptance", "15 discrete views do not replace complete continuous motion or performance tests"]}
        self.setup()

    def setup(self):
        unreal = self.unreal
        if "nullrhi" in unreal.SystemLibrary.get_command_line().lower():
            raise ValueError("Real renders require RHI; NullRHI is forbidden")
        if not hasattr(unreal, "GeometryScript_SceneUtils"):
            raise RuntimeError("This process must enable GeometryScripting for actual component CPU-skinned vertices; no bone-only substitute")
        self.dynamic_mesh = unreal.DynamicMesh()
        self.copy_options = unreal.GeometryScriptCopyMeshFromComponentOptions()
        self.copy_options.set_editor_property("want_normals", False)
        self.copy_options.set_editor_property("want_tangents", False)
        lod = unreal.GeometryScriptMeshReadLOD()
        lod.set_editor_property("lod_type", unreal.GeometryScriptLODType.RENDER_DATA)
        lod.set_editor_property("lod_index", 0)
        self.copy_options.set_editor_property("requested_lod", lod)
        self.world = unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
        if self.world is None:
            raise RuntimeError("Could not create an unsaved temporary editor map")
        editor = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        self.level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        self.level_editor.editor_set_game_view(True)
        for command in ("t.MaxFPS 15", "r.VSync 0", "r.ScreenPercentage 100", "r.DynamicGlobalIlluminationMethod 0", "r.ReflectionMethod 0", "r.Shadow.Virtual.Enable 0", "r.EyeAdaptationQuality 0"):
            unreal.SystemLibrary.execute_console_command(self.world, command)
        self.body_asset = unreal.EditorAssetLibrary.load_asset(self.imported["result"]["body"])
        self.weapon_asset = unreal.EditorAssetLibrary.load_asset(self.imported["result"]["weapon"]["path"])
        if not isinstance(self.body_asset, unreal.SkeletalMesh) or not isinstance(self.weapon_asset, unreal.StaticMesh):
            raise TypeError("Actual persisted body or weapon failed to load")
        self.clips = {record["clip"]: unreal.EditorAssetLibrary.load_asset(record["path"]) for record in self.imported["result"]["clips"]}
        self.actor = editor.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(0, 0, 0))
        self.body = self.actor.get_component_by_class(unreal.SkeletalMeshComponent)
        self.body.set_skeletal_mesh_asset(self.body_asset)
        self.body.set_mobility(unreal.ComponentMobility.MOVABLE)
        self.body.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
        self.body.set_editor_property("visibility_based_anim_tick_option", unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES)
        self.body.set_update_animation_in_editor(True)
        self.body.set_component_tick_enabled(True)
        socket = self.fitted["result"]["socket_name"]
        if socket != "weapon_r" or not self.body.does_socket_exist(socket):
            raise ValueError("Actual saved weapon_r socket missing; do not fabricate an attachment")
        self.weapon_actor = editor.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0))
        self.weapon = self.weapon_actor.get_component_by_class(unreal.StaticMeshComponent)
        self.weapon.set_mobility(unreal.ComponentMobility.MOVABLE)
        self.weapon.set_static_mesh(self.weapon_asset)
        snap = unreal.AttachmentRule.SNAP_TO_TARGET
        if not self.weapon.attach_to_component(self.body, socket, snap, snap, snap, False):
            raise RuntimeError("Actual independent weapon attachment failed")
        ground = editor.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, -.3))
        ground.get_component_by_class(unreal.StaticMeshComponent).set_static_mesh(unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Plane"))
        ground.set_actor_scale3d(unreal.Vector(12, 12, 1))
        for rotation, intensity in ((unreal.Rotator(pitch=-45, yaw=-35, roll=0), 4.0), (unreal.Rotator(pitch=-30, yaw=140, roll=0), 1.5)):
            light = editor.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 400), rotation)
            light.get_component_by_class(unreal.DirectionalLightComponent).set_intensity(intensity)
        fill = editor.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(240, 330, 200), unreal.Rotator(pitch=-18, yaw=-125, roll=0))
        fill_component = fill.get_component_by_class(unreal.DirectionalLightComponent)
        fill_component.set_intensity(2.0)
        fill_component.set_cast_shadows(False)
        self.report["review_lighting"] = {"original_key_lux": 4.0, "original_secondary_lux": 1.5, "additional_camera_side_fill_lux": 2.0,
                                           "additional_fill_cast_shadows": False, "material_or_exposure_modified_for_fill": False}
        self.camera = editor.spawn_actor_from_class(unreal.CameraActor, unreal.Vector(240, 340, 190))
        self.camera_component = self.camera.get_component_by_class(unreal.CameraComponent)
        self.camera_component.set_field_of_view(38)
        self.camera_component.set_editor_property("constrain_aspect_ratio", False)
        self.options = unreal.AnimPoseEvaluationOptions()
        self.options.set_editor_property("evaluation_type", unreal.AnimDataEvalType.RAW)
        self.options.set_editor_property("should_retarget", False)
        self.options.set_editor_property("extract_root_motion", False)
        self.options.set_editor_property("optional_skeletal_mesh", self.body_asset)
        unreal.EditorPythonScripting.set_keep_python_script_alive(True)
        self.handle = unreal.register_slate_post_tick_callback(self.tick)

    def prepare(self):
        unreal = self.unreal
        self.current = self.shots[self.index]
        label, clip, position, yaw, crop = self.current
        self.actor.set_actor_rotation(unreal.Rotator(pitch=0, yaw=yaw, roll=0), False)
        self.body.set_animation(self.clips[clip])
        self.body.stop()
        self.body.set_play_rate(0)
        self.body.set_position(position, False)
        self.body.override_animation_data(self.clips[clip], False, False, position, 0.0)
        self.expected = unreal.AnimPoseExtensions.get_anim_pose_at_time(self.clips[clip], position, self.options)
        if not unreal.AnimPoseExtensions.is_valid(self.expected):
            raise RuntimeError("Cannot evaluate real imported sequence for shot " + label)
        self.phase_started = time.monotonic()
        self.tick_count = 0
        self.stage = "settle"

    def pose_check(self):
        unreal = self.unreal
        errors = {}
        rotation_errors = {}
        for name in self.motion["reference"]:
            actual = self.body.get_socket_transform(name, unreal.RelativeTransformSpace.RTS_COMPONENT)
            expected = unreal.AnimPoseExtensions.get_bone_pose(self.expected, name, unreal.AnimPoseSpaces.WORLD)
            errors[name] = distance(actual.translation, expected.translation)
            rotation_errors[name] = rotation_distance(actual.rotation, expected.rotation)
        actual_socket = self.body.get_socket_transform("weapon_r", unreal.RelativeTransformSpace.RTS_WORLD)
        actual_weapon = self.weapon.get_world_transform()
        world_up = self.actor.get_actor_up_vector()
        world_forward = self.actor.get_actor_forward_vector()
        yaw_radians = math.radians(self.current[3])
        expected_forward = unreal.Vector(math.cos(yaw_radians), math.sin(yaw_radians), 0)
        marker_errors = {}
        pose_label = next((label for label, record in self.calibration["poses"].items() if record["clip"] == self.current[1] and abs(record["time_seconds"] - self.current[2]) < 1e-6), None)
        if pose_label:
            for name, marker in self.calibration["markers"].items():
                local = marker["local_position_m"]
                expected = self.calibration["poses"][pose_label]["world_positions_m"][name]
                actual_point = unreal.MathLibrary.transform_location(actual_weapon, unreal.Vector(local[0] * 100, -local[1] * 100, local[2] * 100))
                expected_point = unreal.MathLibrary.transform_location(self.body.get_world_transform(), unreal.Vector(expected[0] * 100, -expected[1] * 100, expected[2] * 100))
                marker_errors[name] = distance(actual_point, expected_point)
        return {"bone_position_errors_cm": errors, "maximum_bone_error_cm": max(errors.values()),
                "actual_actor_world_up": coordinates(world_up), "actual_actor_world_forward": coordinates(world_forward),
                "world_up_vector_error": distance(world_up, unreal.Vector(0, 0, 1)), "world_forward_vector_error": distance(world_forward, expected_forward),
                "bone_rotation_errors_deg": rotation_errors, "maximum_bone_rotation_error_deg": max(rotation_errors.values()),
                "weapon_to_socket_position_error_cm": distance(actual_socket.translation, actual_weapon.translation),
                "weapon_to_socket_rotation_error_deg": rotation_distance(actual_socket.rotation, actual_weapon.rotation),
                "actual_attached_marker_errors_cm": marker_errors,
                "actual_weapon_world_scale": coordinates(actual_weapon.scale3d),
                "actual_animation_position_seconds": float(self.body.get_position())}

    def skin_check(self):
        unreal = self.unreal
        copied, local_to_world, outcome = unreal.GeometryScript_SceneUtils.copy_mesh_from_component(self.body, self.dynamic_mesh, self.copy_options, False)
        if outcome != unreal.GeometryScriptOutcomePins.SUCCESS or copied is None:
            raise RuntimeError("Actual render-data component skin extraction failed")
        queried, positions, has_gaps = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(copied, False)
        if has_gaps:
            raise RuntimeError("Unexpected render-data vertex ID gaps; cannot preserve correspondence")
        points = [coordinates(point) for point in unreal.GeometryScript_List.convert_vector_list_to_array(positions)]
        if len(points) < 5683:
            raise RuntimeError("Actual component skin extraction returned incomplete LOD0 geometry")
        frame = round(self.current[2] * 60) + 1
        source = next(record for record in self.motion["clips"][self.current[1]] if record["frame"] == frame)
        expected = [[point[0] * 100, -point[1] * 100, point[2] * 100] for point in source["skinned_points_m"]]
        squared = lambda first, second: sum((left - right) ** 2 for left, right in zip(first, second))
        if self.skin_correspondence is None:
            self.skin_correspondence = [min(range(len(points)), key=lambda index: squared(points[index], point)) for point in expected]
            self.skin_vertex_count = len(points)
            self.report["skin_correspondence"] = {"mapping_initial_clip": self.current[1], "mapping_initial_frame": frame,
                                                   "mapping_method": "Nearest actual evaluated vertex at initial reviewed pose, then immutable vertex indices across every subsequent clip and both yaw directions",
                                                   "source_vertex_indices": self.motion["skinned_sample_vertex_indices"],
                                                   "actual_render_data_vertex_indices": self.skin_correspondence, "actual_vertex_count": len(points)}
        if len(points) != self.skin_vertex_count:
            raise RuntimeError("Actual render-data topology changed between animation poses")
        actual = [points[index] for index in self.skin_correspondence]
        errors = [math.sqrt(squared(left, right)) for left, right in zip(actual, expected)]
        world_transform = self.body.get_world_transform()
        world_points = [unreal.MathLibrary.transform_location(world_transform, unreal.Vector(*point)) for point in points]
        world_floor = min(point.z for point in world_points)
        result = {"status": "passed" if max(errors) < .1 and min(point[2] for point in points) > -.05 and world_floor > -.05 else "failed",
                  "source_frame": frame, "actual_lod0_vertices": len(points), "corresponding_sample_count": len(actual),
                  "maximum_corresponding_vertex_error_cm": max(errors), "all_actual_vertex_floor_minimum_cm": min(point[2] for point in points),
                  "all_actual_vertex_world_floor_minimum_cm": world_floor,
                  "limits": {"maximum_vertex_error_cm": .1, "minimum_floor_cm": -.05},
                  "source": "GeometryScript render-data SkinnedMeshComponentToDynamicMesh calls actual GetCPUSkinnedVertices, not source bone math",
                  "actual_sample_points_cm": actual, "sample_errors_cm": errors}
        if result["status"] != "passed":
            self.report["failed_actual_skin_check"] = result
            raise RuntimeError("Actual deformed UE mesh differs from original physical DCC skin points or intersects ground")
        return result

    def position_camera(self):
        unreal = self.unreal
        label, clip, position, yaw, crop = self.current
        if crop == "hand":
            target = self.body.get_socket_transform("hand_r", unreal.RelativeTransformSpace.RTS_WORLD).translation
            offset = unreal.Vector(48, 78, 35)
            self.camera_component.set_field_of_view(38)
        else:
            target = unreal.Vector((-50 if yaw == 0 else 50) if clip == "Death" else 0, 0, 35 if clip == "Death" else 75)
            offset = unreal.Vector(235, 330, 120)
            self.camera_component.set_field_of_view(38)
        location = target + offset
        self.camera.set_actor_location(location, False, False)
        self.camera.set_actor_rotation(unreal.MathLibrary.find_look_at_rotation(location, target), False)

    def tick(self, delta_seconds):
        try:
            if time.monotonic() - self.started > self.args.timeout:
                raise TimeoutError("Actual UE assembly render exceeded bounded time")
            if self.stage == "prepare":
                self.prepare()
                return
            if self.stage == "settle":
                self.tick_count += 1
                if self.tick_count < 8 or time.monotonic() - self.phase_started < .5:
                    return
                self.current_check = self.pose_check()
                if self.current_check["world_up_vector_error"] > 1e-5 or self.current_check["world_forward_vector_error"] > 1e-5:
                    raise RuntimeError("Actual actor world orientation differs from requested pure upright yaw; no component-space-only approval")
                if self.current_check["maximum_bone_error_cm"] > .1 or self.current_check["maximum_bone_rotation_error_deg"] > .5:
                    if time.monotonic() - self.phase_started < 5:
                        return
                    raise RuntimeError("Editor component failed to refresh actual skeletal pose: " + json.dumps(self.current_check))
                if self.current_check["weapon_to_socket_position_error_cm"] > .01 or self.current_check["weapon_to_socket_rotation_error_deg"] > .1 or max(abs(value - 1) for value in self.current_check["actual_weapon_world_scale"]) > .01:
                    raise RuntimeError("Actual weapon socket attachment position or physical scale failed")
                if max(self.current_check["actual_attached_marker_errors_cm"].values(), default=0) > .1:
                    raise RuntimeError("Actual attached geometry markers differ from exported world positions")
                self.current_check["actual_skinned_mesh_validation"] = self.skin_check()
                self.position_camera()
                self.image_path = self.args.output / (self.current[0] + ".png")
                self.task = self.unreal.AutomationLibrary.take_high_res_screenshot(self.args.size, self.args.size, str(self.image_path), self.camera, delay=.2)
                if self.task is None or not self.task.is_valid_task():
                    raise RuntimeError("No actual active editor viewport screenshot task; do not report success")
                self.phase_started = time.monotonic()
                self.stage = "screenshot"
                return
            if self.stage == "screenshot":
                if time.monotonic() - self.phase_started > 20:
                    raise TimeoutError("Viewport screenshot did not complete")
                if not self.task.is_task_done() or not self.image_path.is_file():
                    return
                data = self.image_path.read_bytes()
                if len(data) < 1000 or data[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", data[16:24]) != (self.args.size, self.args.size):
                    raise RuntimeError("Actual screenshot file format or dimensions are invalid")
                label, clip, position, yaw, crop = self.current
                self.report["images"].append({"label": label, "clip": clip, "time_seconds": position, "yaw_degrees": yaw, "crop": crop,
                                               "path": str(self.image_path), "bytes": len(data), "sha256": sha(self.image_path), "actual_pose_check": self.current_check})
                self.index += 1
                if self.index == len(self.shots):
                    self.finish("actual_ue_images_captured_pending_human_visual_review")
                else:
                    self.stage = "prepare"
        except Exception as error:
            self.report["error"] = str(error)
            if hasattr(self, "current_check"):
                self.report["failed_actual_pose_check"] = self.current_check
            self.finish("failed")

    def finish(self, status):
        global SESSION
        self.report["status"] = status
        self.report["elapsed_seconds"] = time.monotonic() - self.started
        self.report["actual_images"] = len(self.report["images"])
        (self.args.output / "ue_render_report.json").write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if self.handle is not None:
            self.unreal.unregister_slate_post_tick_callback(self.handle)
            self.handle = None
        self.unreal.EditorPythonScripting.set_keep_python_script_alive(False)
        self.task = None
        SESSION = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--import-report", type=Path, default=os.environ.get("CIVWAR_STONEAXE_RENDER_IMPORT_REPORT"))
    parser.add_argument("--socket-report", type=Path, default=os.environ.get("CIVWAR_STONEAXE_RENDER_SOCKET_REPORT"))
    parser.add_argument("--output", type=Path, default=os.environ.get("CIVWAR_STONEAXE_RENDER_OUTPUT"))
    parser.add_argument("--labels", default=os.environ.get("CIVWAR_STONEAXE_RENDER_LABELS", ""))
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--dry-run", action="store_true")
    args, unknown = parser.parse_known_args()
    if not args.import_report or not args.socket_report or not args.output:
        raise ValueError("Explicit actual fresh import report, applied socket report and new output directory required")
    args.import_report = args.import_report.resolve()
    args.socket_report = args.socket_report.resolve()
    args.output = args.output.resolve()
    if args.size > 768 or args.size < 256:
        raise ValueError("Review capture size must stay within 256..768 pixels")
    imported, fitted, calibration = validate_inputs(args)
    if args.dry_run:
        count = sum(1 for shot in SHOTS if not args.labels or shot[0] in set(args.labels.split(",")))
        print(json.dumps({"status": "input_validation_only_no_ue_render", "shots": count, "output": str(args.output)}, ensure_ascii=False))
        return
    if (args.output / "ue_render_report.json").exists() or any(args.output.glob("*.png")):
        raise FileExistsError("Use a new output directory; do not replace previous actual captures")
    args.output.mkdir(parents=True, exist_ok=True)
    import unreal
    global SESSION
    try:
        SESSION = ReviewSession(unreal, args, imported, fitted, calibration)
    except Exception as error:
        (args.output / "ue_render_report.json").write_text(json.dumps({"version": VERSION, "status": "failed_before_capture", "error": str(error), "actual_images": 0,
                                                                       "runtime_approved": False, "production_approved": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        unreal.EditorPythonScripting.set_keep_python_script_alive(False)
        raise


if __name__ == "__main__":
    main()
