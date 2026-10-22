"""Import only manifest-listed approved epic music and third-party one-shots.

Run from UnrealEditor-Cmd with -run=pythonscript
-script=F:/code/CivWar/Tools/Unreal/import_epic_audio.py -unattended -nop4
-nosplash -DDC=InstalledNoZenLocalFallback. Root coordinates engine lifetime.
"""
import hashlib
import json
from pathlib import Path
import wave
import unreal


def main():
    root = Path(unreal.Paths.project_dir()).resolve()
    receipt = {"version": 1, "status": "pending", "assets": []}
    report = root / "Saved/EpicAudioImportReport.json"
    entries = []
    for folder, prefix, channels in [("RawAssets/Music", "MUS_", 2), ("RawAssets/Audio/ThirdParty", "TPSFX_", 1)]:
        directory = root / folder
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["assets"]:
            source = (directory / entry["file"]).resolve()
            if source.parent != directory.resolve() or not source.name.startswith(prefix) or source.suffix != ".wav":
                raise RuntimeError("Unsafe manifest path: " + str(source))
            if hashlib.sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
                raise RuntimeError("Source hash differs: " + str(source))
            with wave.open(str(source), "rb") as stream:
                if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (48000, channels, 2):
                    raise RuntimeError("Source must be 48 kHz PCM16 with expected channel count: " + str(source))
            expected_asset = ("/Game/Audio/Music/" if channels == 2 else "/Game/Audio/ThirdParty/") + source.stem
            if entry["asset"] != expected_asset:
                raise RuntimeError("Unexpected import destination: " + entry["asset"])
            entries.append((entry, source, channels == 2))
    receipt["expected_count"] = len(entries)
    try:
        tasks = []
        for entry, source, is_music in entries:
            task = unreal.AssetImportTask()
            task.set_editor_property("filename", str(source))
            task.set_editor_property("destination_path", entry["asset"].rsplit("/", 1)[0])
            task.set_editor_property("destination_name", source.stem)
            task.set_editor_property("replace_existing", True)
            task.set_editor_property("replace_existing_settings", True)
            task.set_editor_property("automated", True)
            task.set_editor_property("save", True)
            tasks.append(task)
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
        for (entry, source, is_music), task in zip(entries, tasks):
            path = entry["asset"]
            asset = unreal.EditorAssetLibrary.load_asset(path)
            if not isinstance(asset, unreal.SoundWave) or not task.get_editor_property("imported_object_paths"):
                raise RuntimeError("Import failed: " + path)
            asset.set_editor_property("volume", 1.0)
            asset.set_editor_property("looping", is_music)
            asset.set_editor_property("compression_quality", 85 if is_music else 90)
            behavior = unreal.SoundWaveLoadingBehavior.PRIME_ON_LOAD if is_music else unreal.SoundWaveLoadingBehavior.RETAIN_ON_LOAD
            asset.set_editor_property("loading_behavior", behavior)
            if is_music:
                asset.set_editor_property("sound_group", unreal.SoundGroup.SOUNDGROUP_MUSIC)
                asset.set_editor_property("virtualization_mode", unreal.VirtualizationMode.PLAY_WHEN_SILENT)
            duration = float(asset.get_editor_property("duration"))
            channels = int(asset.get_editor_property("num_channels"))
            if abs(duration-entry["duration"]) > .003 or channels != entry["channels"]:
                raise RuntimeError("Imported metadata mismatch: " + path)
            if bool(asset.get_editor_property("looping")) != is_music or asset.get_editor_property("loading_behavior") != behavior:
                raise RuntimeError("Imported playback settings mismatch: " + path)
            if not unreal.EditorAssetLibrary.save_asset(path, only_if_is_dirty=False):
                raise RuntimeError("Save failed: " + path)
            receipt["assets"].append({"path":path, "source_sha256":entry["sha256"], "duration":duration, "channels":channels, "looping":is_music, "loading_behavior":str(behavior), "sound_group":str(asset.get_editor_property("sound_group")), "virtualization_mode":str(asset.get_editor_property("virtualization_mode"))})
        receipt["status"] = "passed"
        unreal.log("CIVWAR_EPIC_AUDIO_IMPORT_PASSED assets=%d report=%s" % (len(entries), report))
    except Exception as error:
        receipt["status"] = "failed"
        receipt["error"] = str(error)
        raise
    finally:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
