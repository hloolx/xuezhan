from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re


VERSION = "stoneaxe_socket_absolute_motion_numeric_v3"
SOCKET = "weapon_r"
BONE = "hand_r"
VERTEX_TOLERANCE_CM = .01
POSE_TOLERANCE_CM = .1
CALIBRATION_TOLERANCE_CM = .005
MATRIX_TOLERANCE = 1e-5
POSES = {"reference": (None, 0), "idle": ("Idle", 0), "attack_contact": ("Attack", .35), "death_end": ("Death", 1.2)}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def vector(values, size=3):
    if len(values) != size or any(not math.isfinite(float(value)) for value in values):
        raise ValueError("Expected finite vector of length " + str(size))
    return [float(value) for value in values]


def matrix(values):
    if len(values) != 4:
        raise ValueError("Expected a 4x4 column-vector affine matrix")
    result = [vector(row, 4) for row in values]
    if max(abs(result[3][column] - float(column == 3)) for column in range(4)) > 1e-8:
        raise ValueError("Expected affine bottom row [0, 0, 0, 1]")
    return result


def multiply(left, right):
    return [[sum(left[row][inner] * right[inner][column] for inner in range(4)) for column in range(4)] for row in range(4)]


def inverse(values):
    rows = [row + [float(index == column) for column in range(4)] for index, row in enumerate(matrix(values))]
    for column in range(4):
        pivot = max(range(column, 4), key=lambda row: abs(rows[row][column]))
        if abs(rows[pivot][column]) < 1e-12:
            raise ValueError("Singular transform")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        divisor = rows[column][column]
        rows[column] = [value / divisor for value in rows[column]]
        for row in range(4):
            if row != column:
                factor = rows[row][column]
                rows[row] = [value - factor * other for value, other in zip(rows[row], rows[column])]
    return [row[4:] for row in rows]


def transform_point(transform, point):
    position = vector(point) + [1.0]
    return [sum(transform[row][column] * position[column] for column in range(4)) for row in range(3)]


def distance(first, second):
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(first, second)))


def matrix_error(first, second):
    return max(abs(first[row][column] - second[row][column]) for row in range(4) for column in range(4))


def blender_point_to_ue(point):
    point = vector(point)
    return [100 * point[0], -100 * point[1], 100 * point[2]]


def blender_transform_to_ue(transform):
    transform = matrix(transform)
    basis = (100, -100, 100, 1)
    return [[transform[row][column] * basis[row] / basis[column] for column in range(4)] for row in range(4)]


def compose(translation, quaternion, scale):
    translation, quaternion, scale = vector(translation), vector(quaternion, 4), vector(scale)
    length = math.sqrt(sum(value * value for value in quaternion))
    if length < 1e-12 or min(scale) <= 0:
        raise ValueError("Nonzero quaternion and strictly positive scale required")
    quat_x, quat_y, quat_z, quat_w = [value / length for value in quaternion]
    rotation = [
        [1 - 2 * (quat_y ** 2 + quat_z ** 2), 2 * (quat_x * quat_y - quat_z * quat_w), 2 * (quat_x * quat_z + quat_y * quat_w)],
        [2 * (quat_x * quat_y + quat_z * quat_w), 1 - 2 * (quat_x ** 2 + quat_z ** 2), 2 * (quat_y * quat_z - quat_x * quat_w)],
        [2 * (quat_x * quat_z - quat_y * quat_w), 2 * (quat_y * quat_z + quat_x * quat_w), 1 - 2 * (quat_x ** 2 + quat_y ** 2)],
    ]
    return [[rotation[row][column] * scale[column] for column in range(3)] + [translation[row]] for row in range(3)] + [[0, 0, 0, 1]]


def decompose(transform):
    transform = matrix(transform)
    scale = [math.sqrt(sum(transform[row][column] ** 2 for row in range(3))) for column in range(3)]
    if min(scale) < 1e-10:
        raise ValueError("Singular or zero-scale socket")
    rotation = [[transform[row][column] / scale[column] for column in range(3)] for row in range(3)]
    determinant = sum(rotation[0][column] * (rotation[1][(column + 1) % 3] * rotation[2][(column + 2) % 3] - rotation[1][(column + 2) % 3] * rotation[2][(column + 1) % 3]) for column in range(3))
    orthogonality = max(abs(sum(rotation[row][first] * rotation[row][second] for row in range(3)) - float(first == second)) for first in range(3) for second in range(3))
    if determinant <= 0 or abs(determinant - 1) > MATRIX_TOLERANCE or orthogonality > MATRIX_TOLERANCE:
        raise ValueError("Reflected or sheared transform cannot be a positive-scale socket")
    trace = sum(rotation[index][index] for index in range(3))
    if trace > 0:
        divisor = 2 * math.sqrt(trace + 1)
        quaternion = [(rotation[2][1] - rotation[1][2]) / divisor, (rotation[0][2] - rotation[2][0]) / divisor, (rotation[1][0] - rotation[0][1]) / divisor, divisor / 4]
    else:
        major = max(range(3), key=lambda index: rotation[index][index])
        following, last = (major + 1) % 3, (major + 2) % 3
        divisor = 2 * math.sqrt(1 + rotation[major][major] - rotation[following][following] - rotation[last][last])
        quaternion = [0.0] * 4
        quaternion[major] = divisor / 4
        quaternion[following] = (rotation[following][major] + rotation[major][following]) / divisor
        quaternion[last] = (rotation[last][major] + rotation[major][last]) / divisor
        quaternion[3] = (rotation[last][following] - rotation[following][last]) / divisor
    result = {"translation_cm": [transform[row][3] for row in range(3)], "rotation_xyzw": quaternion, "scale": scale}
    if matrix_error(transform, compose(result["translation_cm"], quaternion, scale)) > MATRIX_TOLERANCE:
        raise ValueError("TRS decomposition failed to preserve socket matrix")
    return result


def fit_socket(hand_reference_ue, weapon_reference_blender):
    return decompose(multiply(inverse(hand_reference_ue), blender_transform_to_ue(weapon_reference_blender)))


def nearest_indices(actual, expected):
    if not actual or not expected:
        raise ValueError("Both actual and expected vertex arrays must be nonempty")
    indices = [min(range(len(expected)), key=lambda index: distance(point, expected[index])) for point in actual]
    return indices, max(distance(point, expected[index]) for point, index in zip(actual, indices))


def compare_vertices(actual, expected):
    mapping, expected_error = nearest_indices(expected, actual)
    _, actual_error = nearest_indices(actual, expected)
    return {"expected_to_actual_max_cm": expected_error, "actual_to_expected_max_cm": actual_error,
            "expected_count": len(expected), "actual_count": len(actual), "passed": max(actual_error, expected_error) <= VERTEX_TOLERANCE_CM}, mapping


def calibration_check(calibration):
    if calibration.get("schema_version") != 1 or calibration.get("units") != "metres":
        raise ValueError("Unsupported calibration schema or units")
    if calibration.get("coordinate_system") != "Blender right-handed +X forward +Z up" or calibration.get("matrix_convention") != "4x4 row arrays representing column-vector transforms; translation in last column":
        raise ValueError("Unexpected calibration axis or matrix convention")
    vertices = [vector(point) for point in calibration["local_vertices_m"]]
    if not vertices or not {"handle_tail", "handle_top", "grip_center", "axe_edge_end"}.issubset(calibration["markers"]):
        raise ValueError("Real scale-baked vertices and named grip/edge markers required")
    parts, next_vertex = {}, 0
    for part in calibration["parts"]:
        if part["object"] in parts or part["vertex_start"] != next_vertex or part["vertex_count"] <= 0:
            raise ValueError("Calibration parts must exactly partition the vertex array")
        parts[part["object"]] = part
        next_vertex += part["vertex_count"]
    if next_vertex != len(vertices):
        raise ValueError("Calibration part vertex counts mismatch")
    marker_indices, maximum_error = {}, 0.0
    for name, marker in calibration["markers"].items():
        indices = []
        for source in marker["source_evaluated_vertices"]:
            part = parts[source["object"]]
            if not 0 <= source["vertex"] < part["vertex_count"]:
                raise ValueError("Marker vertex outside its source part")
            indices.append(part["vertex_start"] + source["vertex"])
        if not indices:
            raise ValueError("Marker must refer to actual evaluated vertices")
        center = [sum(vertices[index][axis] for index in indices) / len(indices) for axis in range(3)]
        maximum_error = max(maximum_error, 100 * distance(center, vector(marker["local_position_m"])))
        marker_indices[name] = indices
    if set(calibration["poses"]) != set(POSES):
        raise ValueError("Reference, Idle, Attack contact and Death end evidence required")
    for name, (clip, sample_time) in POSES.items():
        sample = calibration["poses"][name]
        if sample["clip"] != clip or abs(sample["time_seconds"] - sample_time) > 1e-8:
            raise ValueError("Unexpected calibration clip/time: " + name)
        rigid = matrix(sample["weapon_rigid_world_matrix"])
        rigid_parts = decompose(rigid)
        if max(abs(value - 1) for value in rigid_parts["scale"]) > MATRIX_TOLERANCE or min(vector(sample["weapon_world_scale"])) <= 0:
            raise ValueError("Weapon matrix must be rigid; original positive scale must already be baked")
        for marker_name, marker in calibration["markers"].items():
            predicted = transform_point(rigid, marker["local_position_m"])
            maximum_error = max(maximum_error, 100 * distance(predicted, vector(sample["world_positions_m"][marker_name])))
    if maximum_error > CALIBRATION_TOLERANCE_CM:
        raise ValueError("Independent evaluated calibration markers disagree with rigid/baked vertices: " + str(maximum_error) + " cm")
    return {"maximum_source_marker_error_cm": maximum_error, "marker_vertex_indices": marker_indices, "passed": True}


def verified_record(record):
    path = Path(record["path"]).resolve()
    if not path.is_file() or digest(path) != record["sha256"]:
        raise ValueError("Missing or changed calibration/source file: " + str(path))
    return path


def package_path(value):
    return value.split(".", 1)[0]


def validate_import_report(report, manifest_path, settings, destination):
    if report.get("dry_run") is not False or report.get("status") != "isolated_import_fresh_reopen_structural_review_only":
        raise ValueError("A real completed UE import report is required")
    if Path(report["manifest"]).resolve() != manifest_path.resolve() or report["destination"] != destination or report["settings"] != settings:
        raise ValueError("UE report lineage/settings do not match this exact delivery manifest")
    result = report["result"]
    if result.get("structural_checks_passed") is not True or result.get("warnings"):
        raise ValueError("Actual UE structural checks must pass before socket fitting")
    motion = result.get("absolute_motion_validation", {})
    if motion.get("status") != "passed" or motion.get("frames") != 323 or motion.get("reference_and_each_clip_checked") is not True or not motion.get("source"):
        raise ValueError("Reference and all 323 animation frames must pass absolute physical motion validation")
    persistence = result.get("disk_dependency_validation", {})
    if persistence.get("status") != "passed" or persistence.get("validated_in_fresh_process") is not True:
        raise ValueError("Persisted dependencies must pass actual fresh-process UE reopen validation")
    initial_pid, validation_pid = persistence.get("initial_process_id"), persistence.get("validation_process_id")
    if not isinstance(initial_pid, int) or not isinstance(validation_pid, int) or min(initial_pid, validation_pid) <= 0 or initial_pid == validation_pid:
        raise ValueError("Dependency validation must identify a different fresh UE process")
    if not persistence.get("prior_import_report") or not persistence.get("files"):
        raise ValueError("Fresh-process dependency lineage and saved file evidence required")
    if not re.fullmatch(r"/Game/ArtPilot/StoneAxeRig/h[0-9a-f]{16}", destination):
        raise ValueError("Only the exact isolated hash directory may receive a mesh socket")
    if package_path(result["body"]) != destination + "/SK_StoneAxe_Pilot" or package_path(result["weapon"]["path"]) != destination + "/Weapon/SM_StoneAxe_Fitted":
        raise ValueError("Refusing unrelated body or weapon assets")
    if {clip["clip"] for clip in result["clips"]} != {"Idle", "Move", "Attack", "Hit", "Death"}:
        raise ValueError("Missing imported animation clips")
    for clip in result["clips"]:
        if clip.get("same_skeleton") is not True or package_path(clip["path"]) != destination + "/Animations/AN_StoneAxe_" + clip["clip"]:
            raise ValueError("Refusing unrelated animation asset")


def read_inputs(manifest_path, import_report_path):
    module_spec = importlib.util.spec_from_file_location("stoneaxe_import_contract", Path(__file__).with_name("import_stoneaxe_pilot.py"))
    importer = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(importer)
    manifest, settings, destination = importer.read_manifest(manifest_path)
    report = json.loads(import_report_path.read_text(encoding="utf-8-sig"))
    validate_import_report(report, manifest_path, settings, destination)
    if report["result"]["absolute_motion_validation"]["source"] != manifest.get("physical_motion_reference"):
        raise ValueError("Absolute motion validation must reference this exact frozen physical motion input")
    verified_record(manifest["physical_motion_reference"])
    calibration_path = verified_record(manifest["weapon"]["calibration"])
    if not calibration_path.is_relative_to(manifest_path.parent.resolve()):
        raise ValueError("Calibration must be inside this frozen delivery directory")
    calibration = json.loads(calibration_path.read_text(encoding="utf-8-sig"))
    check = calibration_check(calibration)
    return manifest, report, calibration, check


def ue_vector(value):
    return [float(value.x), float(value.y), float(value.z)]


def ue_transform(value):
    rotation = value.rotation
    return compose(ue_vector(value.translation), [rotation.x, rotation.y, rotation.z, rotation.w], ue_vector(value.scale3d))


def evaluate_pose(unreal, mesh, clips, sample):
    if sample["clip"] is None:
        pose = unreal.AnimPoseExtensions.get_reference_pose(mesh.get_editor_property("skeleton"))
    else:
        options = unreal.AnimPoseEvaluationOptions()
        for key, value in {"evaluation_type": unreal.AnimDataEvalType.RAW, "should_retarget": False, "extract_root_motion": False, "optional_skeletal_mesh": mesh}.items():
            options.set_editor_property(key, value)
        sequence = clips[sample["clip"]]
        if sample["time_seconds"] > unreal.AnimationLibrary.get_sequence_length(sequence) + 1e-6:
            raise ValueError("Pose sample is beyond the actual imported animation")
        pose = unreal.AnimPoseExtensions.get_anim_pose_at_time(sequence, sample["time_seconds"], options)
    if not unreal.AnimPoseExtensions.is_valid(pose) or BONE not in [str(name) for name in unreal.AnimPoseExtensions.get_bone_names(pose)]:
        raise ValueError("Actual UE pose lacks hand_r")
    return pose


def marker_errors(markers, world_matrix, sample):
    return {name: distance(transform_point(world_matrix, point), blender_point_to_ue(sample["world_positions_m"][name])) for name, point in markers.items()}


def execute(unreal, import_report, calibration, check, apply_socket, progress=None):
    progress = progress if progress is not None else {}
    required_apis = {"SkeletalMesh": ("add_socket", "num_sockets", "get_socket_by_index"),
                     "SkeletalMeshSocket": ("set_socket_parent", "set_socket_local_transform", "get_socket_local_transform", "get_outer"),
                     "SkeletalMeshEditorSubsystem": ("rename_socket", "remove_socket"),
                     "AnimPoseExtensions": ("get_socket_names", "get_socket_pose"), "Quat": ("rotator",)}
    unavailable = [type_name + "." + method for type_name, methods in required_apis.items() for method in methods if not hasattr(getattr(unreal, type_name, None), method)]
    if unavailable:
        raise RuntimeError("Missing required installed UE Python APIs: " + ", ".join(unavailable))
    source = import_report["result"]
    mesh = unreal.EditorAssetLibrary.load_asset(source["body"])
    weapon = unreal.EditorAssetLibrary.load_asset(source["weapon"]["path"])
    if not isinstance(mesh, unreal.SkeletalMesh) or not isinstance(weapon, unreal.StaticMesh):
        raise ValueError("Expected isolated SkeletalMesh body and StaticMesh weapon")
    body_files = [record for record in source["disk_dependency_validation"]["files"] if package_path(record["asset_path"]) == package_path(mesh.get_path_name())]
    if len(body_files) != 1 or not Path(body_files[0]["package_file"]).is_file():
        raise ValueError("Fresh-process evidence must identify the actual saved body package")
    body_package = Path(body_files[0]["package_file"]).resolve()
    clips = {clip["clip"]: unreal.EditorAssetLibrary.load_asset(clip["path"]) for clip in source["clips"]}
    skeleton = mesh.get_editor_property("skeleton")
    if any(not isinstance(clip, unreal.AnimSequence) or clip.get_editor_property("skeleton") != skeleton for clip in clips.values()):
        raise ValueError("Actual animation skeletons differ from the body")
    vertices, sections = [], []
    for section_index in range(weapon.get_num_sections(0)):
        section_vertices, triangles, normals, uvs, tangents = unreal.ProceduralMeshLibrary.get_section_from_static_mesh(weapon, 0, section_index)
        if not section_vertices or not triangles:
            raise ValueError("Actual StaticMesh section has no readable render geometry")
        vertices.extend(ue_vector(point) for point in section_vertices)
        sections.append({"section": section_index, "vertices": len(section_vertices), "triangles": len(triangles) // 3})
    vertex_check, mapping = compare_vertices(vertices, [blender_point_to_ue(point) for point in calibration["local_vertices_m"]])
    progress.update({"vertex_check": vertex_check, "static_mesh_sections": sections, "actual_static_mesh_vertices_cm": vertices})
    if not vertex_check["passed"]:
        raise ValueError("Actual UE weapon axes/size differ from scale-baked Blender vertices: " + json.dumps(vertex_check))
    markers = {name: [sum(vertices[mapping[index]][axis] for index in indices) / len(indices) for axis in range(3)] for name, indices in check["marker_vertex_indices"].items()}
    poses = {name: evaluate_pose(unreal, mesh, clips, sample) for name, sample in calibration["poses"].items()}
    hands = {name: unreal.AnimPoseExtensions.get_bone_pose(pose, BONE, unreal.AnimPoseSpaces.WORLD) for name, pose in poses.items()}
    fitted = fit_socket(ue_transform(hands["reference"]), calibration["poses"]["reference"]["weapon_rigid_world_matrix"])
    progress["fitted_socket"] = fitted
    local = compose(fitted["translation_cm"], fitted["rotation_xyzw"], fitted["scale"])
    quat = unreal.Quat(*fitted["rotation_xyzw"])
    local_transform = unreal.Transform(location=unreal.Vector(*fitted["translation_cm"]), rotation=quat.rotator(), scale=unreal.Vector(*fitted["scale"]))
    if matrix_error(ue_transform(local_transform), local) > MATRIX_TOLERANCE:
        raise ValueError("UE quaternion/rotator conversion differs from fitted matrix")
    checks = {}
    progress["pose_checks"] = checks
    for name, sample in calibration["poses"].items():
        hand_matrix = ue_transform(hands[name])
        errors = marker_errors(markers, multiply(hand_matrix, local), sample)
        checks[name] = {"clip": sample["clip"], "time_seconds": sample["time_seconds"], "actual_hand_r_world_matrix_cm": hand_matrix,
                        "marker_errors_cm": errors, "maximum_marker_error_cm": max(errors.values())}
        if max(errors.values()) > POSE_TOLERANCE_CM:
            raise ValueError("Socket does not reproduce actual imported pose markers: " + name + " " + json.dumps(errors))
    result = progress
    result.update({"body": mesh.get_path_name(), "weapon": weapon.get_path_name(), "socket_name": SOCKET, "bone_name": BONE,
              "fitted_socket": fitted, "static_mesh_sections": sections, "actual_static_mesh_vertices_cm": vertices,
              "vertex_check": vertex_check, "pose_checks": checks, "numeric_fit_pass": True, "numeric_socket_pass": False,
              "socket_saved": False, "assembled_render_grip_approved": False, "socket_alignment_approved": False,
              "coordinate_space": "UE mesh component space at identity actor transform; AnimPoseSpaces.WORLD is component space, not a placed game actor",
              "runtime_approved": False, "production_approved": False})
    existing = [mesh.get_socket_by_index(index) for index in range(mesh.num_sockets()) if str(mesh.get_socket_by_index(index).get_editor_property("socket_name")) == SOCKET]
    if len(existing) > 1:
        raise ValueError("Ambiguous duplicate weapon_r sockets; do not overwrite")
    if existing:
        socket = existing[0]
        if socket.get_outer() != mesh or str(socket.get_editor_property("bone_name")) != BONE or matrix_error(ue_transform(socket.get_socket_local_transform()), local) > MATRIX_TOLERANCE:
            raise ValueError("Existing socket conflicts with this fit; refusing to modify it")
    if not apply_socket:
        result["status"] = "actual_ue_numeric_fit_only_no_asset_modified"
        return result
    created = False
    socket = existing[0] if existing else None
    try:
        if socket is None:
            socket = unreal.new_object(unreal.SkeletalMeshSocket, outer=mesh)
            socket.set_socket_parent(mesh, BONE)
            socket.set_socket_local_transform(local_transform)
            mesh.add_socket(socket, False)
            created = True
            automatic_name = str(socket.get_editor_property("socket_name"))
            if automatic_name in {"", "None"} or socket not in [mesh.get_socket_by_index(index) for index in range(mesh.num_sockets())]:
                raise RuntimeError("UE did not add the mesh-owned socket")
            if not unreal.SkeletalMeshEditorSubsystem.rename_socket(mesh, automatic_name, SOCKET):
                raise RuntimeError("UE refused to name the new socket weapon_r")
        if socket.get_outer() != mesh or str(socket.get_editor_property("bone_name")) != BONE:
            raise RuntimeError("Socket is not owned by the isolated mesh/hand_r")
        for name, sample in calibration["poses"].items():
            if sample["clip"] is None:
                actual_matrix = multiply(ue_transform(hands[name]), ue_transform(socket.get_socket_local_transform()))
            else:
                actual_pose = evaluate_pose(unreal, mesh, clips, sample)
                if SOCKET not in [str(value) for value in unreal.AnimPoseExtensions.get_socket_names(actual_pose)]:
                    raise RuntimeError("Actual evaluated mesh pose does not contain weapon_r")
                actual_matrix = ue_transform(unreal.AnimPoseExtensions.get_socket_pose(actual_pose, SOCKET, unreal.AnimPoseSpaces.WORLD))
            errors = marker_errors(markers, actual_matrix, sample)
            checks[name]["actual_socket_marker_errors_cm"] = errors
            checks[name]["actual_socket_world_matrix_cm"] = actual_matrix
            if max(errors.values()) > POSE_TOLERANCE_CM:
                raise ValueError("Actual UE socket composition fails marker gate: " + name)
        if created and not unreal.EditorAssetLibrary.save_loaded_asset(mesh, only_if_is_dirty=False):
            raise RuntimeError("Failed to save isolated mesh socket")
        result.update({"numeric_socket_pass": True, "socket_saved": True, "socket_operation": "created" if created else "reused_identical",
                       "status": "numeric_socket_pass_pending_actual_assembly_render_grip_review"})
        result["body_package_record"] = {"asset_path": mesh.get_path_name(), "package_file": str(body_package),
                                         "bytes": body_package.stat().st_size, "sha256": digest(body_package), "class_name": "SkeletalMesh"}
    except Exception:
        if created and socket is not None:
            current_name = str(socket.get_editor_property("socket_name"))
            unreal.SkeletalMeshEditorSubsystem.remove_socket(mesh, current_name)
        raise
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=os.environ.get("CIVWAR_STONEAXE_MANIFEST"))
    parser.add_argument("--import-report", default=os.environ.get("CIVWAR_STONEAXE_IMPORT_REPORT"))
    parser.add_argument("--report", default=os.environ.get("CIVWAR_STONEAXE_SOCKET_REPORT"))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--evaluate", action="store_true")
    modes.add_argument("--apply", action="store_true")
    args, unknown = parser.parse_known_args()
    if not args.manifest or not args.import_report or not args.report:
        raise ValueError("Provide manifest, completed import-report, and a fresh report path")
    manifest_path, import_path, output = (Path(value).resolve() for value in (args.manifest, args.import_report, args.report))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        report = {"version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(), "manifest": str(manifest_path),
                  "import_report": str(import_path), "mode": "apply" if args.apply else ("evaluate" if args.evaluate else "dry_run"),
                  "numeric_socket_pass": False, "socket_alignment_approved": False, "runtime_approved": False, "production_approved": False,
                  "required_next_gate": "Actual UE assembled weapon/hand renders and both-team game-camera grip review; numeric fitting is not visual or runtime approval.",
                  "tolerances": {"vertex_cm": VERTEX_TOLERANCE_CM, "pose_marker_cm": POSE_TOLERANCE_CM, "source_marker_cm": CALIBRATION_TOLERANCE_CM}}
        try:
            manifest, imported, calibration, check = read_inputs(manifest_path, import_path)
            report.update({"manifest_sha256": digest(manifest_path), "import_report_sha256": digest(import_path),
                           "calibration": manifest["weapon"]["calibration"], "destination": imported["destination"], "source_calibration_check": check,
                           "disk_dependency_validation": imported["result"]["disk_dependency_validation"]})
            if args.apply or args.evaluate:
                import unreal
                report["result"] = {}
                report["result"] = execute(unreal, imported, calibration, check, args.apply, report["result"])
                report["numeric_socket_pass"] = report["result"]["numeric_socket_pass"]
                report["status"] = report["result"]["status"]
            else:
                report["status"] = "validated_frozen_input_only_no_ue_executed"
        except Exception as error:
            report.update({"status": "failed", "error": str(error)})
            raise
        finally:
            handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print("STONEAXE_SOCKET_REPORT " + str(output))


if __name__ == "__main__":
    main()
