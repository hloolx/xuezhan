"""Receive an explicitly named Tripo FBX ZIP without touching raw GLB/PBR."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(asset_id, archive):
    canonical = ROOT/"RawAssets/Art/Tripo_v01/tripo_raw"/asset_id/"web_v01_canonical"
    original = canonical/"rigged.glb"
    if not original.is_file():
        raise ValueError("An original named rigged GLB is required to retain full PBR lineage")
    original_hash = sha(original.read_bytes())
    with zipfile.ZipFile(archive) as zipped:
        candidates = [entry for entry in zipped.infolist() if not entry.is_dir() and entry.filename.lower().endswith(".fbx")]
        if len(candidates) != 1:
            raise ValueError("Choose a ZIP containing exactly one intended rigged FBX")
        entry = candidates[0]
        data = zipped.read(entry)
    output = canonical/"rigged.fbx"
    if output.exists() and output.read_bytes() != data:
        raise ValueError("Preserve prior actual FBX; use a separate version directory")
    if not output.exists():
        output.write_bytes(data)
    if sha(original.read_bytes()) != original_hash:
        raise ValueError("Original GLB changed during source receipt")
    report = {"asset_id": asset_id, "source_zip": str(archive.resolve()),
        "zip_sha256": sha(archive.read_bytes()), "zip_member": entry.filename,
        "fbx": {"path": str(output.resolve()), "sha256": sha(data), "bytes": len(data)},
        "original_glb_pbr": {"path": str(original.resolve()), "sha256": original_hash},
        "actual_bone_frame_verified": False,
        "status": "actual_export_received_pending_blender_bind_inspection",
        "texture_policy": "Use original GLB embedded PBR bytes; FBX-converted JPEG is not the delivered texture"}
    receipt = canonical/"rigged_fbx_receipt.json"
    if receipt.exists() and json.loads(receipt.read_text(encoding="utf-8")) != report:
        raise ValueError("Prior FBX receipt differs; preserve it")
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", required=True)
    parser.add_argument("--zip", type=Path, required=True)
    args = parser.parse_args()
    if not args.asset.replace("_", "").isalnum():
        raise ValueError("Only an explicit asset id is allowed")
    prepare(args.asset, args.zip)
