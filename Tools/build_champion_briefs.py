"""Build only the supplemental champion briefs. Offline; never submits jobs.

Run with --check to detect stale generated cards without writing any files.
Original catalog.json, its 56 briefs, gameplay data and execution.json are read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ART_PATH = Path("RawAssets/Art/Tripo_v01")
GENERATOR = "Tools/build_champion_briefs.py"
CLIPS = ["idle", "move", "attack", "hit", "death"]
STYLE = """CivWar stylized game asset: substantial broad planes, soft bevels, restrained
detail and a readable silhouette at 20-degree gameplay pitch and 1300/2300/3400 cm.
All humans share 5.5-head proportions with slightly oversized hands and boots.
Earthy umber, warm ivory, cool steel, olive and graphite; matte fur/leather/cloth.
Broad muted cobalt panels are replaceable faction-color regions, not baked lighting.
No text, emblems, micro-noise, glossy plastic, bloom, motion blur or background scene.
Soft even studio light, off-white background, full object with generous empty margins.
"""
BODY_POSE = """One unarmed body with attached clothing and armor. Neutral symmetrical A pose,
arms 35-45 degrees from torso, relaxed separated hands, flat feet naturally apart.
Each hand has one opposed thumb and four distinct fingers, no mitten blobs.
No weapon, shield, mount or loose prop. No hands/clothes or leg/leg fusion.
Keep shoulder, elbow, wrist, hip and knee bending gaps. No baked aura or particles.
Use the exact same pose, materials, proportions and part counts across all views.
"""
REVIEW = """Create one four-view review sheet in a 2x2 grid: FRONT / SUBJECT'S RIGHT above,
BACK / SUBJECT'S LEFT below. No printed labels. Orthographic horizontal cameras;
identical pixels per unit and ground baseline in each panel, wide empty gutters.
The narrower side views retain margins; do not enlarge them. Never mirror a view.
This sheet is for design review only. Each accepted view must be exported separately
and mapped using the project's verified canonical API convention before any upload.
Do not submit this sheet or an action-pose image as a multi-view 3D input.
"""
INTEGRATION = """- 身体空手建模；武器另制。右手武器由 hand_r/weapon_r 对齐 grip_r，只有一个父级。
- 双手武器的左手 IK 跟随 grip_l；盾由左前臂 shield_l 承载，左手对齐背面握把。
- 两阵营旋转模型，不做负缩放或镜像；队色区和象牙白、金属、能量区使用独立遮罩。
- 先交付持械 idle/move/attack/hit/death，原地动作由服务器位置驱动，不重复应用根运动。
- 接触对齐服务端 AttackWindup；下一次起手以 AttackInterval 为准，攻速变化需跟随实时节奏。
- 伤害、溅射与技能状态由服务器决定；客户端通知只驱动表现。死亡、换目标、攻击取消、重生清理残留。
- 技能增益持续时间不是施法动作时长；光环与技能特效单独实现，不能烘在人体纹理或用骨骼事件二次结算。
- UE 先走隔离 ArtPilot；五段动画、武器挂点、队色、双方三档镜头通过后才改运行时映射。
- 卡片尺寸是当前程序模型的名义基准，非图片测量；以最新源码派生值为准，不改变玩法碰撞半径。
"""


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def timing(row):
    interval, windup = row["AttackInterval"], row["AttackWindup"]
    if not 0 <= windup < interval:
        raise ValueError("Invalid champion attack timing: " + row["VisualKey"])
    if row["ProjectileSpeed"] != 0:
        raise ValueError("Champion projectile behavior changed; review melee design: " + row["VisualKey"])
    return {"clock": "authoritative server attack start; synchronize late snapshots and attack-speed modifiers",
            "cycle_seconds": interval, "release_seconds": windup,
            "recovery_budget_seconds": round(interval - windup, 6),
            "release_kind": "melee_contact", "client_notify_causes_damage": False}


def runtime_dimensions(root):
    source = root / "Source/CivWar/View/CWModels.cpp"
    content = source.read_text(encoding="utf-8-sig")
    body = content.split("void BuildChampion(", 1)[1].split("void BuildArmoredCar(", 1)[0]
    scale = re.search(r"const float Scale\s*=\s*([\d.]+)f;", body)
    height = re.search(r"Rig\.Height\s*=\s*([\d.]+)f\s*\*\s*Scale", body)
    if not scale or not height:
        raise ValueError("Champion scale implementation changed; inspect runtime baseline")
    return {"nominal_height_cm": round(float(height[1]) * float(scale[1]), 4),
            "baseline_scale": float(scale[1]), "source_file": source.relative_to(root).as_posix(),
            "source_function": "CWModels::BuildChampion", "measurement_status": "runtime_baseline_not_final_mesh_measurement"}


def outputs(root=ROOT):
    art = root / ART_PATH
    supplement = read(art / "catalog_champions.json")
    original = read(art / "catalog.json")
    champions_path = root / "Content/Data/Champions.json"
    rows = read(champions_path)
    by_key = {row["VisualKey"]: row for row in rows}
    core, support = supplement["core"], supplement["support"]
    assets = core + support
    ids = {asset["id"] for asset in assets}
    original_ids = {a["id"] for group in ("core", "support", "non_tripo") for a in original.get(group, [])}
    if len(ids) != len(assets) or ids & original_ids:
        raise ValueError("Duplicate supplemental IDs or collision with original catalog")
    if len(by_key) != len(rows) or {a["id"] for a in core} != set(by_key):
        raise ValueError("Champion catalog must cover every current gameplay VisualKey exactly once")
    if set(supplement["animation_profiles"]) != set(by_key):
        raise ValueError("Champion animation profiles do not match gameplay VisualKeys")
    for asset in assets:
        if set(asset.get("modules", [])) - (ids | original_ids):
            raise ValueError("Unknown champion equipment dependency: " + asset["id"])
    baseline = runtime_dimensions(root)
    source_hash = digest(champions_path)
    pipeline = read(art / "pipeline.json")
    generated = {}
    for asset in assets:
        aid = asset["id"]
        row = by_key.get(aid)
        route_id = "human_p2" if row else "weapon_dcc"
        route = pipeline["routes"][route_id]
        brief = {**asset, "generated_by": GENERATOR, "display_name": row["DisplayName"] if row else asset["name"],
                 "design_catalog_sha256": digest(art / "catalog_champions.json"),
                 "status": "design_only_reference_required", "production_approved": False,
                 "production_route": {"id": route_id, **route},
                 "review_views": ["front", "right", "back", "left"],
                 "production_target": "unarmed A-pose body; separate equipment" if row else "standalone DCC rigid equipment",
                 "required_clips": CLIPS if row else [], "animation_contract": None,
                 "automatic_submission_allowed": False}
        if row:
            brief["source"] = {"source_file": champions_path.relative_to(root).as_posix(), "sha256": source_hash,
                               "group": "champion", "data": row}
            brief["dimensions"] = {**baseline, "gameplay_radius_unchanged_cm": row["Radius"]}
            brief["animation_contract"] = {**supplement["animation_profiles"][aid],
                "status": "design_only_not_implemented_or_rig_validated", "timing": timing(row),
                "ability": {"name": row["AbilityName"], "buff_duration_seconds": row["AbilityDuration"],
                            "cooldown_seconds": row["AbilityCooldown"], "radius_cm": row["AbilityRadius"],
                            "cast_clip_seconds": None, "cast_clip_requires_runtime_integration": True},
                "aura_radius_cm": row["AuraRadius"], "splash_radius_cm": row["SplashRadius"]}
        else:
            brief["used_by"] = [a["id"] for a in core if aid in a["modules"]]
            brief["dimensions"] = {"status": "fit_to_champion_hand_and_clearance_in_DCC", "exact_size_approved": False}
        folder = ART_PATH / "prompts" / aid
        pose = BODY_POSE if row else "One standalone solid equipment asset, no hand, body, stand or surrounding objects.\n"
        production = STYLE + "\n" + asset["subject"] + "\n\n" + pose
        if row:
            production += f"\nNominal body height {baseline['nominal_height_cm']:g} cm; no ruler or dimensions printed in the image.\n"
        generated[folder / "brief.json"] = json_text(brief)
        generated[folder / "production.txt"] = production
        generated[folder / "reference.txt"] = production + "\n" + REVIEW
        detail = f"# {brief['display_name']}：装配与验收\n\n状态：仅设计，未生成模型、未验骨架或动作。\n\n{asset['risk']}\n\n"
        if row:
            profile = brief["animation_contract"]
            detail += f"{profile['grip']}\n\n{profile['motion']}\n\n{profile['clearance']}\n\n"
            detail += f"攻击周期 {row['AttackInterval']} 秒，接触 {row['AttackWindup']} 秒；收招预算 {profile['timing']['recovery_budget_seconds']} 秒。\n\n"
            detail += f"技能“{row['AbilityName']}”：{profile['ability_cue']} 增益 {row['AbilityDuration']} 秒，冷却 {row['AbilityCooldown']} 秒。\n\n"
            detail += "独立装配：" + "、".join(asset["modules"]) + "。\n\n" + INTEGRATION
        else:
            detail += "DCC 优先，不提交付费几何任务。定位点：" + "、".join(asset["anchors"]) + "。\n\n完成手型实测、正反面厚度、握把和全动作净空检查后才标记通过。\n"
        generated[folder / "integration.md"] = detail
    lines = ["# 五时代统帅设计补充", "", "当前只完成设计与依赖规划；参考图、模型、绑定、动画和实机审批均未完成。",
             "与原56项设计并列维护，执行 Tools/build_champion_briefs.py 可重新从当前玩法数据派生。",
             "优先完成部落酋长，与石器三兵种、基地和炮塔组成一套可玩美术。", "",
             "| 统帅 | 时代 | 名义身高 | 周期/接触 | 独立装备 |", "|---|---:|---:|---|---|"]
    for asset in core:
        row = by_key[asset["id"]]
        lines.append(f"| [{row['DisplayName']}](prompts/{asset['id']}/integration.md) | {row['Age']} | {baseline['nominal_height_cm']:g} cm | {row['AttackInterval']}/{row['AttackWindup']} 秒 | {', '.join(asset['modules'])} |")
    lines += ["", "新增5个人体和5件武器/盾；未来统帅复用已有 Weapon_EnergyBlade 设计，仍须单独验证尺度和挂点。",
              "所有人物均为空手中性A姿态四视图；动作参考与建模参考分开。武器先DCC建模，队色、白色材质与特效各自独立。",
              "审批顺序：同组参考图一致性 → 几何与手指 → 灰模/骨架 → 握持与五段动画 → 材质队色 → 双方三档镜头与实际对局。",
              f"程序基准来自 CWModels::BuildChampion（当前缩放 {baseline['baseline_scale']:g}、名义身高 {baseline['nominal_height_cm']:g}cm），尺寸在每次生成时重读源码。不得按美术尺寸改玩法碰撞。", ""]
    generated[ART_PATH / "CHAMPIONS.md"] = "\n".join(lines)
    manifest = {"schema_version": 1, "generated_by": GENERATOR, "champions": len(core), "new_equipment": len(support),
                "source_sha256": source_hash, "catalog_sha256": digest(art / "catalog_champions.json"),
                "paid_jobs_submitted": 0, "production_approved": False,
                "files": {str(path.as_posix()): hashlib.sha256(content.encode("utf-8")).hexdigest()
                          for path, content in generated.items()}}
    generated[ART_PATH / "jobs/champion_briefs_manifest.json"] = json_text(manifest)
    return generated


def generate(root=ROOT, check=False):
    generated = outputs(root)
    changed = [path for path, value in generated.items()
               if not (root / path).exists() or (root / path).read_bytes() != value.encode("utf-8")]
    if check and changed:
        raise ValueError("Stale or missing champion outputs: " + ", ".join(p.as_posix() for p in changed))
    if not check:
        for path in changed:
            destination = root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(generated[path], encoding="utf-8", newline="\n")
    return {"files": len(generated), "changed": len(changed), "checked_only": check, "paid_jobs_submitted": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(generate(args.root.resolve(), args.check)))
