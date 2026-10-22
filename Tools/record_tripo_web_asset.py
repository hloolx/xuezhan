"""Record visible Studio receipts and collect exports from the user's download folder."""
import argparse
import hashlib
import json
import shutil
import struct
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01"
parser = argparse.ArgumentParser()
parser.add_argument("asset")
parser.add_argument("--prepare", action="store_true")
parser.add_argument("--task")
parser.add_argument("--status")
parser.add_argument("--cost", type=int)
parser.add_argument("--balance", type=int)
parser.add_argument("--collect", choices=["geometry", "textured", "pbr", "rigged"])
args = parser.parse_args()
directory = ART / "tripo_raw" / args.asset / "web_v01_canonical"
receipt_path = directory / "submission.json"
intent_path = directory / "submission.intent.json"
now = datetime.now(timezone.utc).isoformat()

def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

if args.prepare:
    if intent_path.exists() or receipt_path.exists():
        raise SystemExit("Existing intent/receipt: inspect it; do not duplicate submission")
    batch = read(ART / "reviews/web_batch_20261020/manifest.json")
    spec = next(j for j in batch["jobs"] if j["asset_id"] == args.asset)
    (directory / "inputs").mkdir(parents=True, exist_ok=False)
    for view, image in spec["images"].items():
        source = Path(image["path"])
        assert hashlib.sha256(source.read_bytes()).hexdigest() == image["sha256"]
        shutil.copy2(source, directory / "inputs" / f"{view}.png")
    receipt = {
        **spec, "prepared_at": now, "status": "prepared_not_submitted",
        "source_review": "Canonical contact sheet visually checked; consistent single subject; stage approval for generation only",
        "generate_clicked": False, "task_id": None, "production_approved": False,
        "scope": "Geometry then texture; rigging, animation, mechanism and UE acceptance remain separate",
    }
    write(intent_path, receipt)
else:
    receipt = read(receipt_path if receipt_path.exists() else intent_path)
if args.task:
    if receipt.get("task_id") and receipt["task_id"] != args.task:
        raise SystemExit("Task ID mismatch")
    receipt["task_id"] = args.task
    receipt["url"] = f"https://studio.tripo3d.ai/workspace/generate/{args.task}"
    receipt["generate_clicked"] = True
if args.status:
    receipt["status"] = args.status
if args.cost is not None:
    receipt["web_credits_confirmed"] = args.cost
if args.balance is not None:
    receipt["web_balance_after"] = args.balance
if args.collect:
    suffix = f"_{args.collect}" if args.collect != "geometry" else ""
    source = Path("F:/down") / f"{args.asset}_web_v01{suffix}.glb"
    blob = source.read_bytes()
    magic, version, size = struct.unpack_from("<4sII", blob)
    assert magic == b"glTF" and version == 2 and size == len(blob), "Invalid/incomplete GLB"
    json_size, chunk_type = struct.unpack_from("<II", blob, 12)
    assert chunk_type == 0x4E4F534A
    gltf = json.loads(blob[20:20 + json_size])
    primitives = [p for m in gltf.get("meshes", []) for p in m["primitives"]]
    image_count = len(gltf.get("images", []))
    materials = gltf.get("materials", [])
    if args.collect in ("textured", "pbr", "rigged"):
        assert image_count and any(m.get("pbrMetallicRoughness", {}).get("baseColorTexture") is not None
                                   for m in materials), "No actual base-color texture found"
    if args.collect == "rigged":
        assert gltf.get("skins") and all("JOINTS_0" in p["attributes"] and "WEIGHTS_0" in p["attributes"]
                                        for p in primitives), "No actual skinned mesh found"
    destination = directory / f"{args.collect}.glb"
    if destination.exists():
        assert destination.read_bytes() == blob, "Refusing to overwrite a different model"
    else:
        shutil.copy2(source, destination)
    inspection = {
        "file": str(destination), "sha256": hashlib.sha256(blob).hexdigest(),
        "bytes": len(blob), "meshes": len(gltf.get("meshes", [])),
        "primitives": len(primitives), "embedded_images": image_count,
        "materials": len(materials),
        "has_uv": all("TEXCOORD_0" in p["attributes"] for p in primitives),
        "has_normal_texture": any(m.get("normalTexture") for m in materials),
        "has_metallic_roughness_texture": any(
            m.get("pbrMetallicRoughness", {}).get("metallicRoughnessTexture") for m in materials),
        "triangles": sum(gltf["accessors"][p["indices"]]["count"] // 3
                         for p in primitives if p.get("mode", 4) == 4 and "indices" in p),
        "skins": len(gltf.get("skins", [])), "animations": len(gltf.get("animations", [])),
        "game_ready": False,
    }
    write(directory / f"{args.collect}_inspection.json", inspection)
    receipt.setdefault("exports", {})[args.collect] = inspection
receipt["updated_at"] = now
write(receipt_path, receipt)
ledger_path = ART / "jobs/web_execution_20261020.json"
ledger = read(ledger_path) if ledger_path.exists() else {
    "schema_version": 1, "provider": "Tripo Studio", "starting_balance": 3035,
    "purchase_made": False, "assets": {},
}
ledger["assets"][args.asset] = {
    "task_id": receipt.get("task_id"), "status": receipt["status"],
    "web_credits_confirmed": receipt.get("web_credits_confirmed"),
    "evidence_file": str(receipt_path.relative_to(ROOT)),
    "export_stages": list(receipt.get("exports", {})), "production_approved": False,
}
ledger["updated_at"] = now
write(ledger_path, ledger)
print(json.dumps(ledger["assets"][args.asset], ensure_ascii=False))
