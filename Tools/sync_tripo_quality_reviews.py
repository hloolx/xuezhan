"""Merge stage-specific QA evidence into the existing task ledger without API calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01"


def merge_isolated_import(ledger, report, evidence, root=ROOT):
    if report.get("dry_run") is not False or report.get("failed") != 0:
        raise ValueError("A successful real UE import report is required")
    for result in report["results"]:
        if result.get("status") not in {"imported", "reused_existing"} or result.get("warnings"):
            raise ValueError("UE import requires review: " + result["id"])
        source = root / result["source"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != result["source_sha256"]:
            raise ValueError("UE imported source changed: " + result["id"])
        meshes = [item for item in result["assets"] if item.get("type") == "static_mesh"]
        if len(meshes) != 1 or result["material_audit"]["status"] != "structural_checks_passed":
            raise ValueError("Missing mesh or material proof: " + result["id"])
    for result in report["results"]:
        mesh = next(item for item in result["assets"] if item.get("type") == "static_mesh")
        review = ledger["assets"][result["id"]].setdefault("quality_review", {})
        review["isolated_ue_import"] = {
            "evidence": evidence, "source_sha256": result["source_sha256"],
            "destination": result["destination"], "mesh": mesh["path"],
            "triangles_lod0": mesh["triangles_lod0"], "dimensions_cm": mesh["dimensions_cm"],
            "runtime_material_overrides": result["runtime_material_overrides"],
            "status": "structural_checks_passed_game_camera_pending",
            "production_approved": False
        }


def merge_current_checkpoints(ledger):
    bindings = {
        "stoneaxe_actual_assembly_pilot": (["Unit_StoneAxe"], "controlled_game_rig_grip_team_reviewed_not_production"),
        "environment_six_partial_game_review": (["Env_BoulderA", "Env_BoulderB", "Env_RockSlab", "Env_Shrub", "Env_Pine", "Env_Broadleaf"], "six_asset_partial_game_reviewed_not_full_environment"),
        "base_stone_pbr_pilot": (["Base_Stone"], "controlled_base_pbr_game_reviewed_remaining_assembly_and_team_gates"),
        "stone_slinger_geometry_pilot": (["Unit_StoneSlinger"], None),
        "mammoth_geometry_pilot": (["Mount_Mammoth"], None),
    }
    visual_gates = {
        "stoneaxe_actual_assembly_pilot": lambda checkpoint: checkpoint.get("controlled_team_shader_approved") is True
        and checkpoint.get("live_team_shader_reviewed_images", 0) >= 6,
        "environment_six_partial_game_review": lambda checkpoint: checkpoint.get("reviewed_actual_game_images", 0) >= 16
        and set(checkpoint.get("camera_sides", [])) == {0, 1},
        "base_stone_pbr_pilot": lambda checkpoint: checkpoint.get("controlled_material_and_scale_visual_passed") is True
        and checkpoint.get("game_visual_pending") is False,
    }
    for checkpoint_name, (asset_ids, status) in bindings.items():
        checkpoint = ledger.get("acceptance_checkpoints", {}).get(checkpoint_name)
        if not checkpoint or checkpoint.get("production_approved") is True:
            continue
        for asset_id in asset_ids:
            if asset_id not in ledger.get("assets", {}):
                continue
            review = ledger["assets"][asset_id].setdefault("quality_review", {})
            review.setdefault("historical_stage_status", review.get("status"))
            review["current_checkpoint"] = checkpoint_name
            review["current_checkpoint_evidence"] = dict(checkpoint)
            visual_passed = checkpoint_name not in visual_gates or visual_gates[checkpoint_name](checkpoint)
            review["status"] = status if status and visual_passed else checkpoint.get("status", "stage_specific_review_pending")
            review["production_approved"] = False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verified-balance", type=float)
    parser.add_argument("--verified-frozen", type=float)
    parser.add_argument("--ue-report", action="append", default=[])
    args = parser.parse_args()
    path = ART / "jobs/execution.json"
    ledger = json.loads(path.read_text(encoding="utf-8-sig"))
    review_path = ART / "tripo_processed/geometry_v03_canonical_others/geometry_review.json"
    if review_path.exists():
        document = json.loads(review_path.read_text(encoding="utf-8-sig"))
        for item in document["assets"]:
            asset = ledger["assets"][item["id"]]
            asset.setdefault("quality_review", {}).update({
                "status": item["decision"],
                "reviewed_geometry_task_id": item["task_id"],
                "texture_pilot_ready": item["texture_pilot_ready"],
                "observations": item["observations"],
                "next": item["next"],
                "evidence": review_path.relative_to(ROOT).as_posix(),
                "production_approved": False,
                "runtime_status": "formal_tripo_set_not_yet_registered"
            })
    broadleaf_path = ART / "tripo_processed/cleanup_v03/texture_input/review.json"
    pine_path = ART / "tripo_processed/geometry_v03_canonical_others/cleanup/Env_Pine/geometry_four_view_approval.json"
    if pine_path.exists():
        document = json.loads(pine_path.read_text(encoding="utf-8-sig"))
        pine = ledger["assets"]["Env_Pine"]
        textures = [item for item in pine.get("task_history", []) if item["version"] == "textured_cleanup_v03"]
        pine["quality_review"].update(status="cleaned_four_view_approved_texture_validation_pending",
            cleaned_input_sha256=document["model_sha256"], texture_pilot_ready=document["approved_for_texture_pilot"],
            cleaned_geometry_review=pine_path.relative_to(ROOT).as_posix(),
            texture_task_id=textures[-1]["task_id"] if textures else None)
    if broadleaf_path.exists():
        document = json.loads(broadleaf_path.read_text(encoding="utf-8-sig"))
        broadleaf = ledger["assets"]["Env_Broadleaf"]
        textures = [item for item in broadleaf.get("task_history", []) if item["version"] == "textured_cleanup_v03"]
        broadleaf.setdefault("quality_review", {}).update({
            "status": "cleaned_geometry_uv_passed_texture_validation_pending",
            "evidence": broadleaf_path.relative_to(ROOT).as_posix(),
            "cleaned_input_sha256": document["sha256"],
            "protected_original_faces": document["protected_original_faces"],
            "protected_geometry_exact": document["protected_geometry_exact"],
            "triangles": document["triangles"],
            "requires_new_texture": True,
            "texture_task_id": textures[-1]["task_id"] if textures else None,
            "production_approved": False,
            "runtime_status": "formal_tripo_set_not_yet_registered"
        })
    stoneaxe = ledger["assets"].get("Unit_StoneAxe", {})
    rigs = [item for item in stoneaxe.get("task_history", []) if item["type"] == "animate_rig"]
    if rigs:
        review = stoneaxe.setdefault("quality_review", {})
        review.update(paid_rig_submitted=True, rig_task_id=rigs[-1]["task_id"],
                      rig_provider_status=rigs[-1]["provider_status"],
                      rig_credits=rigs[-1]["credits_charged"],
                      status="actual_rig_grip_and_animation_validation_in_progress",
                      production_approved=False)
    approval_paths = list((ART / "tripo_processed/textured_v03_canonical_others").glob("*/approval.json"))
    approval_paths += list((ART / "tripo_processed/textured_cleanup_v03").glob("**/approval.json"))
    for approval_path in approval_paths:
        document = json.loads(approval_path.read_text(encoding="utf-8-sig"))
        source = ROOT / document["model_file"]
        if document.get("approved_for_ue_import") is not True:
            continue
        if hashlib.sha256(source.read_bytes()).hexdigest() != document["model_sha256"]:
            raise ValueError("Approved model changed: " + str(source))
        review = ledger["assets"][document["asset_id"]].setdefault("quality_review", {})
        review.update(status="textured_four_view_approved_pending_ue_acceptance", approved_for_ue_import=True,
                      reviewed_textured_model=document["model_file"], reviewed_textured_sha256=document["model_sha256"],
                      pbr_evidence=approval_path.relative_to(ROOT).as_posix(), production_approved=False)
    checkpoint = ART / "tripo_processed/stoneaxe_rig_pilot/checkpoint.json"
    if checkpoint.exists() and rigs:
        document = json.loads(checkpoint.read_text(encoding="utf-8-sig"))
        review = stoneaxe["quality_review"]
        review.update(actual_bone_count=document["rig"]["bone_count"], grip=document["grip_current"],
                      animation_status=document["animation_draft"]["status"], approved=document["approved"],
                      actual_rig_evidence=checkpoint.relative_to(ROOT).as_posix())
    if args.verified_balance is not None:
        if args.verified_frozen is None:
            raise ValueError("Provide frozen value from the same live balance response")
        ledger["credit_policy"].update(last_verified_balance=args.verified_balance,
            last_verified_frozen=args.verified_frozen, verified_at=datetime.now(timezone.utc).isoformat())
    for report_name in args.ue_report:
        report_path = ROOT / report_name
        merge_isolated_import(ledger, json.loads(report_path.read_text(encoding="utf-8-sig")),
                              report_path.relative_to(ROOT).as_posix())
    merge_current_checkpoints(ledger)
    ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"updated_assets": ["Env_Pine", "Env_Shrub", "Env_GrassClump", "Env_Broadleaf", "Unit_StoneAxe"],
                      "production_approved": False}))


if __name__ == "__main__":
    main()
