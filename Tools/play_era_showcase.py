"""Launch a chosen era with the same default assets used by the normal game."""
from __future__ import annotations
import argparse
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess

import play_art_preview as existing
from apply_era_art_handoff import asset_paths

ROOT = Path(__file__).resolve().parents[1]
LABELS = ("石器时代", "中世纪", "工业时代", "现代战争", "未来科技")


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def preflight(age):
    if age == 0:
        from play_stone_era_preview import preflight as stone_preflight
        result = stone_preflight(ROOT)
        return {"age": age, "name": LABELS[age], "assets": result["included"], "missing": []}
    mapping = read(ROOT / "Content/Data/EraArt.json")["assets"]
    required = [
        row["VisualKey"]
        for name in ("Ages", "Units", "Turrets", "Champions")
        for row in read(ROOT / f"Content/Data/{name}.json")
        if row.get("Age", row.get("Index", 0)) == age
    ]
    missing = []
    for key in required:
        entry = mapping.get(key)
        if not entry or not entry.get("enabled") or not entry.get("default_runtime_enabled"):
            missing.append(key)
            continue
        if any(not (ROOT / "Content" / (path.split(".", 1)[0][6:] + ".uasset")).is_file()
               for path in asset_paths(entry)):
            missing.append(key)
    return {"age": age, "name": LABELS[age], "assets": required, "missing": missing}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--age", type=int, choices=range(5), default=0)
    parser.add_argument("--menu", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    age = args.age
    if args.menu:
        print("选择要体验的时代：")
        for index, label in enumerate(LABELS):
            state = preflight(index)
            print(f"  {index + 1}. {label}" + ("（制作中）" if state["missing"] else ""))
        selection = input("输入 1—5，回车启动：").strip()
        if selection not in {"1", "2", "3", "4", "5"}:
            print("未选择时代。")
            return 0
        age = int(selection) - 1
    state = preflight(age)
    if state["missing"]:
        if args.menu:
            print("这个时代还在制作中，暂时不能启动整套展示。")
        else:
            print(json.dumps(state, ensure_ascii=False, indent=2))
        return 1
    root = Path("F:/code/CivWar")
    if not root.is_dir() or not root.samefile(ROOT):
        raise ValueError("The English project junction must point to this project")
    engine = Path(os.environ.get("UE_ROOT", "G:/epic/UE_5.8"))
    editor = engine / "Engine/Binaries/Win64/UnrealEditor.exe"
    binary = root / "Binaries/Win64/UnrealEditor-CivWar.dll"
    if not editor.is_file() or not binary.is_file():
        raise ValueError("Build CivWarEditor before launching")
    if any(path.stat().st_mtime > binary.stat().st_mtime for path in (ROOT / "Source").rglob("*")
           if path.suffix in {".cpp", ".h"}):
        raise ValueError("Build the changed source before launching")
    run = "EraShowcase_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    fixture = "-cwstoneerafixture" if age == 0 else f"-cwerafixture={age}"
    command = [
        str(editor), str(root / "CivWar.uproject"),
        "-game", "-windowed", "-ForceRes", "-ResX=1600", "-ResY=900",
        "-nosplash", "-nop4", "-noshaderworker", "-DDC=InstalledNoZenLocalFallback",
        "-cwsingle=0", "-cwautoready", fixture, "-ExecCmds=t.MaxFPS 60",
        f"-abslog={root / 'Saved/Logs' / (run + '.log')}",
    ]
    if not (args.execute or args.menu):
        print(json.dumps({**state, "command": command, "fps_cap": 60, "asset_enablement_flags": []},
                         ensure_ascii=False, indent=2))
        return 0
    if existing.heavy_processes():
        print("请先保存并关闭正在运行的游戏、UE 编辑器或 Blender。")
        return 1
    print(f"正在进入{LABELS[age]}。双方已配置部队和炮塔，可以继续训练和操作。")
    print("A/D 移动镜头，滚轮缩放，C 查看统帅，1/2/3 训练兵种。")
    process = subprocess.Popen(command, cwd=root, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    if not kernel.SetProcessAffinityMask(int(process._handle), 15):
        process.terminate()
        process.wait()
        raise OSError(ctypes.get_last_error(), "Could not set the game CPU limit")
    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
