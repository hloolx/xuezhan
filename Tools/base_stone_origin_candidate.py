"""Compare the unchanged source and a virtual vertical placement; never export."""
import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).with_name("base_stone_spawn_check.py")
SPEC = importlib.util.spec_from_file_location("base_spawn_check", SCRIPT)
spawn = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(spawn)
ROOT_OUTPUT = spawn.measure.OWNED / "cpu_origin_comparison_v03"
ROOT_OUTPUT.mkdir(exist_ok=False)
comparisons = []
for label, offset_cm in (("baseline", 0), ("buried31cm", -31)):
    spawn.OUTPUT = ROOT_OUTPUT / label
    spawn.BASE_Z_CM = offset_cm
    spawn.main()
    report = json.loads((spawn.OUTPUT / "report.json").read_text(encoding="utf-8"))
    comparisons.append({"label": label, "base_translation_cm": report["base_translation_cm"],
                        "triangle_test_counts": report["triangle_test_counts"], "vertex_sweep_counts": report["vertex_sweep_counts"],
                        "ground_penetrating_pose_row_samples": report["ground_penetrating_pose_row_samples"],
                        "report": spawn.measure.record(spawn.OUTPUT / "report.json")})
result = {"asset_id": "Base_Stone", "status": "virtual_placement_comparison_not_visual_or_origin_approval", "comparisons": comparisons,
          "source_unchanged": spawn.measure.digest(spawn.measure.SOURCE) == spawn.measure.SOURCE_SHA,
          "diagnostic_model_unchanged": spawn.measure.digest(spawn.measure.PROBE) == spawn.measure.PROBE_SHA,
          "tool": spawn.measure.record(Path(__file__)), "mesh_exported": False, "gpu_used": False,
          "approved_for_texture": False, "approved_for_ue_import": False, "production_approved": False}
(ROOT_OUTPUT / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
