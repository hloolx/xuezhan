from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_dual_mask_ue as adapter
import base_stone_dual_mask_render as render


def main():
    folder = adapter.FOLDER
    path = folder / "ue_execution_spec_v01.json"
    if path.exists():
        raise FileExistsError("Keep frozen prior execution plan")
    context = adapter.source_inputs()
    old = adapter.read(adapter.previous.FOLDER / "ue_execution_spec_v01.json")
    ue_folder = "F:/code/CivWar/" + folder.relative_to(adapter.ROOT).as_posix()
    script = "F:/code/CivWar/Tools/base_stone_dual_mask_ue.py"
    renderer = "F:/code/CivWar/Tools/base_stone_dual_mask_render.py"
    token = context["destination"].split("/")[-1]
    spec = dict(old)
    spec.update(schema_version=2, created_at=datetime.now(timezone.utc).isoformat(),
                status="dual_mask_candidate_prepared_pending_root_preview_review_no_ue_execution",
                candidate_destination=context["destination"], root_preview_review_approved=False,
                execution_gate="Root must first inspect the3candidate previews and explicitly set the branch token below; agentA has no heavy-process authority.",
                input_check=adapter.file_record(folder / "ue_input_check_01.json"),
                candidate_guard_sha256=adapter.GUARD_SHA, candidate_protection_sha256=adapter.PROTECTION_SHA,
                candidate_report_sha256=adapter.REPORT_SHA, candidate_report=adapter.file_record(folder / "candidate_report.json"),
                source_atlas_semantic_approval="Prior1217stroke semantic evidence retained; newbilinear sampling preview review still pending.",
                create_fresh_script=script, create_fresh_script_sha256=adapter.sha(adapter.__file__),
                render_script=renderer, render_script_sha256=adapter.sha(render.__file__),
                initial_environment={"CIVWAR_BASE_TEAM_REPORT": ue_folder + "/ue_persist_01.json", "CIVWAR_BASE_TEAM_REOPEN_ONLY": "0",
                                     "CIVWAR_BASE_TEAM_PRIOR_REPORT": "", "CIVWAR_BASE_DUAL_EXECUTE_TOKEN": token},
                fresh_environment={"CIVWAR_BASE_TEAM_REPORT": ue_folder + "/ue_fresh_01.json", "CIVWAR_BASE_TEAM_REOPEN_ONLY": "1",
                                   "CIVWAR_BASE_TEAM_PRIOR_REPORT": ue_folder + "/ue_persist_01.json", "CIVWAR_BASE_DUAL_EXECUTE_TOKEN": token},
                render_environment={"CIVWAR_BASE_TEAM_RENDER_REPORT": ue_folder + "/ue_fresh_01.json",
                                    "CIVWAR_BASE_TEAM_RENDER_OUTPUT": ue_folder + "/ue_control_review_01",
                                    "CIVWAR_BASE_TEAM_RENDER_LOG": ue_folder + "/ue_control_review_01.log"},
                tests={"new_dual_mask_sampling_graph_and_residency_tests": 18, "weighted_and_frozen_side_regression_tests": 32},
                preserved_existing_packages={"original_Base": 5, "StoneAxe": 21, "safe1_team": 4, "footprint_team": 4, "binary_side_team": 4, "total": 38},
                new_packages=5, total_packages_after_trial=43,
                required_native_resident_textures_per_shot=5,
                mask_contract={"strict_guard_sha256": adapter.GUARD_SHA, "strict_guard_filter": "Nearest",
                               "local_protection_sha256": adapter.PROTECTION_SHA, "local_protection_filter": "Bilinear",
                               "formula": "guardNearest * (1 - protectionBilinear) * saturate(TeamColorStrength)",
                               "same_selected_faces": 714, "same_held_faces": 6,
                               "semantic_protection_texels": 1217, "fully_protected_entire_texel_cells": 613, "partial_boundary_cells": 604,
                               "effective_support_cells": 1900, "local_fringe_cells_only_reducing_existing_dye": 683,
                               "new_noncloth_or_held_dye_support": 0, "other_source_triangles_affected": 0,
                               "front45_entire_cells_unchanged": True, "previous30_uv_gaps_still_on": True,
                               "both_actual_game_uv_probes_final_tint": 0, "no_global_pigment_change": True},
                acceptance_gates=["Root actual candidate3preview review must precede initial execution.",
                                  "Strict graph audit must prove unchangedNearest guard multiplied by1-minus independentBilinear protection, not a globally linear guard or bypass.",
                                  "Five packages must save and remain byte-identical through independent fresh reopen; previous38packages unchanged.",
                                  "FinishAll before actual sampler/material audit and exact5x2048native residency at every one of12shots. Missing fifth texture or1024resident must fail.",
                                  "Original/disabled controls, side emblem core and smoothed fringe, no detached high-contrast patches, unchanged frontwhite/old triangle gaps must be reviewed.",
                                  "All43packages and originalatlas/GLB/UV remain unchanged after actual capture; no Content configuration switch until separate approval.",
                                  "Controlled images do not replace actualbothteam noHUD gameplay, held6/fullcloth, door/turret or full-load performance gates."],
                actual_ue_execution_completed=False, actual_visual_approved=False, runtime_approved=False, production_approved=False)
    spec.pop("candidate_mask_sha256", None)
    spec["initial_and_fresh_arguments"] = ["-ExecutePythonScript=" + script if item.startswith("-ExecutePythonScript=") else item for item in old["initial_and_fresh_arguments"]]
    spec["render_arguments"] = ["-ExecutePythonScript=" + renderer if item.startswith("-ExecutePythonScript=") else
                                "-abslog=" + ue_folder + "/ue_control_review_01.log" if item.startswith("-abslog=") else item for item in old["render_arguments"]]
    spec["frozen_reused_implementations"].extend([adapter.file_record(adapter.previous.__file__), adapter.file_record(Path(render.__file__).parent / "base_stone_side_emblem_render.py")])
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review = {"created_at": datetime.now(timezone.utc).isoformat(), "status": "sampling_support_passed_candidate_previews_reviewed_by_A_pending_root_and_actual_UE",
              "personally_viewed": ["atlas_source_crop_x6.png", "bilinear_protection_preview_x6.png", "atlas_bilinear_weight_overlay_x6.png"],
              "observation": "Independent protection contour interpolates rather than nearest-stepping. Source ring/divider/strokes remain within prior semantics; extra683fringe cells only reduce preexisting dye on the same sourcecluster0. Faded/detached marks remain source-semantic and must be judged in real red/blue lighting; atlas preview is not visual approval.",
              "core_and_probe_proof": "613entire nearest cells are fully protected analytically; both actual-game UV ray probes evaluate protection1/finalTint0 via four actual neighboring texels.604boundary cells may blend. No ad-hoc pixel overrides.",
              "candidate_report": adapter.file_record(folder / "candidate_report.json"), "execution_spec": adapter.file_record(path),
              "root_preview_review_approved": False, "actual_ue_visual_approved": False, "runtime_approved": False, "content_modified": False}
    (folder / "agent_review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"spec": adapter.file_record(path), "branch": context["destination"], "token": token}, indent=2))


if __name__ == "__main__":
    main()
