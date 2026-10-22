from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import struct
import sys
import time


sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_team_ue as team
from render_stoneaxe_teamcolor import parse_texture_dump, textures_resident

VERSION = "base_stone_actual_ue_native_pbr_team_controls_v3"
SHOTS = [(mode + "_" + crop, mode, crop) for crop in ("wide", "flag") for mode in ("original", "disabled", "blue", "red")]
CAMERAS = {"wide": {"target": [0, 0, 150], "offset": [1050, -850, 600], "fov": 38},
           "flag": {"target": [206, -198, 45], "offset": [300, -80, 50], "fov": 24}}
SESSION = None


def check_team_report(path):
    report = team.read(path)
    if report.get("status") != "base_team_material_fresh_reopen_passed_pending_actual_render" or report.get("dry_run"):
        raise ValueError("Actual successful fresh material reopen required before screenshots")
    result = report["result"]
    if not result.get("validated_in_fresh_process") or result["initial_process_id"] == result["validation_process_id"]:
        raise ValueError("First-save process is not actual fresh reopen")
    if not result.get("frozen26_unchanged") or result["audit"].get("status") != "passed" or len(result["files"]) != 4:
        raise ValueError("Fresh graph and complete4asset preservation evidence required")
    current = team.source_inputs()
    for key in ("destination", "settings", "sources", "frozen_packages", "source_evidence"):
        if report[key] != current[key]:
            raise ValueError("Fresh material context no longer matches exact approved sources: " + key)
    team.check_records(result["files"] + report["frozen_packages"] + report["source_evidence"])
    return report


def validate_png(path, size):
    data = Path(path).read_bytes()
    if len(data) < 1000 or data[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", data[16:24]) != (size, size):
        raise ValueError("Actual screenshot format or dimensions are invalid")


class BaseReview:
    def __init__(self, unreal, args, context):
        self.unreal, self.args, self.context = unreal, args, context
        self.started = time.monotonic()
        self.handle = None
        self.index = 0
        self.counter = 0
        self.stage = "prepare"
        self.finished = False
        self.report = {"version": VERSION, "status": "running", "execution_process_id": os.getpid(),
                       "created_at": datetime.now(timezone.utc).isoformat(), "team_report": team.file_record(args.team_report),
                       "tool": team.file_record(__file__), "images": [], "component_override_only": True,
                       "frozen_packages": 26, "all_cloth_coverage_approved": False, "visual_approved": False,
                       "runtime_approved": False, "production_approved": False,
                       "limitations": ["Controlled editor captures, not live game-camera or both-team rotation acceptance.",
                                       "Only714 main cloth triangles; clusters2/5/6/8 remain unchanged.",
                                       "One frontal-oblique wide and front-flag closeup; rear cloth and far-view aliasing still need follow-up.",
                                       "safe1 retains608 original-blue edge pixels; inspect for rims without relaxing UV protection."]}

    def setup(self):
        unreal = self.unreal
        command = unreal.SystemLibrary.get_command_line().lower()
        if "nullrhi" in command or "forcelogflush" not in command:
            raise ValueError("Actual RHI and -FORCELOGFLUSH required")
        if not self.args.log_file or not self.args.log_file.is_file():
            raise ValueError("Explicit actual current UE log required for native residency proof")
        self.world = unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
        if not self.world:
            raise RuntimeError("Cannot create unsaved isolated review map")
        editor = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_set_game_view(True)
        for command in ("t.MaxFPS 15", "r.VSync 0", "r.ScreenPercentage 100", "r.DynamicGlobalIlluminationMethod 0",
                        "r.ReflectionMethod 0", "r.Shadow.Virtual.Enable 0", "r.EyeAdaptationQuality 0"):
            unreal.SystemLibrary.execute_console_command(self.world, command)
        self.asset = unreal.EditorAssetLibrary.load_asset(self.context["mesh"])
        self.original = unreal.EditorAssetLibrary.load_asset(self.context["original_material"])
        self.material = unreal.EditorAssetLibrary.load_asset(self.context["result"]["material"])
        if not isinstance(self.asset, unreal.StaticMesh) or not isinstance(self.material, unreal.Material):
            raise ValueError("Frozen base or persisted derived material failed to load")
        self.actor = editor.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0))
        self.component = self.actor.get_component_by_class(unreal.StaticMeshComponent)
        self.component.set_mobility(unreal.ComponentMobility.MOVABLE)
        self.component.set_static_mesh(self.asset)
        self.actor.set_actor_scale3d(unreal.Vector(1, 1, 1))
        self.actor.set_actor_rotation(unreal.Rotator(pitch=0, yaw=0, roll=0), False)
        self.mid = self.component.create_dynamic_material_instance(0, self.material, "BaseStoneTeamControlledReview")
        if not isinstance(self.mid, unreal.MaterialInstanceDynamic):
            raise RuntimeError("Could not create transient component-only MID")
        self.component.set_material(0, self.original)
        ground = editor.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, -.3))
        ground.get_component_by_class(unreal.StaticMeshComponent).set_static_mesh(unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Plane"))
        ground.set_actor_scale3d(unreal.Vector(28, 28, 1))
        for pitch, yaw, intensity, shadow in ((-45, -35, 4.0, True), (-30, 140, 1.5, True), (-18, 125, 2.0, False)):
            light = editor.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 600), unreal.Rotator(pitch=pitch, yaw=yaw, roll=0))
            component = light.get_component_by_class(unreal.DirectionalLightComponent)
            component.set_intensity(intensity)
            component.set_cast_shadows(shadow)
        self.camera = editor.spawn_actor_from_class(unreal.CameraActor, unreal.Vector(1000, -850, 600))
        self.camera_component = self.camera.get_component_by_class(unreal.CameraComponent)
        self.camera_component.set_editor_property("constrain_aspect_ratio", False)
        mask = unreal.EditorAssetLibrary.load_asset(self.context["result"]["mask"])
        instances = {name: unreal.EditorAssetLibrary.load_asset(path) for name, path in self.context["result"]["instances"].items()}
        self.required_paths = set(self.context["original_textures"] + [self.context["result"]["mask"]])
        if len(self.required_paths) != 4:
            raise ValueError("Exactly original3PBR and new1mask textures required")
        self.initial_dump = self.request_dump("initial")
        self.report["mask_dimensions_before_compilation_flush"] = [mask.blueprint_get_size_x(), mask.blueprint_get_size_y()]
        unreal.SystemLibrary.execute_console_command(self.world, "Editor.AsyncAssetCompilationFinishAll")
        self.report["mask_dimensions_after_compilation_flush"] = [mask.blueprint_get_size_x(), mask.blueprint_get_size_y()]
        self.report["actual_material_audit_before_capture"] = team.audit(unreal, self.context, mask, self.material, instances)
        for path in self.required_paths:
            unreal.EditorAssetLibrary.load_asset(path).set_force_mip_levels_to_be_resident(180.0, 0)
        self.component.prestream_textures(180.0, True, 0)
        self.report["resource_preparation"] = {"compile_flush": "Editor.AsyncAssetCompilationFinishAll", "required2048textures": sorted(self.required_paths),
                                               "stream_request_seconds": 180, "source_texture_settings_modified": False,
                                               "readiness_gate": "actual ListTextures -CSV maximum and resident dimensions, not source-size inference"}
        unreal.EditorPythonScripting.set_keep_python_script_alive(True)
        self.handle = unreal.register_slate_post_tick_callback(self.tick)

    def request_dump(self, label):
        if self.finished:
            raise RuntimeError("Terminal review cannot queue more console commands")
        self.counter += 1
        token = f"BASE_TEAM_RESIDENCY_{os.getpid()}_{self.counter}_{label}"
        self.unreal.log(token + "_BEGIN")
        self.unreal.SystemLibrary.execute_console_command(self.world, "ListTextures -CSV")
        self.unreal.log(token + "_END")
        return token + "_BEGIN", token + "_END"

    def read_dump(self, markers):
        return parse_texture_dump(self.args.log_file.read_text(encoding="utf-8-sig", errors="replace"), *markers, self.required_paths)

    def prepare(self):
        unreal = self.unreal
        self.label, self.mode, self.crop = SHOTS[self.index]
        self.current_team = "Red" if self.mode == "red" else "Blue"
        self.strength = 0.0 if self.mode == "disabled" else 1.0
        if self.mode == "original":
            self.component.set_material(0, self.original)
        else:
            self.mid.set_vector_parameter_value("TeamColor", team.shared.color(unreal, team.shared.TEAM_COLORS[self.current_team]))
            self.mid.set_scalar_parameter_value("TeamColorStrength", self.strength)
            self.component.set_material(0, self.mid)
        definition = CAMERAS[self.crop]
        target, offset = unreal.Vector(*definition["target"]), unreal.Vector(*definition["offset"])
        location = target + offset
        self.camera.set_actor_location(location, False, False)
        self.camera.set_actor_rotation(unreal.MathLibrary.find_look_at_rotation(location, target), False)
        self.camera_component.set_field_of_view(definition["fov"])
        self.phase_started = self.last_request = time.monotonic()
        self.current_dump = self.request_dump(self.label)
        self.current_dump_attempts = 1
        self.stage = "resources"

    def check_component(self):
        result = {"mode": self.mode, "actual_material": self.component.get_material(0).get_path_name(), "camera": CAMERAS[self.crop],
                  "actual_texture_residency": self.current_residency, "source_ground_min_z_cm": -31, "actor_translation_z_cm": self.actor.get_actor_location().z}
        scale = self.actor.get_actor_scale3d()
        if any(abs(value - 1) > 1e-6 for value in (scale.x, scale.y, scale.z)) or self.actor.get_actor_location().z != 0:
            raise ValueError("Frozen normalization changed: no re-bottom-align, scale or extra minus31")
        if self.mode == "original":
            if self.component.get_material(0) != self.original:
                raise ValueError("Original control assignment differs")
        else:
            if self.component.get_material(0) != self.mid or self.mid.get_editor_property("parent") != self.material:
                raise ValueError("Actual component MID or parent differs")
            strength = float(self.mid.get_scalar_parameter_value("TeamColorStrength"))
            color = team.shared.values(self.mid.get_vector_parameter_value("TeamColor"))
            if strength != self.strength or max(abs(value - expected) for value, expected in zip(color, team.shared.TEAM_COLORS[self.current_team])) > 1e-6:
                raise ValueError("Actual MID parameters differ")
            result.update(TeamColor=color, TeamColorStrength=strength)
        return result

    def tick(self, delta_seconds):
        if self.finished:
            return
        try:
            now = time.monotonic()
            if now - self.started > self.args.timeout:
                raise TimeoutError("Bounded actual UE review timed out")
            if self.stage == "prepare":
                self.prepare()
            elif self.stage == "resources":
                if now - self.phase_started > 20:
                    raise TimeoutError("Native residency did not reach4actual2048textures")
                records = self.read_dump(self.current_dump)
                if records is None:
                    return
                if not textures_resident(records, self.required_paths):
                    if self.current_dump_attempts >= 4:
                        raise TimeoutError("Four completed native dumps did not prove4resident2048textures")
                    if now - self.last_request >= .5:
                        self.report.setdefault("residency_observations", []).append({"label": self.label, "markers": self.current_dump, "textures": records})
                        self.current_dump, self.last_request = self.request_dump(self.label), now
                        self.current_dump_attempts += 1
                    return
                if now - self.phase_started < 1.0:
                    return
                self.current_residency = records
                self.report["initial_residency_before_force"] = self.read_dump(self.initial_dump)
                self.report.setdefault("verified_residency_markers", []).append({"label": self.label, "markers": self.current_dump, "attempts": self.current_dump_attempts})
                self.phase_started, self.tick_count, self.stage = now, 0, "settle"
            elif self.stage == "settle":
                self.tick_count += 1
                if self.tick_count < 8 or now - self.phase_started < .5:
                    return
                self.current_check = self.check_component()
                self.image_path = self.args.output / (self.label + ".png")
                self.task = self.unreal.AutomationLibrary.take_high_res_screenshot(self.args.size, self.args.size, str(self.image_path), self.camera, delay=.2)
                if self.task is None or not self.task.is_valid_task():
                    raise RuntimeError("Actual viewport screenshot task unavailable")
                self.phase_started, self.stage = now, "screenshot"
            elif self.stage == "screenshot":
                if now - self.phase_started > 20:
                    raise TimeoutError("Actual screenshot did not complete")
                if not self.task.is_task_done() or not self.image_path.is_file():
                    return
                validate_png(self.image_path, self.args.size)
                self.report["images"].append({"label": self.label, **team.file_record(self.image_path), "actual_check": self.current_check})
                self.index += 1
                if self.index == len(SHOTS):
                    self.finish("actual8images_captured_pending_visual_and_pixel_control_review")
                else:
                    self.stage = "prepare"
        except Exception as error:
            self.report["error"] = str(error)
            self.finish("failed")

    def finish(self, status):
        global SESSION
        if self.finished:
            return
        self.finished = True
        self.stage = "finished"
        if self.handle is not None:
            self.unreal.unregister_slate_post_tick_callback(self.handle)
            self.handle = None
        try:
            team.check_records(self.context["frozen_packages"] + self.context["source_evidence"] + self.context["result"]["files"])
            self.report["source_base5_stoneaxe21_derived4_unchanged"] = True
        except Exception as error:
            self.report["preservation_error"], status = str(error), "failed"
        self.report.update(status=status, actual_images=len(self.report["images"]), elapsed_seconds=time.monotonic() - self.started)
        (self.args.output / "ue_render_report.json").write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.unreal.EditorPythonScripting.set_keep_python_script_alive(False)
        SESSION = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--team-report", type=Path, default=os.environ.get("CIVWAR_BASE_TEAM_RENDER_REPORT"))
    parser.add_argument("--output", type=Path, default=os.environ.get("CIVWAR_BASE_TEAM_RENDER_OUTPUT"))
    parser.add_argument("--log-file", type=Path, default=os.environ.get("CIVWAR_BASE_TEAM_RENDER_LOG"))
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=150)
    parser.add_argument("--dry-run", action="store_true")
    args, unknown = parser.parse_known_args()
    if not args.team_report or not args.output or args.output.exists() or not 256 <= args.size <= 768:
        raise ValueError("Explicit fresh report, new output and256..768image size required")
    context = check_team_report(args.team_report)
    if args.dry_run:
        print(json.dumps({"status": "inputs_only_no_ue", "actual_images": 0, "planned_images": len(SHOTS), "cameras": CAMERAS}))
        return
    args.output.mkdir(parents=True)
    import unreal
    global SESSION
    SESSION = BaseReview(unreal, args, context)
    try:
        SESSION.setup()
    except Exception as error:
        SESSION.report["error"] = str(error)
        SESSION.finish("failed_before_capture")
        raise


if __name__ == "__main__":
    main()
