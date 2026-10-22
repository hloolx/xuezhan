"""Verify and render one independent loop-anchor derivative against the real rig."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_stone_slinger_joint_pinch as prior
import audit_stone_slinger_loop_anchor as audit

base = prior.base
geometry = prior.diameter


def new_mesh(name, specification, parent, material):
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(specification["positions_local_m"], [], specification["triangles"])
    mesh.update()
    uv = mesh.uv_layers.new(name="DiagnosticProjectionUV")
    minimum = np.min(specification["positions_local_m"], axis=0)
    extent = np.maximum(np.ptp(specification["positions_local_m"], axis=0), .001)
    for polygon in mesh.polygons:
        axes = [axis for axis in range(3) if axis != int(np.argmax(np.abs(polygon.normal)))]
        for loop_index in polygon.loop_indices:
            vertex = np.array(mesh.vertices[mesh.loops[loop_index].vertex_index].co)
            uv.data[loop_index].uv = ((vertex - minimum) / extent)[axes]
        polygon.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.matrix_basis = Matrix.Identity(4)
    if material:
        mesh.materials.append(material)
    return obj


def full_interior_certificate(actual, triangles, hand_faces, points, faces):
    initial = geometry.certify_triangle_interiors(actual, triangles, hand_faces, points, faces)
    unresolved = np.array(initial["unresolved_face_ids"], dtype=int)
    refined = geometry.certify_triangle_interiors(actual, triangles, unresolved, points, faces, max_depth=8, budget=12000) if len(unresolved) else None
    return {"initial": initial, "refined_only_initial_unresolved": refined,
            "passed": not initial["failures"] and (refined is None or refined["passed"]), "penetration_limit_m": .002}


def retention_cameras(actual, triangles, retained_points, specification, section, world_matrix):
    center = np.array(section["center_local_m"])
    axis, outward = np.array(section["axis_local"]), np.array(section["outward_local"])
    local = np.array(specification["positions_local_m"])
    relative = local - center
    axial = relative @ axis
    radial = relative - axial[:, None] * axis
    radial_length = np.linalg.norm(radial, axis=1)
    ring_ids = np.flatnonzero((np.abs(axial) <= .002001) & (np.abs(radial_length - section["radius_m"]) <= .002001))
    connector_ids = np.flatnonzero(((relative @ outward) > section["radius_m"] + .0021) & ((relative @ outward) < section["radius_m"] + .030) & (np.abs(axial) < .020))
    if not len(ring_ids) or not len(connector_ids):
        raise ValueError("Missing actual ring/connector vertices for capture visibility")
    tree = prior.BVHTree.FromPolygons(actual.tolist(), triangles.tolist(), all_triangles=True)
    rotation = world_matrix.to_3x3()
    world_axis, world_outward = rotation @ Vector(axis), rotation @ Vector(outward)
    ring_center = np.array(world_matrix @ Vector(center))
    context = actual[np.linalg.norm(actual - ring_center, axis=1) < .048]
    frame_points = np.vstack((context, retained_points[ring_ids], retained_points[connector_ids]))
    selected = []
    for side in (-1, 1):
        choices = []
        for outer_weight in (.3, .6, .9):
            direction = (world_axis * side + world_outward * outer_weight).normalized()
            counts = {}
            for label, ids in (("ring", ring_ids), ("connector", connector_ids)):
                sample_ids = ids[::max(1, len(ids) // 96)]
                visible = 0
                for vertex in retained_points[sample_ids]:
                    origin = Vector(vertex) + direction * 3
                    hit, _, _, distance = tree.ray_cast(origin, -direction, 3.001)
                    if hit is None or distance >= 2.9995:
                        visible += 1
                counts[label] = {"body_unoccluded_vertices": visible, "tested": len(sample_ids)}
            choices.append({"direction": list(direction), "dot_actual_ring_axis": float(direction.dot(world_axis.normalized())),
                            "visibility": counts, "score": min(counts[label]["body_unoccluded_vertices"] / counts[label]["tested"] for label in counts)})
        chosen = max(choices, key=lambda row: row["score"])
        if chosen["score"] == 0:
            raise ValueError("Opposite-side ring and connector camera remains blocked")
        selected.append(chosen)
    return selected, frame_points


def execute(plan_path, certificate_path, output):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    if certificate["source_plan"] != base.rig.record(plan_path) or not all(certificate["checks"].values()):
        raise ValueError("Fixed geometry requires its exact bounded pure certificate")
    for key in ("source", "weapon_source", "root_review"):
        if base.rig.record(Path(plan[key]["path"])) != plan[key]:
            raise ValueError("Frozen input drift: " + key)
    prep = json.loads((base.plan_math.BRANCH / "preparation_05/grip_preparation.json").read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=plan["source"]["path"])
    body, = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    armature, = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    base.transfer.set_pose([armature], [])
    baseline = base.rig.mesh_snapshot(body)
    weights = base.foot.weights_of(body)
    encoded_normals = base.foot.encoded_normals(body.data)
    materials = base.rig.materials_report([body])
    bones_before = base.foot.rest_bones(armature)
    weapon, weapon_baseline, _ = base.append_existing_weapon(prep)
    source_world = Matrix(plan["basis_columns"]).to_4x4()
    source_world.translation = Vector(plan["root_rest_m"])
    mount = base.bone_world(armature, "hand_r").inverted() @ source_world
    socket = bpy.data.objects.new("weapon_r", None)
    bpy.context.scene.collection.objects.link(socket)
    socket.parent, socket.parent_type, socket.parent_bone = armature, "BONE", "hand_r"
    bpy.context.view_layer.update()
    socket.matrix_world = source_world
    bpy.context.view_layer.update()
    weapon["Weapon_Sling"].parent = socket
    weapon["Weapon_Sling"].matrix_parent_inverse = Matrix.Identity(4)
    weapon["Weapon_Sling"].matrix_basis = Matrix.Identity(4)
    new_objects = {}
    for name, specification in plan["meshes"].items():
        source_cord = weapon["cord_N1" if name == "retained_loop_cord" else "cord_P1"]
        material = source_cord.data.materials[0] if source_cord.data.materials else None
        new_objects[name] = new_mesh(name, specification, weapon["Weapon_Sling"], material)
    for name in ("cord_N1", "cord_P1"):
        weapon[name].hide_render = True
        weapon[name].hide_set(True)
    weapon["retained_terminal"].location = plan["independent_controls"]["retained_anchor"]
    weapon["release_terminal"].location = plan["independent_controls"]["released_tip"]
    base.set_bone_world_rotation = prior.set_rotation_channels
    modified = dict(prep, initial_grip_commands=plan["commands"])
    arms = base.pose(armature, modified, "idle")
    actual, triangles = base.evaluated_snapshot(body)
    if not np.array_equal(triangles, base.plan_math.texture.read_glb(base.rig.SOURCE)[2]["indices"]):
        raise ValueError("Actual face IDs differ from explicitly mapped source")
    hand_ids = np.array([index for index, row in enumerate(weights) if any(name.endswith("_r") and name.startswith(("hand_", "index_", "thumb_", "middle_", "ring_", "pinky_")) and value > 0 for name, value in row.items())])
    hand_faces = np.flatnonzero(np.all(np.isin(triangles, hand_ids), axis=1))
    report = {"asset_id": "Unit_StoneSlinger", "status": "actual_loop_anchor_candidate_pending_visual_review", "script": base.rig.record(Path(__file__)),
              "plan": base.rig.record(plan_path), "pure_certificate": base.rig.record(certificate_path), "source": plan["source"], "original_weapon": plan["weapon_source"],
              "pose": "limited_idle_only", "arms": arms, "actual_cords": {}, "images": [], "grip_approved": False, "gait_approved": False, "production_approved": False,
              "scope": "One new branch-loop8mmmain/4mmloop derivative. Original cords hidden but Basis/Draw/UV preserved. No bodyweights/PBR change; no gait/attack/releaseanimation.",
              "derivative_UV": "New dominant-face diagnostic projection only; original weapon UV archive unchanged. Not a final baked-texture/packing approval."}
    report_path = output / "loop_anchor_report.json"
    cord_surfaces = {}
    for name, obj in new_objects.items():
        points, faces = base.evaluated_snapshot(obj)
        desired = np.array([list(weapon["Weapon_Sling"].matrix_world @ Vector(point)) for point in plan["meshes"][name]["positions_local_m"]])
        if not np.array_equal(faces, plan["meshes"][name]["triangles"]):
            raise ValueError("Actual new triangles changed; do not reuse a different pure certificate")
        error = float(np.linalg.norm(points - desired, axis=1).max())
        if error > 3e-6:
            raise ValueError("Actual independent derivative positions differ from frozen plan")
        cord_surfaces[name] = (points, faces)
        report["actual_cords"][name] = {"vertices": len(points), "triangles": len(faces), "frozen_geometry_max_error_m": error,
                                        "full_face_interior": full_interior_certificate(actual, triangles, hand_faces, points, faces),
                                        "hand_triangle_crossings": geometry.mesh_crossings(actual, triangles, hand_faces, points, faces),
                                        "self_crossings": geometry.joint.pair_crossings(points, faces, np.arange(len(faces)), np.arange(len(faces)), np.arange(len(points)))}
        base.rig.save(report_path, report)
    retained_points, retained_faces = cord_surfaces["retained_loop_cord"]
    released_points, released_faces = cord_surfaces["released_cord"]
    report["actual_retained03_contact"] = audit.fixed_contact_samples(actual, triangles, weights, "pinky_03_r", retained_points, retained_faces)
    source_report = json.loads(Path(prep["actual_rig_transfer_report"]["path"]).read_text(encoding="utf-8"))
    bones = source_report["actual_final_skeleton"]["armatures"][0]["bones"]
    pads = {finger: geometry.joint.pad_faces(finger, baseline["positions"], triangles, weights, bones, np.array(prep["hand_frame"]["palm"])) for finger in ("index", "thumb")}
    pinch = np.array(plan["true03_contacts"]["index"]["barycentric"])
    report["actual_release03_contacts"] = {}
    contact_radials = []
    first_contact = actual[triangles[plan["true03_contacts"]["index"]["triangle"]]].mean(axis=0)
    second_contact = actual[triangles[plan["true03_contacts"]["thumb"]["triangle"]]].mean(axis=0)
    pinch_center = (first_contact + second_contact) * .5
    for finger, ids in pads.items():
        samples, normals = geometry.joint.face_samples(actual, triangles[ids])
        distances, nearest = geometry.joint.nearest_surface(samples, released_points[released_faces])
        selected = int(np.argmin(distances))
        radial = base.plan_math.normalize(nearest[selected] - pinch_center)
        contact_radials.append(radial)
        report["actual_release03_contacts"][finger] = {"triangle": int(ids[selected]), "barycentric": pinch.tolist(), "gap_m": float(distances[selected]), "normal_dot_radial": float(np.dot(normals[selected], radial))}
    report["actual_opposition_dot"] = float(np.dot(*contact_radials))
    report["between_cords_crossings"] = geometry.mesh_crossings(retained_points, retained_faces, np.arange(len(retained_faces)), released_points, released_faces)
    matrices = {bone.name: np.array(base.bone_world(armature, bone.name) @ armature.data.bones[bone.name].matrix_local.inverted()) for bone in armature.pose.bones}
    homogeneous = np.column_stack((baseline["positions"], np.ones(len(actual))))
    predicted = np.array([sum((matrices[bone] @ point)[:3] * weight for bone, weight in row.items()) for point, row in zip(homogeneous, weights)])
    report["actual_body_LBS_error_m"] = float(np.linalg.norm(actual - predicted, axis=1).max())
    report["pose_scale_channels_exactly_one"] = all(tuple(bone.scale) == (1, 1, 1) for bone in armature.pose.bones)
    report["actual_weapon_mount_error"] = max(abs(value) for row in (weapon["Weapon_Sling"].matrix_world - base.bone_world(armature, "hand_r") @ mount) for value in row)
    report["body_orientation"] = base.geometry.triangle_orientation(baseline["positions"], actual, triangles, base.foot.weight_linear(weights, matrices))
    mapping = json.loads(Path(source_report["mapping"]["path"]).read_text(encoding="utf-8"))
    native_ids = np.array([mapping["source_render_vertex_to_cleaned_native_vertex"][str(index)] for index in range(len(weights))])
    hand_crossings = base.foot.exact_intersections(actual, triangles, native_ids, np.flatnonzero(np.any(np.isin(triangles, hand_ids), axis=1)))
    cuff, digits = [], []
    for pair in hand_crossings["proper_crossing_pairs"]:
        influence = max(sum(value for name, value in weights[int(vertex)].items() if name.startswith("lowerarm") and name.endswith("_r")) for triangle in pair for vertex in triangles[triangle])
        (cuff if influence > .15 else digits).append(pair)
    report["separate_hand_crossings"] = {"wrist_cuff_pairs": cuff, "other_hand_digit_pairs": digits}
    report["checks"] = {"true03_release_contact_within2mm": max(row["gap_m"] for row in report["actual_release03_contacts"].values()) <= .002,
                        "true03_retained_contact_within2mm": report["actual_retained03_contact"]["gap_m"] <= .002,
                        "opposed_distal_pads": report["actual_opposition_dot"] <= -.5,
                        "true03_pad_normals_face_cord": all(row["normal_dot_radial"] <= -.3 for row in report["actual_release03_contacts"].values()),
                        "full_face_interiors_within2mm": all(row["full_face_interior"]["passed"] for row in report["actual_cords"].values()),
                        "no_cord_self_crossings": all(not row["self_crossings"] for row in report["actual_cords"].values()),
                        "cords_do_not_cross_each_other": not report["between_cords_crossings"], "no_digit_crossings": not digits}
    base.rig.save(report_path, report)
    if not report["pose_scale_channels_exactly_one"] or report["actual_body_LBS_error_m"] > 3e-6 or report["actual_weapon_mount_error"] > 3e-6:
        raise ValueError("Source physical pose/scale contract failed; do not render")
    source_gate = base.transfer.check_rest_normals_uv(baseline, base.rig.mesh_snapshot(body))
    source_gate.update({"body_weights_exact": weights == base.foot.weights_of(body), "encoded_normals_exact": encoded_normals == base.foot.encoded_normals(body.data),
                        "body_PBR_exact": materials == base.rig.materials_report([body]), "rest_bones_exact": bones_before == base.foot.rest_bones(armature),
                        "original_weapon_Basis_Draw_UV_geometry_exact": all(base.local_weapon_data(weapon[name]) == value for name, value in weapon_baseline.items())})
    report["pre_render_source_gate"] = source_gate
    base.rig.save(report_path, report)
    if not all(source_gate.values()):
        raise ValueError("Original source preservation failed before rendering")
    for obj in list(bpy.context.scene.objects):
        if obj.type in {"CAMERA", "LIGHT"}:
            bpy.data.objects.remove(obj, do_unlink=True)
    renderer = base.rig.module("slinger_loop_renderer", "prepare_tripo_character.py")
    renderer.render_setup(samples=8)
    bpy.context.scene.render.threads_mode, bpy.context.scene.render.threads = "FIXED", 2
    objects = [body, weapon["leather_pouch"], weapon["loaded_stone"]] + list(new_objects.values())
    display_ids = np.array([index for index, row in enumerate(weights) if sum(value for name, value in row.items() if name.endswith("_r") and name.startswith(("hand_", "index_", "thumb_", "middle_", "ring_", "pinky_"))) > .5])
    cameras = prior.camera_candidates(actual, triangles, armature, prep, display_ids, pads)
    if any(camera["score"] == 0 for camera in cameras):
        raise ValueError("Blocked true-pad camera")
    report["release_camera_visibility"] = cameras
    ring_cameras, ring_frame = retention_cameras(actual, triangles, retained_points, plan["meshes"]["retained_loop_cord"], plan["retention_surface_section"], weapon["Weapon_Sling"].matrix_world)
    report["retention_camera_visibility"] = ring_cameras
    directions = [("release_pad_" + str(index + 1), camera["direction"], actual[display_ids]) for index, camera in enumerate(cameras)]
    directions.extend(("retained_ring_side_" + str(index + 1), camera["direction"], ring_frame) for index, camera in enumerate(ring_cameras))
    for name, direction, frame_points in directions:
        target, framing, _ = base.framing_math.orthographic_frame(frame_points, direction, padding=1.45)
        path = output / (name + ".png")
        renderer.render_view(path, objects, direction, size=512, framing=framing, target=target.tolist())
        report["images"].append(base.rig.record(path))
    report["preservation"] = base.transfer.check_rest_normals_uv(baseline, base.rig.mesh_snapshot(body))
    report["preservation"].update({"body_weights_exact": weights == base.foot.weights_of(body), "encoded_normals_exact": encoded_normals == base.foot.encoded_normals(body.data),
                                    "body_PBR_exact": materials == base.rig.materials_report([body]), "rest_bones_exact": bones_before == base.foot.rest_bones(armature),
                                    "original_weapon_Basis_Draw_UV_geometry_exact": all(base.local_weapon_data(weapon[name]) == value for name, value in weapon_baseline.items()),
                                    "frozen_body_file_unchanged": base.rig.record(Path(plan["source"]["path"])) == plan["source"],
                                    "frozen_weapon_file_unchanged": base.rig.record(Path(plan["weapon_source"]["path"])) == plan["weapon_source"]})
    base.rig.save(report_path, report)
    if not all(report["preservation"].values()):
        raise ValueError("Frozen source preservation failed")
    blend = output / "Unit_StoneSlinger_LoopAnchorDiagnostic.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    report["blend"] = base.rig.record(blend)
    base.rig.save(report_path, report)
    print(json.dumps({"status": report["status"], "checks": report["checks"], "images": len(report["images"])}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    execute(Path(args.plan).resolve(), Path(args.certificate).resolve(), Path(args.output).resolve())
