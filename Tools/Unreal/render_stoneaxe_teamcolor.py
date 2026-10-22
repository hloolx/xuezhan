from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time


sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_stoneaxe_review as review
import import_stoneaxe_teamcolor as team_import


VERSION = "stoneaxe_actual_ue_cloth_resident_control_review_v2"
SHOTS = [
    ("original_front", "Idle", 0.0, 0, "body"),
    ("original_face", "Idle", 0.0, 0, "face"),
    ("disabled_front", "Idle", 0.0, 0, "body"),
    ("disabled_face", "Idle", 0.0, 0, "face"),
    ("original_repeat_front", "Idle", 0.0, 0, "body"),
    ("original_repeat_face", "Idle", 0.0, 0, "face"),
    ("blue_front", "Idle", 0.0, 0, "body"),
    ("blue_reverse", "Idle", 0.0, 180, "body"),
    ("blue_face", "Idle", 0.0, 0, "face"),
    ("blue_far", "Idle", 0.0, 0, "far"),
    ("red_front", "Idle", 0.0, 0, "body"),
    ("red_reverse", "Idle", 0.0, 180, "body"),
    ("red_face", "Idle", 0.0, 0, "face"),
    ("red_far", "Idle", 0.0, 0, "far"),
]


def parse_texture_dump(text, start, end, required_paths):
    if start not in text or end not in text.rsplit(start, 1)[1]:
        return None
    block = text.rsplit(start, 1)[1].split(end, 1)[0]
    records = {}
    pattern = re.compile(r"(\d+),(\d+),(\d+),([^,]*),(\d+),(\d+),(\d+),([^,]+),([^,]+),(/Game/[^,\r\n]+),")
    for match in pattern.finditer(block):
        path = match.group(10).strip()
        if path in required_paths:
            records[path] = {"maximum_allowed_size": [int(match.group(1)), int(match.group(2))],
                             "actual_resident_size": [int(match.group(5)), int(match.group(6))],
                             "format": match.group(8), "native_csv_line": match.group(0)}
    return records


def textures_resident(records, required_paths):
    return records is not None and set(records) == set(required_paths) and all(
        record["maximum_allowed_size"] == [2048, 2048] and record["actual_resident_size"] == [2048, 2048]
        for record in records.values())


def check_team_input(args):
    team = review.read(args.team_report)
    if team.get("status") != "team_material_fresh_reopen_passed_pending_actual_color_review" or team.get("dry_run"):
        raise ValueError("Successful actual fresh derived material reopen is required")
    result = team.get("result", {})
    disk = result.get("disk_dependency_validation", {})
    if disk.get("status") != "passed" or not disk.get("validated_in_fresh_process") or disk.get("initial_process_id") == disk.get("validation_process_id"):
        raise ValueError("Derived material was not persisted and validated in a new UE process")
    if not result.get("frozen_asset_bytes_unchanged") or result.get("frozen_packages_checked") != 17 or result.get("material_audit", {}).get("status") != "passed":
        raise ValueError("Derived material graph or original asset preservation failed")
    for record in team["sources"].values():
        team_import.check_record(record)
    for key in ("import_report", "socket_report"):
        if Path(team["sources"][key]["path"]).resolve() != getattr(args, key):
            raise ValueError("Derived material and assembly source lineage differ")
    records = disk.get("files", [])
    if len(records) != 4:
        raise ValueError("Expected exactly mask, material and two preview instance packages")
    for record in records + team["frozen_packages"]:
        team_import.check_record(record, "package_file")
    if team["settings"]["team_colors_linear"] != team_import.TEAM_COLORS:
        raise ValueError("Actual material pilot and runtime team color values differ")
    return team


class TeamReviewSession(review.ReviewSession):
    def __init__(self, unreal, args, imported, fitted, calibration, team):
        self.team = team
        review.SHOTS = SHOTS
        super().__init__(unreal, args, imported, fitted, calibration)
        self.report.update({"version": VERSION, "team_report": team_import.file_record(args.team_report),
                            "team_material": team["result"]["team_material"], "component_override_only": True,
                            "frozen_packages": 17, "team_colors_linear": team_import.TEAM_COLORS,
                            "views": "Original material versus MID strength0 controls, then both team colors front/back, face and far. Far shot is a controlled review distance, not live game-camera acceptance.",
                            "final_team_colors_approved": False})

    def setup(self):
        if self.args.log_file is None or not self.args.log_file.is_file():
            raise ValueError("Explicit actual current UE log file is required for resident-mip evidence")
        if "forcelogflush" not in self.unreal.SystemLibrary.get_command_line().lower():
            raise ValueError("Use -FORCELOGFLUSH so native residency evidence is available before capture")
        super().setup()
        unreal = self.unreal
        self.original_material = self.body.get_material(0)
        self.team_material = unreal.EditorAssetLibrary.load_asset(self.team["result"]["team_material"])
        if not isinstance(self.team_material, unreal.Material):
            raise TypeError("Derived parent material missing")
        self.mid = self.body.create_dynamic_material_instance(element_index=0, source_material=self.team_material, optional_name="StoneAxeTeamReview")
        if not isinstance(self.mid, unreal.MaterialInstanceDynamic):
            raise RuntimeError("Could not create actual component-only team MID")
        self.body.set_material(0, self.original_material)
        self.report["original_vs_derived_sampler_audit"] = self.audit_samplers()
        paths = [record["texture"] for record in self.imported["result"]["materials"]["channels"].values()]
        paths.append(self.team["result"]["mask"])
        self.required_texture_paths = set(paths)
        self.residency_counter = 0
        self.initial_dump = self.request_texture_dump("initial_before_force")
        self.unreal.SystemLibrary.execute_console_command(self.world, "Editor.AsyncAssetCompilationFinishAll")
        for path in paths:
            texture = unreal.EditorAssetLibrary.load_asset(path)
            texture.set_force_mip_levels_to_be_resident(180.0, 0)
        self.body.prestream_textures(180.0, True, 0)
        self.report["resource_preparation"] = {"asset_and_shader_compilation_flush": "Editor.AsyncAssetCompilationFinishAll",
                                               "force_resident_scope": paths, "seconds": 180,
                                               "native_resident_dimensions_source": "UEngine::HandleListTexturesCommand current size uses GetNumResidentMips, UnrealEngine.cpp:6931",
                                               "log_file": str(self.args.log_file), "persistent_texture_settings_changed": False}

    def audit_samplers(self):
        unreal = self.unreal
        editing = unreal.MaterialEditingLibrary
        original_nodes = list(editing.get_material_expressions(self.original_material))
        derived_nodes = list(editing.get_material_expressions(self.team_material))
        fields = ["const_coordinate", "const_mip_value", "mip_value_mode", "sampler_source", "sampler_type", "automatic_view_mip_bias", "gather_mode"]
        result = {}
        for channel, record in self.imported["result"]["materials"]["channels"].items():
            matched = []
            for nodes in (original_nodes, derived_nodes):
                matches = [node for node in nodes if isinstance(node, unreal.MaterialExpressionTextureSample) and node.get_editor_property("texture").get_path_name() == record["texture"]]
                if len(matches) != 1:
                    raise ValueError("Expected one original/derived texture sample for " + channel)
                node = matches[0]
                inputs = list(editing.get_inputs_for_material_expression(self.original_material if nodes is original_nodes else self.team_material, node))
                if any(source is not None for source in inputs):
                    raise ValueError("Unexpected UV/mip input override in " + channel)
                matched.append({field: str(node.get_editor_property(field)) for field in fields})
            if matched[0] != matched[1]:
                raise ValueError("Original and derived PBR sampler attributes differ: " + channel)
            result[channel] = {"texture": record["texture"], "original": matched[0], "derived": matched[1], "equal": True}
        return result

    def request_texture_dump(self, label):
        self.residency_counter += 1
        token = f"STONEAXE_RESIDENCY_{os.getpid()}_{self.residency_counter}_{label}"
        start, end = token + "_BEGIN", token + "_END"
        self.unreal.log(start)
        self.unreal.SystemLibrary.execute_console_command(self.world, "ListTextures -CSV")
        self.unreal.log(end)
        return start, end

    def read_texture_dump(self, markers):
        return parse_texture_dump(self.args.log_file.read_text(encoding="utf-8-sig", errors="replace"), *markers, self.required_texture_paths)

    def prepare(self):
        super().prepare()
        label = self.current[0]
        self.current_team = "Red" if label.startswith("red_") else "Blue"
        self.current_strength = 0.0 if label.startswith("disabled_") else 1.0
        self.original_mode = label.startswith("original_")
        if self.original_mode:
            self.body.set_material(0, self.original_material)
        else:
            self.mid.set_vector_parameter_value("TeamColor", team_import.color(self.unreal, team_import.TEAM_COLORS[self.current_team]))
            self.mid.set_scalar_parameter_value("TeamColorStrength", self.current_strength)
            self.body.set_material(0, self.mid)
        self.position_camera()
        self.resource_started = time.monotonic()
        self.last_resource_request = self.resource_started
        self.current_dump = self.request_texture_dump(label)
        self.stage = "team_resources"

    def tick(self, delta_seconds):
        if self.stage != "team_resources":
            super().tick(delta_seconds)
            return
        try:
            elapsed = time.monotonic() - self.resource_started
            if elapsed > 8:
                raise TimeoutError("Actual texture residency never reached all five approved2048 dimensions")
            records = self.read_texture_dump(self.current_dump)
            if records is None:
                return
            ready = textures_resident(records, self.required_texture_paths)
            if not ready:
                if time.monotonic() - self.last_resource_request >= .3:
                    self.report.setdefault("residency_wait_observations", []).append({"label": self.current[0], "elapsed_seconds": elapsed, "textures": records})
                    self.current_dump = self.request_texture_dump(self.current[0])
                    self.last_resource_request = time.monotonic()
                return
            if elapsed < 1:
                return
            self.current_residency = records
            self.report["initial_residency_before_force"] = self.read_texture_dump(self.initial_dump)
            self.phase_started = time.monotonic()
            self.tick_count = 0
            self.stage = "settle"
        except Exception as error:
            self.report["error"] = str(error)
            self.finish("failed")

    def pose_check(self):
        result = super().pose_check()
        result["actual_texture_residency"] = self.current_residency
        if self.original_mode:
            if self.body.get_material(0) != self.original_material:
                raise ValueError("Original material control shot assignment differs")
            result["actual_material_parameters"] = {"mode": "original_frozen_material"}
        else:
            actual_color = team_import.values(self.mid.get_vector_parameter_value("TeamColor"))
            actual_strength = float(self.mid.get_scalar_parameter_value("TeamColorStrength"))
            if self.body.get_material(0) != self.mid or self.mid.get_editor_property("parent") != self.team_material:
                raise ValueError("Actual component MID assignment or parent differs")
            if max(abs(actual - expected) for actual, expected in zip(actual_color, team_import.TEAM_COLORS[self.current_team])) > 1e-6 or actual_strength != self.current_strength:
                raise ValueError("Actual MID parameter values differ from requested shot")
            result["actual_material_parameters"] = {"mode": "derived_component_mid", "team": self.current_team,
                                                     "TeamColor": actual_color, "TeamColorStrength": actual_strength}
        return result

    def position_camera(self):
        unreal = self.unreal
        crop = self.current[4]
        if crop == "face":
            target = unreal.Vector(2, 0, 134)
            offset = unreal.Vector(120, 18, 8)
            self.camera_component.set_field_of_view(28)
        elif crop == "far":
            target = unreal.Vector(0, 0, 75)
            offset = unreal.Vector(705, 990, 360)
            self.camera_component.set_field_of_view(38)
        else:
            super().position_camera()
            return
        location = target + offset
        self.camera.set_actor_location(location, False, False)
        self.camera.set_actor_rotation(unreal.MathLibrary.find_look_at_rotation(location, target), False)

    def finish(self, status):
        try:
            for record in self.team["result"]["disk_dependency_validation"]["files"] + self.team["frozen_packages"]:
                team_import.check_record(record, "package_file")
            self.report["original_and_derived_asset_bytes_unchanged"] = True
        except Exception as error:
            self.report["error"] = str(error)
            self.report["original_and_derived_asset_bytes_unchanged"] = False
            status = "failed"
        super().finish(status)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--import-report", type=Path, default=os.environ.get("CIVWAR_STONEAXE_RENDER_IMPORT_REPORT", str(team_import.PILOT / "delivery_v05c/unreal_fresh_reopen_v5.json")))
    parser.add_argument("--socket-report", type=Path, default=os.environ.get("CIVWAR_STONEAXE_RENDER_SOCKET_REPORT", str(team_import.PILOT / "delivery_v05c/socket_apply_05.json")))
    parser.add_argument("--team-report", type=Path, default=os.environ.get("CIVWAR_STONEAXE_TEAM_RENDER_REPORT", str(team_import.PILOT / "team_color_v01/ue_fresh_02.json")))
    parser.add_argument("--output", type=Path, default=os.environ.get("CIVWAR_STONEAXE_RENDER_OUTPUT"))
    parser.add_argument("--log-file", type=Path, default=os.environ.get("CIVWAR_STONEAXE_TEAM_RENDER_LOG"))
    parser.add_argument("--labels", default=os.environ.get("CIVWAR_STONEAXE_RENDER_LABELS", ""))
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--dry-run", action="store_true")
    args, unknown = parser.parse_known_args()
    if not args.output:
        raise ValueError("Explicit new output directory required")
    for name in ("import_report", "socket_report", "team_report", "output"):
        setattr(args, name, getattr(args, name).resolve())
    if args.log_file:
        args.log_file = args.log_file.resolve()
    if not 256 <= args.size <= 768:
        raise ValueError("Review captures must remain between256 and768pixels")
    imported, fitted, calibration = review.validate_inputs(args)
    team = check_team_input(args)
    count = sum(1 for shot in SHOTS if not args.labels or shot[0] in set(args.labels.split(",")))
    if args.dry_run:
        print(json.dumps({"status": "inputs_checked_no_ue_render", "actual_images": 0, "planned_images": count, "output": str(args.output)}))
        return
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError("Never overwrite previous capture evidence")
    args.output.mkdir(parents=True, exist_ok=True)
    import unreal
    try:
        review.SESSION = TeamReviewSession(unreal, args, imported, fitted, calibration, team)
    except Exception as error:
        (args.output / "ue_render_report.json").write_text(json.dumps({"version": VERSION, "status": "failed_before_capture", "error": str(error), "actual_images": 0,
                                                                       "runtime_approved": False, "production_approved": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        unreal.EditorPythonScripting.set_keep_python_script_alive(False)
        raise


if __name__ == "__main__":
    main()
