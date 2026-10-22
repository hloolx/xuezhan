"""Read-only Base_Stone fresh-process validation; never imports, repairs or saves UE assets."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import itertools
import json
import math
import os
from pathlib import Path
import struct
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "Tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "Tools"))
from import_art_pilot import inspect_asset, load_manifest, sha256
from inspect_art_materials import audit_meshes

BASE = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/base_stone_v01"
REVIEW = ROOT / "RawAssets/Art/Tripo_v01/reviews/base_stone_ue_20261020"
DESTINATION = "/Game/ArtPilot/tripo_base_stone_pbr_v01/Base_Stone/h96b57839189a"
SOURCE_SHA = "23f0701d13e0edd1d4d788ff8725482ad8e0d9b1e129d14c2e523ab128ff31c4"
POSITION_TOLERANCE_CM = 0.001
UV_TOLERANCE = 0.000001


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_new(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def package_file(asset_path, content=ROOT / "Content"):
    if not asset_path.startswith(DESTINATION + "/") or ".." in asset_path:
        raise ValueError("Refuse package outside this exact isolated Base import")
    package = asset_path.split(".")[0]
    return content / (package[len("/Game/"):] + ".uasset")


def file_record(path):
    path = Path(path).resolve()
    return {"file": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def check_records(records):
    for record in records:
        path = Path(record["file"])
        if not path.is_file() or sha256(path) != record["sha256"]:
            raise ValueError("Frozen evidence changed or missing: " + str(path))


def initial_inputs(import_path, manifest_path):
    imported = read_json(import_path)
    manifest, entries = load_manifest(manifest_path)
    if imported.get("dry_run") is not False or imported.get("failed") != 0:
        raise ValueError("Actual successful initial import is required")
    if len(entries) != 1 or entries[0]["id"] != "Base_Stone" or len(imported["results"]) != 1:
        raise ValueError("Only the single Base_Stone pilot is supported")
    result = imported["results"][0]
    item = entries[0]
    if result.get("warnings") or result.get("status") not in {"imported", "reused_existing"}:
        raise ValueError("Initial import contains unresolved warnings")
    if item["destination"] != DESTINATION or result["destination"] != DESTINATION:
        raise ValueError("Initial import destination differs from frozen Base candidate")
    if item["source_sha256"] != SOURCE_SHA or result["source_sha256"] != SOURCE_SHA:
        raise ValueError("Initial source differs from root-approved PBR")
    if item.get("runtime_material_overrides") != {"Metallic": 0}:
        raise ValueError("Expected explicit dielectric Metallic=0 override")
    if not item.get("approved_for_ue_import") or item.get("production_approved"):
        raise ValueError("Root controlled-import approval, not production approval, is required")
    return result, item


def freeze_baseline(args):
    if not args.initial_process_id or args.initial_process_id == os.getpid():
        raise ValueError("Supply the actual already-exited initial UE process ID")
    result, item = initial_inputs(args.import_report, args.manifest)
    assets = result["assets"]
    if Counter(asset["class"] for asset in assets) != Counter({"StaticMesh": 1, "Material": 1, "Texture2D": 3}):
        raise ValueError("Expected exactly one mesh, one material, three textures")
    files = [dict(file_record(package_file(asset["path"])), asset_path=asset["path"], class_name=asset["class"]) for asset in assets]
    disk_files = set(package_file(assets[0]["path"]).parent.glob("*.uasset"))
    if disk_files != {Path(record["file"]) for record in files}:
        raise ValueError("Actual isolated package set does not contain exactly the imported five assets")
    source_files = [Path(item["source"]), args.import_report, args.manifest,
                    BASE / "pbr_v01/hf150ba0cde05/manifest.json",
                    BASE / "pbr_v01/hf150ba0cde05/inspection.json",
                    BASE / "pbr_v01/hf150ba0cde05/texture_payload_audit.json",
                    BASE / "cpu_diagnostic_v01/platforms.json"]
    source_files.extend(ROOT / texture["file"] for texture in item["textures"])
    document = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "disk_baseline_frozen_after_initial_process_exit_pending_actual_fresh_reopen",
                "initial_process_id": args.initial_process_id,
                "initial_process_evidence": "Root reported initial UE PID and exit0; original generic importer does not emit PID.",
                "destination": DESTINATION, "import_report": str(args.import_report), "manifest": str(args.manifest),
                "files": files, "source_evidence": [file_record(path) for path in source_files],
                "validated_in_fresh_process": False, "production_approved": False}
    write_new(args.baseline, document)
    return document


def read_glb_geometry(path):
    data = Path(path).read_bytes()
    if struct.unpack_from("<III", data) != (0x46546C67, 2, len(data)):
        raise ValueError("Invalid GLB header")
    document, binary = None, None
    cursor = 12
    while cursor < len(data):
        length, kind = struct.unpack_from("<II", data, cursor)
        chunk = data[cursor + 8:cursor + 8 + length]
        cursor += 8 + length
        if kind == 0x4E4F534A:
            document = json.loads(chunk.rstrip(b" \x00"))
        elif kind == 0x004E4942:
            binary = chunk
    if document is None or binary is None or len(document["meshes"]) != 1:
        raise ValueError("Expected this single-mesh embedded GLB")
    if any(set(node) & {"matrix", "translation", "rotation", "scale", "skin"} for node in document["nodes"]):
        raise ValueError("Unexpected node transform: do not silently ignore or double-apply it")
    primitives = document["meshes"][0]["primitives"]
    if len(primitives) != 1 or primitives[0].get("mode", 4) != 4:
        raise ValueError("Expected one indexed triangle primitive")

    def accessor(index):
        record = document["accessors"][index]
        if record.get("sparse") or record.get("normalized"):
            raise ValueError("Unexpected sparse/normalized accessor")
        view = document["bufferViews"][record["bufferView"]]
        if view.get("buffer", 0) != 0:
            raise ValueError("External accessor is unsupported")
        component = {5126: "f", 5123: "H", 5125: "I"}[record["componentType"]]
        width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[record["type"]]
        unpacker = struct.Struct("<" + component * width)
        stride = view.get("byteStride", unpacker.size)
        start = view.get("byteOffset", 0) + record.get("byteOffset", 0)
        return [unpacker.unpack_from(binary, start + offset * stride) for offset in range(record["count"])]

    primitive = primitives[0]
    positions = accessor(primitive["attributes"]["POSITION"])
    uv = accessor(primitive["attributes"]["TEXCOORD_0"])
    indices = [entry[0] for entry in accessor(primitive["indices"])]
    if len(indices) != 18681 * 3 or len(positions) != len(uv):
        raise ValueError("Unexpected source triangle or UV count")
    corners = [(point[0] * 100, point[2] * 100, point[1] * 100, *texcoord) for point, texcoord in zip(positions, uv)]
    if any(not math.isfinite(value) for corner in corners for value in corner):
        raise ValueError("Non-finite source geometry/UV")
    return corners, [tuple(indices[offset:offset + 3]) for offset in range(0, len(indices), 3)]


def match_triangles(source_corners, source_triangles, observed_triangles):
    canonical = {corner: index for index, corner in enumerate(sorted(set(source_corners)))}
    source_ids = [canonical[corner] for corner in source_corners]
    expected = Counter(tuple(sorted(source_ids[index] for index in triangle)) for triangle in source_triangles)
    buckets = defaultdict(list)
    cell = POSITION_TOLERANCE_CM
    for corner, index in canonical.items():
        buckets[tuple(math.floor(value / cell) for value in corner[:3])].append((corner, index))
    offsets = list(itertools.product((-1, 0, 1), repeat=3))
    cache, observed = {}, Counter()
    maximum_position, maximum_uv = 0.0, 0.0
    for triangle in observed_triangles:
        mapped = []
        for corner in triangle:
            corner = tuple(corner)
            if corner not in cache:
                key = tuple(math.floor(value / cell) for value in corner[:3])
                candidates = []
                for offset in offsets:
                    for source, index in buckets.get(tuple(value + delta for value, delta in zip(key, offset)), ()):
                        position_error = max(abs(actual - wanted) for actual, wanted in zip(corner[:3], source[:3]))
                        uv_error = max(abs(actual - wanted) for actual, wanted in zip(corner[3:], source[3:]))
                        if position_error <= POSITION_TOLERANCE_CM and uv_error <= UV_TOLERANCE:
                            candidates.append((position_error, uv_error, index))
                if not candidates:
                    raise ValueError("Actual UE corner has no source position+UV match: " + str(corner))
                error, uv_error, index = min(candidates)
                maximum_position = max(maximum_position, error)
                maximum_uv = max(maximum_uv, uv_error)
                cache[corner] = index
            mapped.append(cache[corner])
        observed[tuple(sorted(mapped))] += 1
    if observed != expected:
        raise ValueError("Triangle position+UV multiset mismatch: missing=" + str(sum((expected - observed).values())) + ", extra=" + str(sum((observed - expected).values())))
    return {"status": "passed", "triangle_count": sum(observed.values()), "unique_position_uv_corners_checked": len(cache),
            "maximum_position_error_cm": maximum_position, "maximum_uv_error": maximum_uv,
            "position_tolerance_cm": POSITION_TOLERANCE_CM, "uv_tolerance": UV_TOLERANCE,
            "gltf_metres_to_unreal_cm": "(x,y,z) -> (100*x,100*z,100*y)",
            "blender_cm_to_unreal_cm": "(x,y,z) -> (x,-y,z)",
            "door_positive_x_preserved": True, "blender_y_sign_reversed": True,
            "scope": "Every source triangle and associated UV0 corners; unordered corner matching does not separately certify winding or render-data normal/tangent parity."}


def actual_triangles(unreal, mesh):
    description = mesh.get_static_mesh_description(0)
    if description is None or description.get_triangle_count() != 18681:
        raise ValueError("Missing or changed persisted source MeshDescription")
    rows = []
    for index in range(description.get_triangle_count()):
        triangle_id = unreal.TriangleID(id_value=index)
        if not description.is_triangle_valid(triangle_id):
            raise ValueError("Unexpected sparse triangle IDs; do not skip source faces")
        row = []
        for instance in description.get_triangle_vertex_instances(triangle_id):
            position = description.get_vertex_position(description.get_vertex_instance_vertex(instance))
            uv = description.get_vertex_instance_uv(instance, 0)
            row.append((float(position.x), float(position.y), float(position.z), float(uv.x), float(uv.y)))
        if len(row) != 3:
            raise ValueError("Unexpected non-triangle source face")
        rows.append(row)
    return rows


def validate_fresh(unreal, baseline, args):
    if baseline["initial_process_id"] == os.getpid():
        raise ValueError("Fresh validation must run in a different UE process")
    check_records(baseline["source_evidence"] + baseline["files"])
    result, item = initial_inputs(Path(baseline["import_report"]), Path(baseline["manifest"]))
    library = unreal.EditorAssetLibrary
    actual_paths = set(library.list_assets(DESTINATION, recursive=True, include_folder=False))
    expected_paths = {record["asset_path"] for record in baseline["files"]}
    if actual_paths != expected_paths:
        raise ValueError("Fresh isolated registry asset set differs from saved five-package set")
    objects = []
    for record in baseline["files"]:
        loaded = library.load_asset(record["asset_path"])
        if loaded is None or loaded.get_class().get_name() != record["class_name"]:
            raise ValueError("Persisted package could not reopen as its recorded class")
        actual_file = package_file(record["asset_path"], Path(unreal.Paths.project_content_dir()).resolve())
        if sha256(actual_file) != record["sha256"]:
            raise ValueError("UE project resolves a different persisted package")
        objects.append(loaded)
    mesh = next(asset for asset in objects if isinstance(asset, unreal.StaticMesh))
    inspection = inspect_asset(unreal, mesh)
    bounds = mesh.get_bounds()
    actual_min = [float(getattr(bounds.origin, axis) - getattr(bounds.box_extent, axis)) for axis in ("x", "y", "z")]
    actual_max = [float(getattr(bounds.origin, axis) + getattr(bounds.box_extent, axis)) for axis in ("x", "y", "z")]
    expected = item["expected_bounds_cm"]
    for observed, wanted in ((actual_min, expected["min"]), (actual_max, expected["max"]), (inspection["dimensions_cm"], item["expected_dimensions_cm"])):
        if any(abs(actual - target) > 0.001 for actual, target in zip(observed, wanted)):
            raise ValueError("Persisted bounds changed; preserve underground minZ=-31, not bottom-align")
    if inspection["triangles_lod0"] != 18681 or inspection["source_mesh_triangles_lod0"] != 18681 or inspection["lod_count"] != 1 or inspection["nanite_enabled"] or len(inspection["material_slots"]) != 1:
        raise ValueError("Persisted mesh counts/LOD/material contract changed")
    audit = audit_meshes(unreal, [mesh], item["source"], repair=False, overrides={"Metallic": 0})
    if audit["warnings"] or len(audit["materials"]) != 1:
        raise ValueError("Persisted native PBR audit failed: " + str(audit["warnings"]))
    material = audit["materials"][0]
    if material["channels"]["metallic"].get("effective_factor_or_scale") != 0:
        raise ValueError("Metallic=0 was not persisted")
    textures = material["textures"]
    if len(textures) != 3 or any(texture.get("dimensions") != [2048, 2048] for texture in textures):
        raise ValueError("Expected three actual 2048-square textures")
    normal_paths = set(material["channels"]["normal"]["textures"])
    if any(not texture["flip_green_channel"] for texture in textures if texture["path"] in normal_paths):
        raise ValueError("GLTF normal green-channel import conversion was not persisted")
    corners, triangles = read_glb_geometry(item["source"])
    geometry = match_triangles(corners, triangles, actual_triangles(unreal, mesh))
    platforms = []
    for platform in read_json(BASE / "cpu_diagnostic_v01/platforms.json"):
        initial = platform["centre_ray_top"]["position_cm"]
        normalized = [initial[0], initial[1], initial[2] - 31]
        platforms.append({"id_from_blender": platform["id"], "original_diagnostic_cm": initial,
                          "normalized_blender_cm": normalized, "expected_unreal_cm": [normalized[0], -normalized[1], normalized[2]],
                          "approved_as_turret_socket": False, "implemented_socket": False,
                          "limitation": "Candidate metadata propagated through verified global geometry transform; not a new local platform ray or turret sweep test."})
    check_records(baseline["source_evidence"] + baseline["files"])
    return {"status": "base_stone_fresh_reopen_structural_and_coordinate_checks_passed",
            "execution_process_id": os.getpid(), "initial_process_id": baseline["initial_process_id"] ,
            "validated_in_fresh_process": True, "read_only": True, "source_and_all_five_packages_unchanged": True,
            "disk_dependency_validation": {"status": "passed", "files": baseline["files"]},
            "source_evidence": baseline["source_evidence"], "mesh": inspection,
            "bounds_cm": {"min": actual_min, "max": actual_max, "ground_reference_z": 0},
            "material_audit": audit, "source_geometry_and_uv_correspondence": geometry,
            "candidate_platform_metadata": platforms,
            "production_approved": False, "runtime_integrated": False,
            "remaining_gates": ["Actual game camera/material appearance", "Faction flag masking or separation", "Turret pivots/support/sweep", "Larger unit and mount spawn clearance", "Small door is not 150cm-unit traversable"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-baseline", action="store_true")
    parser.add_argument("--initial-process-id", type=int)
    parser.add_argument("--import-report", type=Path, default=REVIEW / "import_01.json")
    parser.add_argument("--manifest", type=Path, default=REVIEW / "import_manifest.json")
    parser.add_argument("--baseline", type=Path, default=os.environ.get("CIVWAR_BASE_FRESH_BASELINE", str(BASE / "ue_fresh_preflight/frozen_baseline.json")))
    parser.add_argument("--report", type=Path, default=os.environ.get("CIVWAR_BASE_FRESH_REPORT", str(BASE / "ue_fresh_preflight/fresh_01.json")))
    args, _ = parser.parse_known_args()
    if args.freeze_baseline:
        document = freeze_baseline(args)
        print(json.dumps({"baseline": str(args.baseline), "packages": len(document["files"])}))
        return
    if args.report.exists():
        raise FileExistsError("Refuse to overwrite prior fresh validation evidence")
    baseline = read_json(args.baseline)
    try:
        import unreal
        document = validate_fresh(unreal, baseline, args)
    except Exception as exc:
        write_new(args.report, {"status": "failed", "error": str(exc), "execution_process_id": os.getpid(),
                                "validated_in_fresh_process": False, "production_approved": False})
        raise
    document["created_at"] = datetime.now(timezone.utc).isoformat()
    document["baseline"] = file_record(args.baseline)
    document["validator"] = file_record(Path(__file__))
    write_new(args.report, document)
    print("BaseStone fresh report: " + str(args.report))


if __name__ == "__main__":
    main()
