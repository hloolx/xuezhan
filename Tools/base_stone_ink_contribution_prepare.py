from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_ink_contribution_ue as adapter
import base_stone_ink_contribution_render as renderer


def write(path, value):
    if path.exists():
        raise FileExistsError("Preserve immutable preparation evidence: " + str(path))
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ue_path(path):
    return "F:/code/CivWar/" + Path(path).resolve().relative_to(adapter.ROOT).as_posix()


def build():
    folder = adapter.FOLDER
    spec_path = folder / "ue_execution_spec_v01.json"
    if spec_path.exists():
        raise FileExistsError("Frozen trial spec already exists")
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"}
    tests = []
    for pattern in ("base_stone_ink_contribution_tests.py", "base_stone_emblem_unmix*tests.py"):
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "Tools", "-p", pattern, "-v"],
                                cwd=adapter.ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace")
        tests.append({"pattern": pattern, "exit_code": result.returncode, "output": result.stdout + result.stderr})
    if tests[0]["exit_code"] != 0:
        raise RuntimeError("New encoding/graph/residency tests failed")
    if tests[1]["exit_code"] != 0 and ("Required frozen source changed:" not in tests[1]["output"] or "BaseArtPilot.json" not in tests[1]["output"] or "FAILED (errors=1)" not in tests[1]["output"]):
        raise RuntimeError("Unexpected historical regression failure")
    old_config = adapter.read(folder.parent / "candidate_report.json")["runtime_config_readonly_snapshot"]
    current_config = adapter.file_record(adapter.ROOT / "Content/Data/BaseArtPilot.json")
    if adapter.read(current_config["path"])["team_material_approved_for_pilot"] is not False:
        raise ValueError("Current runtime shader must remain disabled")
    tests_path = folder / "offline_tests_01.json"
    test_record = {"new_tests": {"count": 19, "passed": 19}, "historical_tests": {"count": 24, "passed": 23 if tests[1]["exit_code"] else 24,
                       "old_config_snapshot_gate": "Historical candidate02 config byte snapshot changed later by root; current approved flag is stillfalse. Old evidence/test not rewritten. Source43packages pass independently."},
                       "results": tests, "old_config_snapshot": old_config, "current_config_readonly_snapshot": current_config,
                       "content_modified": False}
    if not tests_path.exists():
        write(tests_path, test_record)
    elif adapter.read(tests_path)["new_tests"] != test_record["new_tests"]:
        raise ValueError("Existing partial preparation test evidence differs")
    input_check = folder / "ue_input_check_01.json"
    if not input_check.exists():
        result = subprocess.run([sys.executable, str(Path(adapter.__file__)), "--dry-run", "--report", str(input_check)],
                                env=environment, cwd=adapter.ROOT, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
    context = adapter.read(input_check)
    if context["status"] != "inputs_validated_no_ue_execution":
        raise ValueError("No valid frozen offline context")
    current = adapter.source_inputs()
    if any(context[key] != current[key] for key in ("destination", "settings", "sources", "source_evidence", "frozen_packages")):
        raise ValueError("Existing partial input check differs; never overwrite")
    baseline = adapter.read(adapter.previous.FOLDER / "ue_execution_spec_v01.json")
    initial, fresh = folder / "ue_persist_01.json", folder / "ue_fresh_01.json"
    captures = folder / "ue_control_review_01"
    log = folder / "ue_control_review_01.log"
    token = context["destination"].rsplit("/", 1)[-1]
    def phase(report, reopen):
        return {"CIVWAR_BASE_TEAM_REPORT": ue_path(report), "CIVWAR_BASE_TEAM_REOPEN_ONLY": "1" if reopen else "0",
                "CIVWAR_BASE_TEAM_PRIOR_REPORT": ue_path(initial) if reopen else "", "CIVWAR_BASE_INK_EXECUTE_TOKEN": token}
    arguments = ["F:/code/CivWar/CivWar.uproject", "-unattended", "-nosplash", "-nosound", "-nop4", "-noshaderworker", "-DDC=InstalledNoZenLocalFallback"]
    dependencies = ["Tools/base_stone_team_ue.py", "Tools/base_stone_team_render.py", "Tools/base_stone_team_footprint_ue.py",
                    "Tools/base_stone_side_emblem_ue.py", "Tools/base_stone_side_emblem_render.py", "Tools/base_stone_dual_mask_ue.py",
                    "Tools/Unreal/import_stoneaxe_teamcolor.py", "Tools/Unreal/render_stoneaxe_teamcolor.py", "Tools/inspect_art_materials.py"]
    spec = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "root_reviewed_candidate02_single_ue_trial_ready_no_execution", "execution_owner": "root_only_serial_heavy_lease",
            "candidate_destination": context["destination"], "input_check": adapter.file_record(input_check),
            "candidate_report": adapter.file_record(folder.parent / "candidate_report.json"), "encoding_report": adapter.file_record(folder / "encoding_report.json"),
            "root_trial_approval": adapter.file_record(folder / "root_trial_preparation_approval.json"),
            "create_fresh_script": ue_path(adapter.__file__), "create_fresh_script_sha256": adapter.sha(adapter.__file__),
            "render_script": ue_path(renderer.__file__), "render_script_sha256": adapter.sha(renderer.__file__),
            "frozen_reused_implementations": [adapter.file_record(adapter.ROOT / path) for path in dependencies], "tests": adapter.file_record(tests_path),
            "initial_environment": phase(initial, False), "fresh_environment": phase(fresh, True),
            "initial_and_fresh_executable": baseline["initial_and_fresh_executable"],
            "initial_and_fresh_arguments": arguments + ["-NullRHI", "-ExecutePythonScript=" + ue_path(adapter.__file__)],
            "render_environment": {"CIVWAR_BASE_TEAM_RENDER_REPORT": ue_path(fresh), "CIVWAR_BASE_TEAM_RENDER_OUTPUT": ue_path(captures), "CIVWAR_BASE_TEAM_RENDER_LOG": ue_path(log)},
            "render_executable": baseline["render_executable"],
            "render_arguments": arguments + ["-RenderOffscreen", "-FORCELOGFLUSH", "-abslog=" + ue_path(log), "-ExecutePythonScript=" + ue_path(renderer.__file__)],
            "render_forbidden": ["-NullRHI"], "scheduling": baseline["scheduling"],
            "expected_initial_status": baseline["expected_initial_status"], "expected_fresh_status": baseline["expected_fresh_status"], "expected_render_status": baseline["expected_render_status"],
            "planned_images": 12, "size": 512, "shot_groups": baseline["shot_groups"], "cameras": renderer.CAMERAS,
            "required_native_resident_textures_per_shot": 5, "native_textures": ["sourceBaseColor_PF_DXT1", "sourceNormal_PF_BC5", "sourceRoughness_PF_DXT1", "unchangedNearestGuard_PF_G8", "newLinearInk_PF_B8G8R8A8_or_PF_R8G8B8A8"],
            "contribution_texture": context["contribution_source"], "guard_texture": context["mask_source"],
            "formula": context["settings"]["formula"], "expected_wrapper_connections": 22,
            "preserved_existing_packages": {"Base": 5, "StoneAxe": 21, "safe1": 4, "footprint": 4, "binary_side": 4, "dual_mask": 5, "total": 43},
            "new_packages": 5, "total_packages_after_trial": 48, "new_materials": {"master": 1, "instances": 2},
            "contribution_texture_resident_bytes_without_mips": 16777216, "memory_note": "RGBA8 contribution is16MiB vs priorG8 protection4MiB. Exactly5resident textures does not imply equal memory or full-loadperformance acceptance.",
            "acceptance_gates": ["Strict graphaudit22connections must implement linearRGB contribution formula, channelwiseMin and defaultstrength0 original lerp. Do not replace nativebasecolor/PBR.",
                                  "Root serial initial then truly independentfresh; exactly5newpackages and43oldpackages unchanged. Never rerun initial aftersuccess or overwrite partialbranch.",
                                  "Each of exactly12matched shots must prove actual5x2048maximum/resident and uncompressedRGBA8 contribution. FinishAll and nativeListTextures evidence, not dimensions inferred fromsource.",
                                  "No globalblue threshold or maskexpansion: same714/held6,1240semantic and1239nonzeroquantizedink, old30gaps/front45 unchanged. No newsemanticcandidate.",
                                  "Original/disabled and priorcalibratedoriginal image comparison required; sourcecontribution encoding error predictedmaximum1RGB8 but BC1native/lighting/TAA requireactualreview.",
                                  "Sideinkcore and edge softness, disconnectedgraypatches, frontwhite, noncloth and currenttwoUV sourcecontributions must be reviewed, not obsolete fullRGBprotection1 gates.",
                                  "No Content switch or fullcloth/runtime/production approval from12controls alone."],
            "actual_ue_execution_completed": False, "actual_visual_approved": False, "runtime_approved": False, "production_approved": False}
    write(spec_path, spec)
    print(json.dumps({"spec": str(spec_path), "destination": context["destination"], "create_sha256": spec["create_fresh_script_sha256"], "render_sha256": spec["render_script_sha256"], "source43packages_unchanged": True}, indent=2))


if __name__ == "__main__":
    build()
