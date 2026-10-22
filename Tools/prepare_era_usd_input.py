"""Receive an actual standalone USD/USDZ, preserving original GLB PBR bytes.

No skeleton claim is made here: the separate leased Blender inspection must pass.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def record(path):
    return {"path": str(path.resolve()), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def prepare(asset, source):
    source = source.resolve(strict=True)
    if source.suffix.lower() not in {".usd", ".usda", ".usdc", ".usdz"}:
        raise ValueError("An actual standalone USD/USDZ is required; inspect ZIP packaging before extracting dependencies")
    raw = source.read_bytes()
    if source.suffix.lower() == ".usdz":
        with zipfile.ZipFile(source) as archive:
            if archive.testzip() is not None or not any(Path(n).suffix.lower() in {".usd", ".usda", ".usdc"} for n in archive.namelist()):
                raise ValueError("The received USDZ is incomplete or contains no USD stage")
    elif not (raw.startswith(b"PXR-USDC") or raw.lstrip().startswith(b"#usda")):
        raise ValueError("The received file is not a recognized USD stage")
    canonical = ROOT/"RawAssets/Art/Tripo_v01/tripo_raw"/asset/"web_v01_canonical"
    original = canonical/"rigged.glb"
    if not original.is_file():
        raise ValueError("Retain the original GLB for exact PBR lineage")
    target = canonical/("rigged"+source.suffix.lower())
    if target.exists() and target.read_bytes() != raw:
        raise ValueError("Preserve earlier actual USD; use an explicit new source version")
    if not target.exists():
        target.write_bytes(raw)
    receipt = canonical/"rigged_usd_receipt.json"
    report = {"asset_id": asset, "received_source": record(source), "usd": record(target),
              "original_glb_pbr": record(original),
              "status": "actual_usd_received_pending_blender_skeleton_and_weights",
              "actual_bone_frame_verified": False, "actual_skin_weights_verified": False}
    if receipt.exists() and json.loads(receipt.read_text(encoding="utf-8")) != report:
        raise ValueError("Preserve previous USD receipt")
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", required=True)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    if not args.asset.replace("_", "").isalnum():
        raise ValueError("An explicit asset id is required")
    prepare(args.asset, args.source)
