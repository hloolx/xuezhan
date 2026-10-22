"""Reimport only CivWar's manifest-listed audio, never maps/materials/other content.

UnrealEditor-Cmd.exe F:/code/CivWar/CivWar.uproject -run=pythonscript
    -script=F:/code/CivWar/Tools/Unreal/import_audio.py -unattended -nop4 -nosplash
    -DDC=InstalledNoZenLocalFallback
"""
import hashlib
import json
from pathlib import Path
import wave
import unreal


def main():
    root = Path(unreal.Paths.project_dir()).resolve()
    source = root / "RawAssets" / "Audio"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest["assets"]
    # Validate all source files before touching any imported assets.
    for entry in entries:
        path = source / entry["file"]
        if path.parent != source or not path.name.startswith("SFX_"):
            raise RuntimeError("Unsafe/non-audio manifest path: " + str(path))
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError("Source hash differs from manifest: " + str(path))
        with wave.open(str(path), "rb") as stream:
            if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (48000, 1, 2):
                raise RuntimeError("Expected 48 kHz mono PCM16: " + str(path))

    tasks = []
    for entry in entries:
        path = source / entry["file"]
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", str(path))
        task.set_editor_property("destination_path", "/Game/Audio")
        task.set_editor_property("destination_name", path.stem)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("replace_existing_settings", True)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", True)
        tasks.append(task)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)

    receipt = {"version": manifest["version"], "expected_count": len(entries), "assets": []}
    for entry, task in zip(entries, tasks):
        asset_path = "/Game/Audio/" + Path(entry["file"]).stem
        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not isinstance(asset, unreal.SoundWave) or not task.get_editor_property("imported_object_paths"):
            raise RuntimeError("Audio import failed: " + asset_path)
        asset.set_editor_property("volume", 1.0)
        asset.set_editor_property("looping", False)
        asset.set_editor_property("compression_quality", 85)
        # Small one-shots stay resident; the first hit should not wait for disk streaming.
        asset.set_editor_property("loading_behavior", unreal.SoundWaveLoadingBehavior.RETAIN_ON_LOAD)
        duration = float(asset.get_editor_property("duration"))
        channels = int(asset.get_editor_property("num_channels"))
        if abs(duration - entry["duration"]) > .002 or channels != 1:
            raise RuntimeError("Imported audio metadata mismatch: " + asset_path)
        if not unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=False):
            raise RuntimeError("Could not save: " + asset_path)
        receipt["assets"].append({"path": asset_path, "duration": duration,
                                  "channels": channels, "source_sha256": entry["sha256"]})
    receipt["status"] = "passed"
    report = root / "Saved" / "AudioImportReport.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    unreal.log("CIVWAR_AUDIO_IMPORT_PASSED assets=%d report=%s" % (len(entries), report))


if __name__ == "__main__":
    main()
