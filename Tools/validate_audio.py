"""Verify shipped audio, event coverage, amplitude headroom, variants and reproducibility.

python Tools/validate_audio.py [--reproduce] [--report path.json]
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import tempfile
import wave

import gen_sfx

ROOT = Path(__file__).resolve().parents[1]


def validate(reproduce=False):
    source = ROOT / "RawAssets" / "Audio"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    profiles = re.findall(r'\{TEXT\("(\w+)"\), EChannel::',
                          (ROOT / "Source/CivWar/View/CWAudio.cpp").read_text(encoding="utf-8"))
    expected = [spec[0] for spec in gen_sfx.SPECS]
    errors, results, event_hashes = [], [], {}
    if profiles != expected:
        errors.append("C++ runtime event profiles differ from generator order")
    expected_files = {"SFX_" + name + ("" if variant == 0 else "_V%02d" % (variant + 1)) + ".wav"
                      for name, _, variants, _, _ in gen_sfx.SPECS for variant in range(variants)}
    actual_files = {entry["file"] for entry in manifest["assets"]}
    if actual_files != expected_files or len(manifest["assets"]) != len(expected_files):
        errors.append("Manifest is missing or duplicates runtime sound/variant files")
    for entry in manifest["assets"]:
        path = source / entry["file"]
        if not path.is_file():
            errors.append("Missing WAV: " + path.name)
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            errors.append("Hash changed: " + path.name)
        hashes = event_hashes.setdefault(entry["event"], set())
        if digest in hashes:
            errors.append("Duplicate variation: " + path.name)
        hashes.add(digest)
        with wave.open(str(path), "rb") as stream:
            if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth(), stream.getcomptype()) != (48000, 1, 2, "NONE"):
                errors.append("Wrong PCM format: " + path.name)
            frames = stream.readframes(stream.getnframes())
            pcm = struct.unpack("<%dh" % (len(frames) // 2), frames)
        samples = [x / 32767 for x in pcm]
        stats = gen_sfx.metrics(samples)
        if not .04 <= stats["duration"] <= 3:
            errors.append("Unexpected duration: " + path.name)
        if abs(stats["duration"] - entry["duration"]) > 1 / gen_sfx.SR:
            errors.append("Duration drift: " + path.name)
        if stats["peak_dbfs"] > entry["peak_ceiling_dbfs"] + .015:
            errors.append("Peak headroom exceeded: " + path.name)
        if stats["rms_dbfs"] > entry["rms_ceiling_dbfs"] + .015 or stats["rms_dbfs"] < -45:
            errors.append("RMS outside design range: " + path.name)
        if abs(stats["dc"]) > .001 or pcm[0] != 0 or pcm[-1] != 0:
            errors.append("DC/click discontinuity: " + path.name)
        if max(abs(x) for x in pcm) >= 32760:
            errors.append("Clipping: " + path.name)
        results.append({"file": path.name, **stats})
    if reproduce:
        with tempfile.TemporaryDirectory(prefix="civwar_audio_check_") as folder:
            rebuilt = gen_sfx.generate(folder)
            if [(e["file"], e["sha256"]) for e in rebuilt["assets"]] != [(e["file"], e["sha256"]) for e in manifest["assets"]]:
                errors.append("Regeneration is not byte-identical")
    return {"status": "passed" if not errors else "failed", "events": len(expected),
            "wav_count": len(results), "reproduction_checked": reproduce,
            "errors": errors, "assets": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reproduce", action="store_true")
    parser.add_argument("--report", type=Path, default=ROOT / "reviews/Audio_20261021/validation.json")
    args = parser.parse_args()
    result = validate(args.reproduce)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "assets"}, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
