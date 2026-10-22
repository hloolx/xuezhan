"""Import real horse clips and sample the actual UE saddle attachment frame."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
import import_era_character as character
import fit_stoneaxe_socket as fit


def execute(manifest_path, report_path):
    import unreal as u
    result = character.execute(manifest_path, report_path)
    mesh = u.EditorAssetLibrary.load_asset(result["mesh"])
    skeleton = mesh.get_editor_property("skeleton")
    reference = u.AnimPoseExtensions.get_reference_pose(skeleton)
    if "saddle_seat" not in result["bone_names"]:
        raise ValueError("The horse has no actual saddle attachment bone")
    transform = u.AnimPoseExtensions.get_bone_pose(reference, "saddle_seat", u.AnimPoseSpaces.WORLD)
    q = transform.rotation
    rotation = u.Quat(-q.x, -q.y, -q.z, q.w).rotator()
    result["saddle"] = {
        "bone": "saddle_seat",
        "reference_transform": fit.ue_transform(transform),
        "rider_rotation_degrees": [rotation.pitch, rotation.yaw, rotation.roll],
        "rider_translation_cm": [0., 0., 0.],
        "reference_frame": "Actual imported UE skeleton; rider origin sits at saddle surface",
    }
    Path(report_path).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    execute(args.manifest.resolve(), args.output.resolve())
