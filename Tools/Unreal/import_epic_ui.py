"""Import only the selected, provenance-recorded Kenney CC0 frame texture.

UnrealEditor-Cmd.exe F:/code/CivWar/CivWar.uproject -run=pythonscript
    -script=F:/code/CivWar/Tools/Unreal/import_epic_ui.py -unattended -nop4 -nosplash
    -DDC=InstalledNoZenLocalFallback
"""
import hashlib
import json
from pathlib import Path
import struct
import unreal


def main():
    root = Path(unreal.Paths.project_dir()).resolve()
    source = root / "RawAssets" / "UI" / "EpicBorders"
    manifest = json.loads((source / "selection_manifest.json").read_text(encoding="utf-8-sig"))
    entries = manifest["assets"]
    for entry in entries:
        path = source / entry["file"]
        if path.parent != source or path.suffix != ".png" or not path.name.startswith("T_"):
            raise RuntimeError("Unsafe UI manifest path: " + str(path))
        original = (root / entry["source_file"]).resolve()
        original.relative_to(root / "RawAssets" / "ThirdParty")
        data = path.read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("Expected PNG: " + str(path))
        if struct.unpack(">II", data[16:24]) != (entry["width"], entry["height"]):
            raise RuntimeError("Incorrect PNG dimensions: " + str(path))
        if hashlib.sha256(data).hexdigest() != entry["sha256"] or data != original.read_bytes():
            raise RuntimeError("UI source no longer matches the licensed original: " + str(path))
        if entry["license"] != "CC0-1.0" or entry["unreal_asset"] != "/Game/UI/EpicBorders/" + path.stem:
            raise RuntimeError("Unexpected license or destination: " + str(path))

    tasks = []
    for entry in entries:
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", str(source / entry["file"]))
        task.set_editor_property("destination_path", "/Game/UI/EpicBorders")
        task.set_editor_property("destination_name", Path(entry["file"]).stem)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("replace_existing_settings", True)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", True)
        tasks.append(task)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)

    settings = {
        "compression_settings": unreal.TextureCompressionSettings.TC_EDITOR_ICON,
        "lod_group": unreal.TextureGroup.TEXTUREGROUP_UI,
        "mip_gen_settings": unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS,
        "srgb": True,
        "never_stream": True,
        "compression_no_alpha": False,
        "filter": unreal.TextureFilter.TF_BILINEAR,
        "address_x": unreal.TextureAddress.TA_CLAMP,
        "address_y": unreal.TextureAddress.TA_CLAMP,
    }
    receipt = {"version": 1, "expected_count": len(entries), "assets": []}
    for entry, task in zip(entries, tasks):
        asset_path = entry["unreal_asset"]
        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not isinstance(asset, unreal.Texture2D) or not task.get_editor_property("imported_object_paths"):
            raise RuntimeError("UI texture import failed: " + asset_path)
        for key, value in settings.items():
            asset.set_editor_property(key, value)
        if not unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=False):
            raise RuntimeError("Could not save: " + asset_path)
        for key, value in settings.items():
            if asset.get_editor_property(key) != value:
                raise RuntimeError("UI texture setting mismatch: %s.%s" % (asset_path, key))
        receipt["assets"].append({"path": asset_path, "source_sha256": entry["sha256"],
                                  "width": entry["width"], "height": entry["height"],
                                  "license": entry["license"],
                                  "settings": {key: str(value) for key, value in settings.items()}})
    receipt["status"] = "passed"
    report = root / "Saved" / "EpicUIImportReport.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    unreal.log("CIVWAR_EPIC_UI_IMPORT_PASSED assets=%d report=%s" % (len(entries), report))


if __name__ == "__main__":
    main()
