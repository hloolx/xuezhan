"""Import one derived glove-weight mesh onto the existing reviewed skeleton.

No original package or runtime mapping is rewritten. The caller owns the UE
heavy lease and activates the mesh only after reviewing actual game images.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).parent))
import import_beast_rider_preview as base
import import_era_character as character

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = "/Game/ArtPilot/EraCharacters/Champion_Future/ha5ee529f8f0aa8a0"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot():
    directory = ROOT/"Content"/(ORIGINAL[6:])
    return {str(path): sha(path) for path in directory.rglob("*.uasset")}


def run(u, report_path, output):
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if report["schema"] != "future_glove_weight_repair_v1" or report["geometry_before"] != report["geometry_after"]:
        raise ValueError("Not a verified weight-only derived mesh")
    fbx = Path(report["mesh_fbx"]["path"])
    if sha(fbx) != report["mesh_fbx"]["sha256"]:
        raise ValueError("Derived FBX changed")
    original = u.EditorAssetLibrary.load_asset(ORIGINAL+"/SK_Champion_Future")
    skeleton = original.get_editor_property("skeleton")
    before = snapshot()
    destination = "/Game/ArtPilot/VisualPolish/FutureGloves/h"+sha(fbx)[:16]
    options = base.options(u)
    options.set_editor_property("skeleton", skeleton)
    mesh = base.task(u, fbx, destination, "SK_Champion_Future_GloveWeights", options, u.FbxFactory())
    if mesh.get_editor_property("skeleton") != skeleton:
        raise ValueError("Derived mesh must use the original skeleton")
    names = lambda value: [str(x) for x in u.AnimPoseExtensions.get_bone_names(u.AnimPoseExtensions.get_reference_pose(value))]
    if names(skeleton) != names(original.get_editor_property("skeleton")) or "weapon_r" not in names(skeleton):
        raise ValueError("Original skeleton/weapon attachment changed")
    slots = list(original.get_editor_property("materials"))
    if len(mesh.get_editor_property("materials")) != len(slots):
        raise ValueError("Derived material slots changed")
    mesh.set_editor_property("materials", slots)
    settings = u.SkeletalMeshEditorSubsystem.get_lod_build_settings(mesh, 0)
    settings.set_editor_property("use_high_precision_skin_weights", True)
    u.SkeletalMeshEditorSubsystem.set_lod_build_settings(mesh, 0, settings)
    clips = {}
    for name in ("Idle", "Move", "Attack", "Hit", "Death"):
        clip = u.EditorAssetLibrary.load_asset(ORIGINAL+"/Animations/A_"+name)
        if clip.get_editor_property("skeleton") != skeleton:
            raise ValueError("Original five actions no longer share the skeleton")
        for t in (0., float(u.AnimationLibrary.get_sequence_length(clip))*.5):
            character.evaluate_pose(u, mesh, {name: clip}, {"clip": name, "time_seconds": t})
        clips[name] = clip.get_path_name()
    u.EditorAssetLibrary.save_loaded_asset(mesh, only_if_is_dirty=False)
    if snapshot() != before:
        raise ValueError("An original reviewed package was rewritten")
    files = list((ROOT/"Content"/destination[6:]).glob("*.uasset"))
    result = {"status": "imported_weight_only_pending_gameplay", "mesh": mesh.get_path_name(),
              "skeleton": skeleton.get_path_name(), "destination": destination, "process_id": os.getpid(),
              "clips": clips, "original_packages_unchanged": True, "original_package_count": len(before),
              "new_packages": [{"path": str(path), "sha256": sha(path)} for path in files],
              "source_report": str(report_path), "failures": [], "runtime_mapping_changed": False}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return result


def execute(report_path, output):
    import unreal
    try:
        return run(unreal, Path(report_path), Path(output))
    except Exception as error:
        Path(output).write_text(json.dumps({"status": "failed", "error": str(error), "traceback": traceback.format_exc()}, indent=2)+"\n", encoding="utf-8")
        raise


if __name__ == "__main__":
    if os.environ.get("CIVWAR_FUTURE_GLOVE_IMPORT_REPORT"):
        execute(os.environ["CIVWAR_FUTURE_GLOVE_IMPORT_REPORT"], os.environ["CIVWAR_FUTURE_GLOVE_IMPORT_OUTPUT"])
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument("--repair-report", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        args = parser.parse_args()
        execute(args.repair_report.resolve(), args.output.resolve())
