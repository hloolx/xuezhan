"""Collect one Studio production export without writing the shared web ledger."""
import argparse
import hashlib
import json
import shutil
import struct
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset")
    parser.add_argument("--intent", action="store_true")
    parser.add_argument("--task")
    parser.add_argument("--status")
    parser.add_argument("--stage")
    parser.add_argument("--cost", type=int)
    parser.add_argument("--cost-evidence")
    parser.add_argument("--balance", type=int)
    parser.add_argument("--collect", choices=["geometry", "textured", "pbr", "rigged"])
    parser.add_argument("--collect-fbx", action="store_true")
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    directory = ART / "tripo_raw" / args.asset / "web_v01_canonical"
    directory.mkdir(parents=True, exist_ok=True)
    receipt_path = directory / "production_receipt.json"
    intent_path = directory / "production_submission.intent.json"
    now = datetime.now(timezone.utc).isoformat()
    if args.intent:
        if intent_path.exists() or receipt_path.exists():
            raise SystemExit("Existing production intent/receipt: inspect before submitting")
        prepared = ART / "prepared_tripo_canonical" / args.asset
        images = {}
        for view in ("front", "left", "back", "right"):
            source = prepared / f"{view}.png"
            if source.exists():
                images[view] = {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        if "front" not in images:
            raise SystemExit("Canonical front reference missing")
        receipt = {
            "asset_id": args.asset, "prepared_at": now, "images": images,
            "status": "prepared_not_submitted", "task_id": None, "stages": {},
            "game_ready": False, "purchase_made": False,
            "requested_model": "HD H3.1; final settings and price require visible UI confirmation",
        }
        write(intent_path, receipt)
    elif receipt_path.exists():
        receipt = read(receipt_path)
    else:
        old_path = directory / "submission.json"
        receipt = {
            "asset_id": args.asset, "prepared_at": now, "stages": {},
            "status": "continuing_existing_task", "game_ready": False, "purchase_made": False,
        }
        if old_path.exists():
            old = read(old_path)
            receipt["task_id"] = old.get("task_id")
            receipt["existing_receipt"] = str(old_path.relative_to(ROOT))
    if args.task:
        if receipt.get("task_id") and receipt["task_id"] != args.task:
            raise SystemExit("Task mismatch; do not silently substitute")
        receipt["task_id"] = args.task
    if args.stage:
        if args.cost is None or not args.cost_evidence:
            raise SystemExit("Stage cost needs amount and observed evidence")
        receipt["stages"][args.stage] = {
            "credits": args.cost, "evidence": args.cost_evidence, "recorded_at": now,
        }
        receipt["web_credits_confirmed"] = sum(s["credits"] for s in receipt["stages"].values())
    if args.balance is not None:
        receipt["shared_balance_observed"] = args.balance
        receipt["balance_note"] = "Shared across tabs; stage costs are not inferred from total balance deltas."
    if args.status:
        receipt["status"] = args.status
    if args.collect_fbx:
        if not args.source or args.collect:
            raise SystemExit("--collect-fbx needs --source and cannot combine with --collect")
        blob = args.source.read_bytes()
        with zipfile.ZipFile(args.source) as archive:
            entries = archive.namelist()
            if not any(name.lower().endswith(".fbx") for name in entries):
                raise SystemExit("FBX archive contains no FBX")
            if archive.testzip() is not None:
                raise SystemExit("Corrupt FBX archive")
        destination = directory / "rigged_fbx.zip"
        if destination.exists() and destination.read_bytes() != blob:
            raise SystemExit("Refusing to overwrite a different FBX archive")
        if not destination.exists():
            shutil.copy2(args.source, destination)
        inspection = {
            "asset_id": args.asset, "task_id": receipt.get("task_id"),
            "file": str(destination), "source_download": str(args.source),
            "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob),
            "archive_entries": entries, "cost": 0,
            "format": "FBX Blender preset; Export Skeleton enabled; 4K",
            "dcc_rest_pose_validated": False, "game_ready": False,
        }
        write(directory / "fbx_export_receipt.json", inspection)
        receipt.setdefault("exports", {})["rigged_fbx"] = inspection
    if args.collect:
        if not args.source:
            raise SystemExit("--source required")
        blob = args.source.read_bytes()
        magic, version, size = struct.unpack_from("<4sII", blob)
        if magic != b"glTF" or version != 2 or size != len(blob):
            raise SystemExit("Invalid or incomplete GLB")
        length, kind = struct.unpack_from("<II", blob, 12)
        if kind != 0x4E4F534A:
            raise SystemExit("GLB JSON chunk missing")
        gltf = json.loads(blob[20:20 + length])
        primitives = [p for mesh in gltf.get("meshes", []) for p in mesh["primitives"]]
        materials = gltf.get("materials", [])
        if args.collect in ("pbr", "rigged"):
            if not any(m.get("normalTexture") and m.get("pbrMetallicRoughness", {}).get("metallicRoughnessTexture") for m in materials):
                raise SystemExit("Requested PBR export lacks normal or metallic/roughness texture")
        if args.collect == "rigged":
            if not gltf.get("skins") or not all("JOINTS_0" in p["attributes"] and "WEIGHTS_0" in p["attributes"] for p in primitives):
                raise SystemExit("Requested rigged export lacks actual skin weights")
        destination = directory / f"{args.collect}.glb"
        if destination.exists() and destination.read_bytes() != blob:
            raise SystemExit("Refusing to overwrite a different export")
        if not destination.exists():
            shutil.copy2(args.source, destination)
        inspection = {
            "file": str(destination), "source_download": str(args.source),
            "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob),
            "meshes": len(gltf.get("meshes", [])), "materials": len(materials),
            "embedded_images": len(gltf.get("images", [])), "skins": len(gltf.get("skins", [])),
            "animations": len(gltf.get("animations", [])),
            "triangles": sum(gltf["accessors"][p["indices"]]["count"] // 3 for p in primitives if p.get("mode", 4) == 4 and "indices" in p),
            "has_uv": all("TEXCOORD_0" in p["attributes"] for p in primitives),
            "has_normal_texture": any(m.get("normalTexture") for m in materials),
            "has_metallic_roughness_texture": any(m.get("pbrMetallicRoughness", {}).get("metallicRoughnessTexture") for m in materials),
            "bone_names": [[gltf["nodes"][i].get("name", str(i)) for i in skin["joints"]] for skin in gltf.get("skins", [])],
            "skin_rest_evidence": [
                {
                    "joint_count": len(skin["joints"]),
                    "joints_with_explicit_local_transform": sum(
                        any(key in gltf["nodes"][i] for key in ("matrix", "translation", "rotation", "scale"))
                        for i in skin["joints"]
                    ),
                    "joints_with_nonidentity_local_transform": sum(
                        gltf["nodes"][i].get("translation", [0, 0, 0]) != [0, 0, 0]
                        or gltf["nodes"][i].get("rotation", [0, 0, 0, 1]) != [0, 0, 0, 1]
                        or gltf["nodes"][i].get("scale", [1, 1, 1]) != [1, 1, 1]
                        or gltf["nodes"][i].get("matrix", [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
                        != [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
                        for i in skin["joints"]
                    ),
                    "inverse_bind_accessor": skin.get("inverseBindMatrices"),
                    "dcc_rest_pose_validated": False,
                    "note": "Raw skin/weights presence is not a DCC usability check. Tripo may omit joint node TRS; preserve source and validate/derive rest transforms from inverse binds before animation.",
                }
                for skin in gltf.get("skins", [])
            ],
            "game_ready": False,
        }
        write(directory / f"{args.collect}_inspection.json", inspection)
        receipt.setdefault("exports", {})[args.collect] = inspection
    receipt["updated_at"] = now
    write(receipt_path, receipt)
    print(json.dumps({"asset": args.asset, "task": receipt.get("task_id"), "status": receipt["status"], "credits": receipt.get("web_credits_confirmed"), "exports": list(receipt.get("exports", {}))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
