"""Import both real mounted-unit parts in one serialized UE process."""
from pathlib import Path
import sys
import json
import unreal

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import import_beast_rider_preview as importer

ROOT = HERE.parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed"
OUTPUT = ART / "beast_rider_v01/preview_delivery_02"

try:
    mount = importer.run(
        unreal, ART / "mammoth_v01/preview_delivery_02/manifest.json",
        OUTPUT / "ue_mount_import.json")
    rider = importer.run(
        unreal, OUTPUT / "manifest.json",
        OUTPUT / "ue_rider_import.json")
    result = {
        "status": "imported_preview_pending_gameplay",
        "visual_key": "Unit_BeastRider",
        "reference_move_speed_cm_s": 220,
        "attack_contact_seconds": .4,
        "parts": [
            {
                "id": "mount", "skeletal_mesh": mount["mesh"],
                "animations": {k: v["asset"] for k, v in mount["clips"].items()},
                "team_materials": [{"slot": 0, "path": mount["team_materials"]["Blue"],
                                    "red_path": mount["team_materials"]["Red"]}],
            },
            {
                "id": "rider", "skeletal_mesh": rider["mesh"],
                "animations": {k: v["asset"] for k, v in rider["clips"].items()},
                "parent_part": "mount", "parent_socket": "saddle_seat",
                "rotation_degrees": mount["attachment_reference"]["inverse_rotation_degrees"],
                "translation_cm": [0, 0, 0], "uniform_scale": 1,
                "team_materials": [{"slot": 0, "path": rider["team_materials"]["Blue"],
                                    "red_path": rider["team_materials"]["Red"]}],
            },
        ],
        "attachments": [
            {"static_mesh": rider["weapon"], "parent_part": "rider", "socket": "weapon_r",
             "translation_cm": [0, 0, 0],
             "rotation_degrees": rider["weapon_attachment"]["rotation_degrees"], "uniform_scale": 1}
        ],
        "production_approved": False,
    }
    (OUTPUT / "runtime_contract.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
finally:
    unreal.SystemLibrary.quit_editor()
