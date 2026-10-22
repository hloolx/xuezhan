"""Read-only exact buckle/foot weight regions and hypothetical rigid-seam risk."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_mammoth_rig_transfer as transfer


MODEL = transfer.BRANCH / "rig_transfer_parent_02/Mount_Mammoth_parent_only.glb"
MODEL_SHA = "65c1f2291b1917cafa97ec3b9be3181c7ca9f51a8360330f66e1762ca867effb"


def pose_matrices(document, command):
    worlds, parents = transfer.world_matrices(document)
    nodes = document["nodes"]
    index = next(index for index, node in enumerate(nodes) if node.get("name") == command["bone"])
    axis = transfer.BASIS.T @ np.array(command["axis_world"], dtype=float)
    axis /= np.linalg.norm(axis)
    cross = np.array(((0, -axis[2], axis[1]), (axis[2], 0, -axis[0]), (-axis[1], axis[0], 0)))
    radians = np.deg2rad(command["degrees"])
    rotation = np.eye(3) + np.sin(radians) * cross + (1 - np.cos(radians)) * (cross @ cross)
    delta = np.eye(4)
    delta[:3, :3] = rotation
    delta[:3, 3] = worlds[index][:3, 3] - rotation @ worlds[index][:3, 3]
    actual = {}
    for joint in document["skins"][0]["joints"]:
        ancestor = joint
        while ancestor != index and ancestor in parents:
            ancestor = parents[ancestor]
        actual[joint] = delta @ worlds[joint] if ancestor == index else worlds[joint]
    return np.array([actual[joint] for joint in document["skins"][0]["joints"]])


def analyze(output):
    if transfer.audit_tool.texture.core.record(MODEL)["sha256"] != MODEL_SHA:
        raise ValueError("Frozen parent-only candidate changed")
    if output.exists() or output.parent.resolve() != transfer.BRANCH.resolve() or not output.name.startswith("rig_weight_plan_"):
        raise ValueError("Use a fresh owned rig_weight_plan_* directory")
    document, binary = transfer.read_container(MODEL)
    arrays = transfer.source_arrays(document, binary)
    preparation = json.loads((MODEL.parent / "preparation.json").read_text(encoding="utf-8-sig"))
    physical = arrays["POSITION"] @ transfer.BASIS.T
    native_map, split_pairs, native = transfer.audit_tool.texture.native_identity(arrays)
    identifiers, _ = transfer.audit_tool.texture.core.position_correspondence(arrays["POSITION"], arrays["POSITION"])
    groups = defaultdict(set)
    for index, identifier in enumerate(identifiers):
        groups[int(identifier)].add(index)
    joint_names = [document["nodes"][index]["name"] for index in document["skins"][0]["joints"]]
    inverse = transfer.accessor(document, binary, document["skins"][0]["inverseBindMatrices"])
    pose_skin = {command["name"]: pose_matrices(document, command) @ inverse for command in transfer.POSES}
    actual_positions = {name: transfer.skin_positions(arrays["POSITION"], arrays["JOINTS_0"], arrays["WEIGHTS_0"], matrices)
                        for name, matrices in pose_skin.items()}
    patches = []
    for native_patch in native["plan"]["accessory_patches"]:
        label = str(native_patch["patch_root"])
        indices = preparation["buckle_regions"][label]
        inside = set(indices)
        pairs = sorted({(index, outside) for index in indices for outside in groups[int(identifiers[index])] - inside})
        anchor = "tripo::Spine_2" if label in ("5857", "8674") else "tripo::Spine_0"
        anchor_index = joint_names.index(anchor)
        hypothetical = []
        for name, matrices in pose_skin.items():
            rigid_points = (np.column_stack((arrays["POSITION"][indices], np.ones(len(indices)))) @ matrices[anchor_index].T)[:, :3]
            by_index = dict(zip(indices, rigid_points))
            before = [np.linalg.norm(actual_positions[name][inside_index] - actual_positions[name][outside_index]) for inside_index, outside_index in pairs]
            after = [np.linalg.norm(by_index[inside_index] - actual_positions[name][outside_index]) for inside_index, outside_index in pairs]
            hypothetical.append({"pose": name, "current_max_coincident_seam_gap_m": float(max(before, default=0)),
                                 "rigid_patch_only_max_coincident_seam_gap_m": float(max(after, default=0))})
        weights = [{"source_render_vertex": index, "cleaned_native_vertex": native_map[index],
                    "weights": {joint_names[int(joint)]: float(weight) for joint, weight in zip(arrays["JOINTS_0"][index], arrays["WEIGHTS_0"][index]) if weight > 0}}
                   for index in indices]
        patches.append({"native_patch": int(label), "native_faces": native_patch["face_indices"], "source_render_vertices": indices,
                        "bounds_blender_m": {"min": physical[indices].min(axis=0).tolist(), "max": physical[indices].max(axis=0).tolist()},
                        "exact_current_weights": weights, "coincident_patch_to_surrounding_pairs": pairs,
                        "surrounding_native_vertices": sorted({native_map[outside] for _, outside in pairs}),
                        "hypothetical_rigid_anchor_not_applied": anchor, "pure_GLTF_skin_simulation_not_Blender_actual": hypothetical,
                        "proposal": "Do not apply rigid-patch-only weights if seams open. Inspect these exact surrounding cloth/strap vertices in a color-mask view; only then scope matching contact weights and a small transition region. No whole-body or position-weld edits."})
    tail_index = joint_names.index("bone_32")
    tail_rows = []
    for index in preparation["regions"]["x-1_y-1"]:
        influence = sum(float(weight) for joint, weight in zip(arrays["JOINTS_0"][index], arrays["WEIGHTS_0"][index]) if int(joint) == tail_index)
        if influence > 0:
            tail_rows.append({"source_render_vertex": index, "cleaned_native_vertex": native_map[index], "world_rest_blender_m": physical[index].tolist(),
                              "actual_tail_weight": influence,
                              "weights": {joint_names[int(joint)]: float(weight) for joint, weight in zip(arrays["JOINTS_0"][index], arrays["WEIGHTS_0"][index]) if weight > 0}})
    report = {"asset_id": "Mount_Mammoth", "status": "exact_regions_and_simulated_seam_risks_only_no_weights_applied",
              "candidate": transfer.audit_tool.texture.core.record(MODEL), "patches": patches, "tail_in_hind_negative_y_spatial_foot": tail_rows,
              "tail_scope": "Only source rest X<0,Y<-0.1,Z<0.12m vertices carrying actual bone_32 influence. A future candidate may remove only that influence and renormalize each vertex's remaining actual leg weights; this is not averaging across vertices.",
              "source_changes": 0, "weight_changes": 0, "Blender_runs": 0, "production_approved": False}
    output.mkdir(parents=True, exist_ok=False)
    transfer.audit_tool.texture.core.save(output / "exact_regions.json", report)
    summary = {"status": report["status"], "model_sha256": MODEL_SHA, "exact_regions": transfer.audit_tool.texture.core.record(output / "exact_regions.json"),
               "patches": [{"native_patch": patch["native_patch"], "render_vertices": len(patch["source_render_vertices"]), "native_faces": len(patch["native_faces"]),
                            "coincident_contact_pairs": len(patch["coincident_patch_to_surrounding_pairs"]), "proposed_anchor_not_applied": patch["hypothetical_rigid_anchor_not_applied"],
                            "largest_rigid_patch_only_seam_gap_mm": max(row["rigid_patch_only_max_coincident_seam_gap_m"] for row in patch["pure_GLTF_skin_simulation_not_Blender_actual"]) * 1000} for patch in patches],
               "tail_in_foot_render_vertices": len(tail_rows), "tail_in_foot_native_vertices": len({row["cleaned_native_vertex"] for row in tail_rows}),
               "tail_weight_range": [min(row["actual_tail_weight"] for row in tail_rows), max(row["actual_tail_weight"] for row in tail_rows)] if tail_rows else [],
               "next": "Color-mask exact buckle/cloth contacts before any weights; patch-only rigid assignment would open measured coincident seams. No changes yet."}
    transfer.audit_tool.texture.core.save(output / "summary.json", summary)
    print(json.dumps(summary))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    analyze(args.output.resolve())


if __name__ == "__main__":
    main()
