"""Launch the reviewed art in a normal, playable standalone match.

Dry run by default. --execute starts one UE process; --smoke-seconds also
enables autoplay/screenshots and collects actual runtime evidence. No paid API,
asset generation, approval changes, or permanent mapping changes occur here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MAP = "RawAssets/Art/Tripo_v01/reviews/environment_inputs_20261020/six_asset_game_review.json"
ENV_IDS = {"Env_BoulderA", "Env_BoulderB", "Env_RockSlab", "Env_Shrub", "Env_Pine", "Env_Broadleaf"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(root, object_path):
    if not isinstance(object_path, str) or not re.fullmatch(r"/Game/ArtPilot/[A-Za-z0-9_/]+\.[A-Za-z0-9_]+", object_path):
        raise ValueError(f"Invalid isolated asset path: {object_path}")
    path = root / "Content" / (object_path.split(".")[0][len("/Game/"):] + ".uasset")
    if not path.is_file():
        raise ValueError(f"Missing imported package: {path}")
    return path


def environment_lineage(root, mapping, permanent):
    expected = mapping.get("permanent_runtime_mapping_sha256")
    if expected == sha(permanent):
        return []
    legacy = root / "Content/Data/EnvironmentArtLegacy.json"
    if not legacy.is_file() or sha(legacy) != expected:
        raise ValueError("Original environment mapping is missing or changed")
    current = read(permanent)
    assets = current.get("assets", {})
    if current.get("default_runtime_enabled") is not True or set(assets) != ENV_IDS | {"Env_GrassClump"}:
        raise ValueError("Default environment scope differs from the reviewed six plus legacy grass")
    for asset_id, reviewed in mapping["assets"].items():
        if any(assets[asset_id].get(key) != value for key, value in reviewed.items()):
            raise ValueError(f"Default environment differs from reviewed source: {asset_id}")
    grass = read(legacy)["assets"]["Env_GrassClump"]
    if any(assets["Env_GrassClump"].get(key) != value for key, value in grass.items()):
        raise ValueError("Unreviewed grass cannot replace the legacy fallback")
    return [legacy]


def preflight(root):
    mapping = read(root / MAP)
    permanent = root / "Content/Data/EnvironmentArt.json"
    if (mapping.get("partial_review_only") is not True
            or mapping.get("hide_deferred_grass") is not True
            or set(mapping.get("assets", {})) != ENV_IDS):
        raise ValueError("Six-asset mapping is invalid or the permanent mapping changed; review it before launching")
    tracked = [permanent, root / MAP, *environment_lineage(root, mapping, permanent)]
    packages = []
    for asset in mapping["assets"].values():
        packages.append(package(root, asset["object_path"]))
        source = Path(asset["source"])
        if not source.is_file() or sha(source) != asset["source_sha256"]:
            raise ValueError(f"Reviewed source missing or changed: {source}")
    unit_path = root / "Content/Data/UnitArtPilot.json"
    unit = read(unit_path)
    if unit.get("asset_id") != "Unit_StoneAxe" or any(unit.get(k) is not True for k in (
            "enabled", "ue_structural_approved", "socket_alignment_approved")):
        raise ValueError("StoneAxe structural/socket pilot approvals are absent")
    for key in ("skeletal_mesh", "weapon_mesh", "team_material"):
        packages.append(package(root, unit[key]))
    for clip in ("Idle", "Move", "Attack", "Hit", "Death"):
        packages.append(package(root, unit["animations"][clip]))
    tracked.append(unit_path)
    flags = ["-cwstoneaxepilot"]
    included = [*sorted(ENV_IDS), "Unit_StoneAxe"]
    deferred = ["Env_GrassClump: geometry review failed; hidden", "Other units/champions/eras: existing prototype visuals"]
    base_path = root / "Content/Data/BaseArtPilot.json"
    base = read(base_path)
    turret_path = root / "Content/Data/TurretArtPilot.json"
    turret = read(turret_path)
    tracked.extend([base_path, turret_path])
    base_ready = base.get("asset_id") == "Base_Stone" and all(base.get(k) is True for k in (
        "enabled", "ue_structural_approved", "placement_approved_for_pilot"))
    # The runtime deliberately refuses the whole base if its configured faction
    # material is unapproved. Never bypass that by deleting the material field.
    base_ready = base_ready and (not base.get("team_material") or base.get("team_material_approved_for_pilot") is True)
    if base_ready:
        packages.append(package(root, base["static_mesh"]))
        if base.get("team_material"):
            packages.append(package(root, base["team_material"]))
        flags.append("-cwbasestonepilot")
        included.append("Base_Stone")
        if turret.get("asset_id") == "Turret_RockTower" and all(turret.get(k) is True for k in (
                "enabled", "ue_structural_approved", "assembly_approved_for_pilot")):
            packages.extend(package(root, p) for p in turret["meshes"].values())
            flags.append("-cwrocktowerpilot")
            included.append("Turret_RockTower")
        else:
            deferred.append("Turret_RockTower: assembly pilot approval absent")
    else:
        deferred.append("Base_Stone / Turret_RockTower: base faction-material review remains failed; original prototypes retained")
    return {"included": included, "deferred": deferred, "flags": flags,
            "protected_files": {str(p): sha(p) for p in tracked},
            "package_count": len(set(packages)), "production_approved": False}


def heavy_processes():
    result = subprocess.run(["powershell", "-NoProfile", "-Command",
        "@(Get-Process UnrealEditor,UnrealEditor-Cmd,blender -ErrorAction SilentlyContinue) | ForEach-Object { $_.Id }"],
        capture_output=True, text=True, check=True)
    return result.stdout.split()


def summarize(log, state, screenshots, returncode, timed_out):
    failures = []
    if returncode != 0 or timed_out:
        failures.append(f"Engine exit={returncode}, timed_out={timed_out}")
    if "CIVWAR_ART_PREVIEW environment_meshes=6 camera=player" not in log:
        failures.append("Interactive six-asset preview did not activate")
    if "CIVWAR_STONEAXE_PILOT mesh=" not in log:
        failures.append("No actual skeletal StoneAxe spawned")
    if "CIVWAR_ART_REVIEW shot=" in log:
        failures.append("Automated art-review camera unexpectedly activated")
    if "Base_Stone" in state["included"]:
        for team in (0, 1):
            if f"CIVWAR_BASE_STONE_PILOT team={team}" not in log:
                failures.append(f"Base pilot absent for team {team}")
    if not screenshots:
        failures.append("No actual screenshot was captured")
    for p, expected in state["protected_files"].items():
        if not Path(p).is_file() or sha(Path(p)) != expected:
            failures.append(f"Configuration changed during run: {p}")
    errors = [line for line in log.splitlines() if re.search(r"\bFatal error:|\bAssertion failed:|\bEnsure condition failed:", line)]
    failures.extend(errors[:10])
    perf = re.findall(r"CIVWAR_PERF[^\r\n]*", log)
    return {"failures": failures, "runtime_smoke_passed": not failures,
            "perf_samples": perf, "screenshots": screenshots,
            "result_lines": re.findall(r"CIVWAR_RESULT[^\r\n]*", log),
            "manual_input_tested": False, "network_tested": False,
            "full_match_verified": bool(re.search(r"CIVWAR_RESULT", log)),
            "production_approved": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--smoke-seconds", type=int, default=0)
    parser.add_argument("--engine-root", type=Path, default=Path(os.environ.get("UE_ROOT", "G:/epic/UE_5.8")))
    args = parser.parse_args()
    if args.smoke_seconds and not 60 <= args.smoke_seconds <= 1200:
        parser.error("--smoke-seconds must be 60..1200")
    root = Path("F:/code/CivWar") if ROOT.name != "CivWar" else ROOT
    if not root.is_dir() or not root.samefile(ROOT):
        raise ValueError("The English UE junction must point to this project")
    state = preflight(ROOT)
    editor = args.engine_root / "Engine/Binaries/Win64/UnrealEditor.exe"
    if not editor.is_file():
        raise ValueError(f"Unreal editor not found: {editor}")
    binary = root / "Binaries/Win64/UnrealEditor-CivWar.dll"
    newer = [p for p in (ROOT / "Source").rglob("*") if p.suffix in (".cpp", ".h") and (not binary.exists() or p.stat().st_mtime > binary.stat().st_mtime)]
    if newer:
        raise ValueError("Rebuild CivWarEditor before previewing: newer source files detected")
    run = "ArtPreview_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    out = root / "RawAssets/Art/Tripo_v01/reviews" / run
    command = [str(editor), str(root / "CivWar.uproject"), "-game", "-windowed", "-ForceRes", "-ResX=1600", "-ResY=900",
               "-nosplash", "-nop4", "-noshaderworker", "-DDC=InstalledNoZenLocalFallback",
               "-cwsingle=0", "-cwautoready", "-cwartpreview", f"-cwartenvironment={MAP}",
               "-cwperf", "-ExecCmds=t.MaxFPS 30", f"-abslog={out / 'game.log'}", *state["flags"]]
    if args.smoke_seconds:
        command += ["-RenderOffscreen", "-unattended", "-nosound", "-cwautoplay", "-cwshots",
                    f"-cwshotprefix={run}", f"-cwquitafter={args.smoke_seconds}", "-cwexitonend"]
    state.update({"run": run, "command": command, "smoke_seconds": args.smoke_seconds,
                  "output": str(out), "mode": "smoke" if args.smoke_seconds else "interactive"})
    print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)
    if not args.execute:
        return 0
    if heavy_processes():
        raise ValueError("Another UE or Blender process owns the heavy-work slot")
    out.mkdir(parents=True, exist_ok=False)
    (out / "launch.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    # Lower priority at creation; apply the CPU cap immediately after launch.
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
    print(f"Started PID={process.pid}; single UE, four logical CPUs, 30 FPS", flush=True)
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
    if args.smoke_seconds:
        log_path = out / "game.log"
        log = log_path.read_text(encoding="utf-8-sig", errors="replace") if log_path.exists() else ""
        shots = [{"path": str(p), "sha256": sha(p)} for p in sorted((ROOT / "Saved/Screenshots").rglob(run + "_*.png"))]
        report = summarize(log, state, shots, process.returncode, timed_out)
        report.update({"run": run, "pid": process.pid, "exit_code": process.returncode,
                       "log": str(log_path), "finished_at_utc": datetime.now(timezone.utc).isoformat()})
        report_path = out / "smoke_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report: {report_path}\nFailures: {report['failures']}", flush=True)
        return int(bool(report["failures"]))
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
