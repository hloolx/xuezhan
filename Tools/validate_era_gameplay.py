"""Check one real default-art era match against its gameplay data tables."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import validate_stone_era_timing as timing

ROOT = Path(__file__).resolve().parents[1]


def table(name):
    return json.loads((ROOT / f"Content/Data/{name}.json").read_text(encoding="utf-8-sig"))


def validate_motion(rows):
    failures = []
    if not rows:
        return ["No actual continuous movement sample"]
    if any(not re.search(r"\bstopped_frames=0\b", row) for row in rows):
        failures.append("Continuous movement contained stopped render frames")
    for row in rows:
        values = dict(re.findall(r"(\w+)=([^\s]+)", row))
        if "sample_policy" not in values:  # Preserve historical report semantics.
            continue
        if values["sample_policy"] != "bounded_start_v1" or values.get("status") != "complete":
            failures.append("Movement startup failed or unsupported sample policy: " + row)
            continue
        try:
            duration, startup, frame, limit, buffer = (
                float(values[key]) for key in (
                    "duration", "startup_seconds", "startup_frame_seconds",
                    "startup_limit_seconds", "buffer_seconds")
            )
            if not all(math.isfinite(value) for value in (duration, startup, frame, limit, buffer)):
                raise ValueError("Non-finite motion diagnostic")
            # Startup fields have six decimal places; allow only their rounding error.
            if duration < 2.0 or startup < 0 or frame <= 0:
                raise ValueError("Incomplete duration or invalid startup measurement")
            if abs(buffer - 0.100) > 0.000001 or abs(limit - (buffer + frame)) > 0.000002:
                raise ValueError("Startup bound differs from buffer plus one frame")
            if startup > limit + 0.000002:
                raise ValueError("Startup exceeded its bounded delay")
        except (KeyError, ValueError) as error:
            failures.append(f"Invalid bounded movement sample ({error}): {row}")
    return failures


def inspect(directory: Path, age: int):
    text = (directory / "game.log").read_text(encoding="utf-8-sig", errors="replace")
    expected = {
        "base": [row["VisualKey"] for row in table("Ages") if row["Index"] == age],
        "turrets": [row["VisualKey"] for row in table("Turrets") if row["Age"] == age],
        "units": [row["VisualKey"] for row in table("Units") if row["Age"] == age],
        "champions": [row["VisualKey"] for row in table("Champions") if row["Age"] == age],
    }
    failures = []
    for pattern in ("Fatal error:", "Assertion failed:", "Ensure condition failed:",
                    "missing usage flag", "Default Material will be used"):
        if pattern in text:
            failures.append("Runtime error: " + pattern)
    for team in (0, 1):
        if not re.search(rf"CIVWAR_ERA_FIXTURE_READY team={team} age={age} ", text):
            failures.append(f"Real upgrade/training fixture absent: team={team}, age={age}")
        for keys in expected.values():
            for key in keys:
                if not re.search(r"CIVWAR_ERA_ART [^\r\n]*asset=" + re.escape(key) + rf" team={team} ", text):
                    failures.append(f"Default imported asset not observed: {key}, team={team}")
    motion = re.findall(r"CIVWAR_UNIT_MOTION [^\r\n]*", text)
    failures.extend(validate_motion(motion))
    windups = {row["VisualKey"]: float(row["AttackWindup"])
               for name in ("Units", "Champions") for row in table(name)}
    attack = timing.analyze(text, windups)
    failures.extend(attack["failures"])
    if not attack["records"]:
        failures.append("No actual attack timing records")
    poses = re.findall(r"CIVWAR_UNIT_POSE[^\r\n]*", text)
    deaths = [row for row in poses if "to=Death " in row]
    shots = sorted((ROOT / "Saved/Screenshots").rglob(directory.name + "_*.png"))
    if not shots:
        failures.append("No actual game screenshot")
    report = {
        "age": age, "expected_assets": expected, "failures": failures,
        "continuous_movement": motion, "death_transitions": deaths,
        "attack_timing": attack,
        "loaded_era_assets": sorted(set(re.findall(r"CIVWAR_ERA_ART[^\r\n]*", text))),
        "screenshots": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in shots],
        "actual_visual_inspection": "pending",
        "normal_default_assets": True,
        "fixture": "Explicit editor standalone setup using real upgrade, training, turret commands",
    }
    (directory / "gameplay_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"age": age, "failures": failures, "movement_samples": len(motion),
                      "deaths": len(deaths), "attack_records": attack["records"], "screenshots": len(shots)}, ensure_ascii=False))
    return int(bool(failures))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--age", required=True, type=int, choices=range(1, 5))
    args = parser.parse_args()
    sys.exit(inspect(args.directory.resolve(), args.age))
