"""Audit actual RockTower component samples without claiming network or damage coverage."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import sys


sys.path.insert(0, str(Path(__file__).resolve().parent / "Blender"))
from build_rock_tower import sample_cycle


RELEASE = re.compile(r"CIVWAR_ROCK_TOWER_RELEASE team=(\d+) slot=(\d+) seq=(\d+) pitch=([-\d.]+) stone_visible=([01])")
POSE = re.compile(r"CIVWAR_ROCK_TOWER_POSE team=(\d+) slot=(\d+) seq=(\d+) elapsed=([-\d.]+) pitch=([-\d.]+) stone_visible=([01]).*?scale=X=([-\d.]+) Y=([-\d.]+) Z=([-\d.]+)")
BUILD = re.compile(r"CIVWAR_ROCK_TOWER_PILOT team=(\d+) slot=(\d+) components=(\d+)")
FIXTURE = re.compile(r"CIVWAR_ROCK_TOWER_FIXTURE team=(\d+) slot=(\d+) result=(\d+)")
GOLD = re.compile(r"CIVWAR_ROCK_TOWER_FIXTURE_GOLD team=(\d+) before=([-\d.]+) after=([-\d.]+)")
AUTHORITY = re.compile(r"CIVWAR_ROCK_TOWER_AUTHORITY team=(\d+) slot=(\d+) seq=(\d+) sim_time=([-\d.]+) target=(-?\d+) target_x=([-\d.]+)")
IMAGE = re.compile(r"CIVWAR_ROCK_TOWER_IMAGE shot=(\S+) team=(\d+) slot=(\d+) seq=(\d+) phase=(\d+) elapsed=([-\d.]+) pitch=([-\d.]+) stone_visible=([01])")


def audit(text, require_fixture=True):
    failures, releases, samples, active = [], [], [], {}
    build_records = [(int(team), int(slot), int(count)) for team, slot, count in BUILD.findall(text)]
    builds = {(team, slot) for team, slot, count in build_records if count == 5}
    fixtures = {(int(team), int(slot)) for team, slot, result in FIXTURE.findall(text) if int(result) == 0}
    required = {(team, slot) for team in (0, 1) for slot in (0, 1, 2)}
    fixture_line_count = sum("CIVWAR_ROCK_TOWER_FIXTURE" in line for line in text.splitlines())
    if any((team, slot) not in required or count != 5 for team, slot, count in build_records):
        failures.append("Invalid actual built tower team, slot or component count")
    gold = {int(team): (float(before), float(after)) for team, before, after in GOLD.findall(text)}
    if require_fixture:
        if builds != required or fixtures != required:
            failures.append("Six actual components/normal-command fixture records are required")
        if set(gold) != {0, 1} or any(not all(math.isfinite(value) for value in (before, after)) or abs(before - after) > .001 for before, after in gold.values()):
            failures.append("Fixture changed remaining gold or omitted actual gold evidence")
    else:
        if fixture_line_count:
            failures.append("Natural-build audit rejects every fixture or fixture-gold line")
        if not builds:
            failures.append("Natural-build audit requires at least one actual built tower")
    phases = Counter()
    authority_expected = not require_fixture or "CIVWAR_ROCK_TOWER_AUTHORITY " in text
    authority, release_keys = Counter(), Counter()
    image_records, last_poses, built_seen = [], {}, set()
    for line in text.splitlines():
        build = BUILD.search(line)
        if build and int(build[3]) == 5:
            built_seen.add((int(build[1]), int(build[2])))
        shot = IMAGE.search(line)
        if shot:
            key = tuple(map(int, shot.groups()[1:4]))
            phase = int(shot[5])
            values = (float(shot[6]), float(shot[7]), bool(int(shot[8])))
            previous_pose = last_poses.get(key)
            if previous_pose is None or abs(previous_pose[0] - values[0]) > .000002 or abs(previous_pose[1] - values[1]) > .001 or previous_pose[2] != values[2]:
                failures.append("Image telemetry has no matching actual evaluated component sample")
            expected_phase = 5 if values[0] >= 2.099998 else 4 if values[0] >= 1.2 else 3 if values[0] >= .95 else 2 if values[0] >= .3 else 1 if values[0] >= .16 else 0
            if phase != expected_phase or any(record["key"] == key and record["phase"] == phase for record in image_records):
                failures.append("Image phase is invalid or repeated")
            image_records.append({"shot": shot[1], "key": key, "phase": phase, "elapsed": values[0], "pitch": values[1], "stone_visible": values[2]})
        event = AUTHORITY.search(line)
        if event:
            key = tuple(map(int, event.groups()[:3]))
            if not all(math.isfinite(float(event[index])) for index in (4, 6)) or key[:2] not in required:
                failures.append("Invalid actual authority event")
            if not require_fixture and key[:2] not in builds:
                failures.append("Authority event does not belong to an actual built tower")
            authority[key] += 1
        release = RELEASE.search(line)
        if release:
            team, slot, sequence = map(int, release.groups()[:3])
            pitch, visible = float(release[4]), bool(int(release[5]))
            if (team, slot) not in built_seen:
                failures.append("Visual release does not belong to a preceding actual built tower")
            if abs(pitch - 35) > .001 or visible:
                failures.append("Release did not use ready pitch and hidden stone")
            active[(team, slot)] = (sequence, 0.0)
            key = (team, slot, sequence)
            release_keys[key] += 1
            if authority_expected and release_keys[key] > authority[key]:
                failures.append("Visual release has no preceding authority event")
            releases.append({"team": team, "slot": slot, "sequence": sequence, "pitch": pitch, "stone_visible": visible})
            phases["release"] += 1
        pose = POSE.search(line)
        if not pose:
            continue
        team, slot, sequence = map(int, pose.groups()[:3])
        if (team, slot) not in built_seen:
            failures.append("Component pose does not belong to a preceding actual built tower")
        elapsed, pitch = float(pose[4]), float(pose[5])
        visible, scale = bool(int(pose[6])), list(map(float, pose.groups()[6:]))
        last_poses[(team, slot, sequence)] = (elapsed, pitch, visible)
        previous = active.get((team, slot))
        if previous is None or previous[0] != sequence or elapsed + .000002 < previous[1]:
            failures.append("Pose has no matching release or reverses elapsed time")
        active[(team, slot)] = (sequence, elapsed)
        if not all(math.isfinite(value) for value in (elapsed, pitch, *scale)) or not 0 <= elapsed <= 2.100002:
            failures.append("Nonfinite or out-of-cycle component sample")
            continue
        expected = sample_cycle(elapsed)
        pitch_error = abs(pitch + expected["angle_degrees"])
        if pitch_error > .001 or any(abs(value - 1) > .001 for value in scale):
            failures.append("Actual pitch/positive scale differs from physical cycle")
        if abs(elapsed - 1.2) > .000002 and visible != expected["stone_visible"]:
            failures.append("Actual loaded-stone visibility differs from cycle")
        phase = "ready" if elapsed >= 2.099998 else "return_to_ready" if elapsed >= 1.3 else "loaded_reload" if elapsed >= 1.2 else "empty_reload" if elapsed >= .95 else "return" if elapsed >= .3 else "followthrough_hold" if elapsed >= .16 else "followthrough"
        phases[phase] += 1
        samples.append({"team": team, "slot": slot, "sequence": sequence, "elapsed": elapsed, "pitch_error": pitch_error, "phase": phase})
    for prefix, pattern in (("CIVWAR_ROCK_TOWER_PILOT ", BUILD), ("CIVWAR_ROCK_TOWER_FIXTURE ", FIXTURE), ("CIVWAR_ROCK_TOWER_FIXTURE_GOLD ", GOLD), ("CIVWAR_ROCK_TOWER_RELEASE ", RELEASE), ("CIVWAR_ROCK_TOWER_POSE ", POSE), ("CIVWAR_ROCK_TOWER_AUTHORITY ", AUTHORITY), ("CIVWAR_ROCK_TOWER_IMAGE ", IMAGE)):
        if sum(prefix in line for line in text.splitlines()) != len(pattern.findall(text)):
            failures.append("Malformed actual component telemetry")
    if authority_expected and authority != release_keys:
        failures.append("Authority and visual release multiplicities differ")
    return {"status": "failed" if failures else "local_component_samples_passed" if samples else "assembly_only_no_fire_samples",
            "audit_mode": "six_tower_fixture" if require_fixture else "natural_build",
            "require_fixture": require_fixture, "fixture_line_count": fixture_line_count,
            "fixture_record_count": len(FIXTURE.findall(text)),
            "failures": failures, "built_team_slots": sorted(builds), "gold_before_after": gold,
            "release_count": len(releases), "sample_count": len(samples), "phases": dict(phases),
            "release_team_slots": sorted({(record["team"], record["slot"]) for record in releases}),
            "maximum_pitch_error_degrees": max((record["pitch_error"] for record in samples), default=None),
            "local_sample_validation_passed": bool(samples) and not failures,
            "both_team_cycles_observed": {record["team"] for record in samples} == {0, 1},
            "authority_event_count": sum(authority.values()),
            "image_component_records": image_records,
            "authority_event_correlation_verified": bool(authority) and authority == release_keys and not failures,
            "network_timing_approved": False,
            "production_approved": False,
            "scope": ("Strict six-tower fixture with gold conservation. " if require_fixture else "Naturally built actual towers only; zero fixture lines required and every visual release requires preceding read-only authority evidence. ") + "Local component samples and read-only standalone event/image-request correlation; not damage-impact timing, actual image quality, network transport or full-load performance approval."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--natural-build", action="store_true", help="Audit naturally built towers; reject fixture evidence and require authority for any release")
    args = parser.parse_args()
    report = audit(args.log.read_text(encoding="utf-8-sig", errors="replace"), require_fixture=not args.natural_build)
    report["log"] = str(args.log.resolve())
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(report, ensure_ascii=False))
    if report["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
