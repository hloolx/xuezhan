"""Complete four ankle-plus20 comparison frames without changing the candidate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np


SOURCE_SHA = "960ce41300b9dd6323f451458865cde6770ffe835547c3d2f27b4ad1faa92225"
CHANGES_SHA = "2df6094be4af3dbec3d2d1f104d761f86ffcccac60bc0cdfce91ff0bec6ca52c"


def orthographic_frame(points, direction, padding=1.2):
    direction = np.asarray(direction, dtype=float)
    direction /= np.linalg.norm(direction)
    right = np.cross([0., 0., 1.], direction)
    right /= np.linalg.norm(right)
    up = np.cross(direction, right)
    basis = np.array([right, up, direction])
    projected = points @ basis.T
    center = (projected.min(axis=0) + projected.max(axis=0)) * .5
    size = float(np.ptp(projected[:, :2], axis=0).max() * padding)
    return center @ basis, size, basis


def render(source, changes_path, output):
    import bpy
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import inspect_stone_slinger_rig as rig
    import apply_stone_slinger_rig_transfer as transfer

    records = [rig.record(source), rig.record(changes_path)]
    if records[0]["sha256"] != SOURCE_SHA or records[1]["sha256"] != CHANGES_SHA:
        raise ValueError("Frozen candidate or exact weight delta changed")
    changes = json.loads(changes_path.read_text(encoding="utf-8"))["changes"]
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=str(source))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(meshes) != 1 or len(armatures) != 1:
        raise ValueError("Unexpected candidate layout")
    body, armature = meshes[0], armatures[0]
    transfer.set_pose([armature], [])
    rest = rig.mesh_snapshot(body)
    material_before = rig.materials_report([body])
    names = {group.index: group.name for group in body.vertex_groups}
    actual_weights = [{names[group.group]: group.weight for group in vertex.groups} for vertex in body.data.vertices]
    control = body.copy()
    control.data = body.data.copy()
    control.name = "FootFrame_BeforeControl"
    bpy.context.scene.collection.objects.link(control)
    for row in changes:
        index = row["source_vertex"]
        if actual_weights[index] != row["after_actual_float32"]:
            raise ValueError("Candidate actual weight row differs from its saved audit")
        for name in actual_weights[index]:
            control.vertex_groups[name].remove([index])
        for name, value in row["before"].items():
            control.vertex_groups[name].add([index], value, "REPLACE")
    for obj in list(bpy.context.scene.objects):
        if obj.type in {"LIGHT", "CAMERA"}:
            bpy.data.objects.remove(obj, do_unlink=True)
    helper = rig.module("foot_frame_review", "prepare_tripo_character.py")
    bpy.context.scene.render.threads_mode = "FIXED"
    bpy.context.scene.render.threads = 2
    helper.render_setup(samples=8)
    commands = [("foot_l", (0, 1, 0), 20), ("foot_r", (0, 1, 0), 20)]
    transfer.set_pose([armature], commands)
    points = {"before": transfer.evaluated_positions(control), "after": transfer.evaluated_positions(body)}
    report = {"status": "frame_completion_in_progress", "source": records[0], "exact_changes": records[1],
              "script": rig.record(Path(__file__)), "numeric_candidate_rerun": False, "weight_candidate_modified": False,
              "images": [], "frame_checks": [], "gait_approved": False, "production_approved": False}
    for side, sign in (("left", 1), ("right", -1)):
        indices = np.flatnonzero((sign * rest["positions"][:, 1] > 0) & (rest["positions"][:, 2] < .35))
        direction = (1, sign * 1.8, .5)
        target, framing, _ = orthographic_frame(np.vstack([points["before"][indices], points["after"][indices]]), direction)
        for stage, shown, hidden in (("before", control, body), ("after", body, control)):
            shown.hide_render, hidden.hide_render = False, True
            path = output / ("ankle_plus20_" + side + "_" + stage + "_wide.png")
            helper.render_view(path, [shown], direction, size=512, framing=framing, target=target.tolist())
            projected = np.array([list(world_to_camera_view(bpy.context.scene, bpy.context.scene.camera, Vector(point))) for point in points[stage][indices]])
            margins = np.column_stack((projected[:, :2], 1 - projected[:, :2]))
            minimum_margin = float(margins.min())
            record = {"view": path.name, "side": side, "stage": stage, "complete_geometric_lowboot_vertices": int(len(indices)),
                      "selection": "Rest-side halfspace and all vertices Z<35cm, not weight threshold; includes entire sole, tip, heel and ankle/cuff transition.",
                      "actual_camera_minimum_margin_fraction": minimum_margin, "margin_passed": minimum_margin >= .07,
                      "camera_target_m": target.tolist(), "ortho_scale_m": framing}
            report["frame_checks"].append(record)
            report["images"].append(rig.record(path))
            rig.save(output / "frame_completion_report.json", report)
            if not record["margin_passed"]:
                raise ValueError("Actual full-foot frame margin failed; no acceptance from cropped views")
    transfer.set_pose([armature], [])
    report["surface_preservation"] = transfer.check_rest_normals_uv(rest, rig.mesh_snapshot(body))
    report["PBR_preserved"] = rig.materials_report([body]) == material_before
    report["frozen_inputs_unchanged"] = all(rig.record(Path(row["path"])) == row for row in records)
    if not report["PBR_preserved"] or not report["frozen_inputs_unchanged"]:
        raise ValueError("Frozen candidate changed")
    report["status"] = "four_wide_frames_complete_pending_actual_visual_review"
    rig.save(output / "frame_completion_report.json", report)
    print(json.dumps({"status": report["status"], "images": len(report["images"])}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--changes", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    render(Path(args.source).resolve(), Path(args.changes).resolve(), Path(args.output).resolve())
