"""Open the full stone-era art fixture in a playable standalone game.

Dry run by default. --execute opens the game; --smoke-seconds captures an
offscreen review. All three new character assemblies are required unless
--allow-incomplete explicitly requests a diagnostic run.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

import play_art_preview as base
import stone_era_art as stone

ROOT = Path(__file__).resolve().parents[1]


def preflight(root=ROOT, allow_incomplete=False):
    existing = base.preflight(root)
    extension = stone.preflight(root, require_complete=not allow_incomplete)
    if extension["failures"]:
        raise ValueError("; ".join(extension["failures"]))
    required = {"Unit_StoneAxe", "Base_Stone", "Turret_RockTower"}
    if not required.issubset(existing["included"]):
        raise ValueError("Reviewed StoneAxe, base and RockTower must remain available")
    tracked = existing["protected_files"]
    for relative in ("Content/Data/StoneEraArt.json", "Content/Data/Units.json", "Content/Data/Champions.json"):
        path = root / relative
        tracked[str(path)] = base.sha(path)
    return {
        "included": existing["included"] + extension["included"],
        "deferred": extension["deferred"],
        "protected_files": tracked,
        "flags": existing["flags"] + extension["flags"] + ["-cwstoneerafixture"],
        "complete_era": extension["complete_extension_ready"],
        "diagnostic_partial_run": allow_incomplete,
        "package_count": existing["package_count"] + extension["package_count"],
        "production_approved": False,
    }


def summarize(log, state, screenshots, returncode, timed_out):
    report = base.summarize(log, state, screenshots, returncode, timed_out)
    if state.get("camera_review") == "units":
        # The normal launcher deliberately rejects automatic review cameras.
        # This explicit diagnostic accepts only its own six tracked-unit shots.
        report["failures"] = [failure for failure in report["failures"]
                              if failure != "Automated art-review camera unexpectedly activated"]
        expected = {f"{state['run']}_team{team}_distance{distance}.png": (team, distance)
                    for team in (0, 1) for distance in (1300, 2300, 3400)}
        camera_rows = re.findall(r"CIVWAR_ART_REVIEW shot=(\S+) team=(\d+) distance=(\d+)\b", log)
        unit_rows = re.findall(r"CIVWAR_UNIT_ART_REVIEW shot=(\S+) id=(\d+) unit_team=(\d+)\b", log)
        if (len(camera_rows) != 6 or {row[0] for row in camera_rows} != set(expected) or
                any(expected.get(name) != (int(team), int(distance)) for name, team, distance in camera_rows)):
            report["failures"].append("Expected both-team 1300/2300/3400 review-camera evidence is incomplete or unexpected")
        if (len(unit_rows) != 6 or {row[0] for row in unit_rows} != set(expected) or
                any(name not in expected or expected[name][0] != int(team) for name, _, team in unit_rows)):
            report["failures"].append("Each review camera must actually track a unit on its stated team")
        actual = {Path(item["path"]).name: item for item in screenshots}
        if len(screenshots) != 6 or set(actual) != set(expected):
            report["failures"].append("Exactly six expected unit-review screenshots are required")
        for name in set(actual) & set(expected):
            path = Path(actual[name]["path"])
            if not path.is_file() or base.sha(path) != actual[name]["sha256"]:
                report["failures"].append("Unit-review screenshot is missing or changed: " + name)
        report["camera_review"] = {"kind": "units", "expected_shots": sorted(expected),
                                   "actual_camera_rows": camera_rows, "tracked_unit_rows": unit_rows,
                                   "visual_content_verified": False}
    for asset_id in stone.ASSETS:
        if asset_id in state["included"]:
            for team in (0, 1):
                if not re.search(rf"CIVWAR_STONE_ERA_ART asset={asset_id} team={team}\b", log):
                    report["failures"].append(f"Imported {asset_id} did not spawn on team {team}")
    for team in (0, 1):
        if not re.search(rf"CIVWAR_ROCK_TOWER_PILOT team={team}\b", log):
            report["failures"].append(f"Imported RockTower did not spawn on team {team}")
    if "CIVWAR_STONE_ERA_FIXTURE" not in log:
        report["failures"].append("The explicit stone-era fixture did not execute")
    report["runtime_smoke_passed"] = not report["failures"]
    report["complete_era_observed"] = state["complete_era"] and not report["failures"]
    report["visual_reviewed"] = False
    report["production_approved"] = False
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--smoke-seconds", type=int, default=0)
    parser.add_argument("--camera-review", choices=("units",), help="Diagnostic only: capture both teams at three unit-camera distances")
    parser.add_argument("--engine-root", type=Path, default=Path(os.environ.get("UE_ROOT", "G:/epic/UE_5.8")))
    args = parser.parse_args()
    if args.smoke_seconds and not 60 <= args.smoke_seconds <= 1200:
        parser.error("--smoke-seconds must be 60..1200")
    if args.camera_review and not args.smoke_seconds:
        parser.error("--camera-review requires a bounded --smoke-seconds run")
    root = Path("F:/code/CivWar") if ROOT.name != "CivWar" else ROOT
    if not root.is_dir() or not root.samefile(ROOT):
        raise ValueError("The English UE junction must point to this project")
    state = preflight(ROOT, args.allow_incomplete)
    editor = args.engine_root / "Engine/Binaries/Win64/UnrealEditor.exe"
    if not editor.is_file():
        raise ValueError(f"Unreal editor not found: {editor}")
    binary = root / "Binaries/Win64/UnrealEditor-CivWar.dll"
    needs_build = [p for p in (ROOT / "Source").rglob("*") if p.suffix in (".cpp", ".h") and
                   (not binary.exists() or p.stat().st_mtime > binary.stat().st_mtime)]
    if args.execute and needs_build:
        raise ValueError("Rebuild CivWarEditor before launching changed source")
    run = ("StoneEraUnitReview_" if args.camera_review else "StoneEraPreview_") + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    out = root / "RawAssets/Art/Tripo_v01/reviews" / run
    command = [str(editor), str(root / "CivWar.uproject"), "-game", "-windowed", "-ForceRes", "-ResX=1600", "-ResY=900",
               "-nosplash", "-nop4", "-noshaderworker", "-DDC=InstalledNoZenLocalFallback", "-FORCELOGFLUSH",
               "-cwsingle=0", "-cwautoready", "-cwartpreview", f"-cwartenvironment={base.MAP}",
               "-cwperf", "-cwarttiming", f"-cwarttimingrun={run}", "-ExecCmds=t.MaxFPS 20",
               f"-abslog={out / 'game.log'}", *state["flags"]]
    if args.smoke_seconds:
        command += ["-RenderOffscreen", "-unattended", "-nosound",
                    f"-cwshotprefix={run}", f"-cwquitafter={args.smoke_seconds}", "-cwexitonend"]
        command += ["-cwartreview", "-cwunitartreview"] if args.camera_review else ["-cwshots"]
    state.update(run=run, command=command, output=str(out), smoke_seconds=args.smoke_seconds,
                 camera_review=args.camera_review, source_requires_build=bool(needs_build))
    print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)
    if not args.execute:
        return 0
    if base.heavy_processes():
        raise ValueError("Another UE or Blender process owns the heavy-work slot")
    out.mkdir(parents=True, exist_ok=False)
    (out / "launch.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    startup = subprocess.STARTUPINFO()
    if args.smoke_seconds:
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    process = subprocess.Popen(command, cwd=root, startupinfo=startup, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    if not kernel.SetProcessAffinityMask(int(process._handle), 15):
        process.terminate()
        process.wait()
        raise OSError(ctypes.get_last_error(), "Could not cap UE at four logical CPUs")
    print(f"Started PID={process.pid}; stone-era fixture, four logical CPUs, 20 FPS", flush=True)
    timed_out = False
    try:
        process.wait(timeout=args.smoke_seconds + 120 if args.smoke_seconds else None)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.terminate()
        process.wait(timeout=30)
    except KeyboardInterrupt:
        process.terminate()
        process.wait(timeout=30)
        raise
    if not args.smoke_seconds:
        return process.returncode
    log_path = out / "game.log"
    log = log_path.read_text(encoding="utf-8-sig", errors="replace") if log_path.exists() else ""
    screenshots = [{"path": str(p), "sha256": base.sha(p)} for p in sorted((ROOT / "Saved/Screenshots").rglob(run + "_*.png"))]
    report = summarize(log, state, screenshots, process.returncode, timed_out)
    report.update(run=run, pid=process.pid, exit_code=process.returncode, log=str(log_path))
    (out / "smoke_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(out / "smoke_report.json"), "failures": report["failures"]}, ensure_ascii=False), flush=True)
    return int(bool(report["failures"]))


if __name__ == "__main__":
    raise SystemExit(main())
