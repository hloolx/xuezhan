"""Isolated, articulated RockTower candidate; never edits gameplay or source assets."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "RawAssets/Art/Tripo_v01"
OUTPUT_ROOT = ART / "tripo_processed/rock_tower_v01"
ASSET_ID = "Turret_RockTower"
PIVOT = (-0.04, 0.0, 0.51)
READY_ANGLE = -35.0
FOLLOW_ANGLE = 40.0
RELOAD_ANGLE = -65.0
CYCLE_SECONDS = 2.4
RELEASE_LOCAL = (0.035, 0.0, 0.57)
POST_CENTRE_Z = .38
POST_DIMENSIONS = (.14, .13, .48)
AXLE_RADIUS = .052
BORE_RADIUS = .066
PLATFORMS_CM = {
    "front_negative_y": (148.40097, -191.79658, 157.49995),
    "front_positive_y": (147.91031, 195.37494, 157.55195),
    "rear": (-158.95849, -.11456, 317.55337),
}
REFERENCE_HASHES = {
    "front": "9d7baa8592748c693109f4bea2fb6441a747d88bb3f679dee1c7e2291d110c38",
    "left": "e2b35cb2eab865ff0508350711655436f7d1c77097b3a255e5bacf60fb78de18",
    "back": "4460b0c78b0fcf9889439e1594f68ad4ae5b40db7ebffe5c3f146ca6e0c3d5e7",
}
HIERARCHY = {
    ASSET_ID: None,
    "base": ASSET_ID,
    "posts": "base",
    "fixed_bindings": "base",
    "arm_pivot": "base",
    "throwing_arm": "arm_pivot",
    "cup": "throwing_arm",
    "loaded_stone": "cup",
    "release_point": "cup",
    "moving_bindings": "throwing_arm",
    "team_cloth": "base",
}


def file_record(path):
    path = Path(path).resolve()
    return {"file": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def safe_output(path):
    path = Path(path).resolve()
    if not path.is_relative_to(OUTPUT_ROOT.resolve()) or path == OUTPUT_ROOT.resolve():
        raise ValueError("Output must be a fresh child of rock_tower_v01")
    return path


def rotate_y(point, angle_degrees):
    angle = math.radians(angle_degrees)
    cosine, sine = math.cos(angle), math.sin(angle)
    return (cosine * point[0] + sine * point[2], point[1],
            -sine * point[0] + cosine * point[2])


def arm_point(point, angle_degrees):
    rotated = rotate_y(point, angle_degrees)
    return tuple(rotated[axis] + PIVOT[axis] for axis in range(3))


def smooth_transition(start, end, fraction):
    fraction = min(1.0, max(0.0, fraction))
    return start + (end - start) * fraction * fraction * (3.0 - 2.0 * fraction)


def sample_cycle(elapsed, enabled=True):
    if not math.isfinite(elapsed):
        raise ValueError("Elapsed time must be finite")
    if not enabled:
        return {"phase": "disabled", "angle_degrees": READY_ANGLE, "stone_visible": False}
    if elapsed < 0:
        return {"phase": "ready", "angle_degrees": READY_ANGLE, "stone_visible": True}
    if elapsed < 0.16:
        angle = smooth_transition(READY_ANGLE, FOLLOW_ANGLE, elapsed / 0.16)
        phase = "released_follow_through"
    elif elapsed < 0.30:
        angle, phase = FOLLOW_ANGLE, "follow_through_hold"
    elif elapsed < 0.95:
        angle = smooth_transition(FOLLOW_ANGLE, RELOAD_ANGLE, (elapsed - 0.30) / 0.65)
        phase = "return_empty"
    elif elapsed < 1.30:
        angle, phase = RELOAD_ANGLE, "reload_stone"
    elif elapsed < 2.10:
        angle = smooth_transition(RELOAD_ANGLE, READY_ANGLE, (elapsed - 1.30) / 0.80)
        phase = "return_ready"
    else:
        angle, phase = READY_ANGLE, "ready"
    return {"phase": phase, "angle_degrees": angle, "stone_visible": elapsed >= 1.20}


def swept_point_bounds(points, low_degrees=RELOAD_ANGLE, high_degrees=FOLLOW_ANGLE):
    if low_degrees > high_degrees or not points:
        raise ValueError("Invalid sweep")
    low, high = math.radians(low_degrees), math.radians(high_degrees)
    values = []
    for point in points:
        angles = [low, high]
        for offset in (math.atan2(point[2], point[0]), math.atan2(-point[0], point[2])):
            for multiple in range(-4, 5):
                angle = offset + multiple * math.pi
                if low <= angle <= high:
                    angles.append(angle)
        values.extend(arm_point(point, math.degrees(angle)) for angle in angles)
    return {"min": [min(point[axis] for point in values) for axis in range(3)],
            "max": [max(point[axis] for point in values) for axis in range(3)]}


def aabb_separation(first, second):
    return max(max(second["min"][axis] - first["max"][axis],
                   first["min"][axis] - second["max"][axis]) for axis in range(3))


def cup_geometry(segments=16):
    if segments < 8:
        raise ValueError("Cup needs at least eight sectors")
    outer = [(-0.085, 0.09), (-0.065, 0.58), (-0.015, 0.90), (0.060, 1.0)]
    inner = [(-0.055, 0.08), (-0.035, 0.46), (0.005, 0.74), (0.060, 0.82)]
    vertices, faces, sectors = [], [], []
    for profile in (outer, inner):
        for axial, radius in profile:
            for sector in range(segments):
                angle = sector * math.tau / segments
                vertices.append((axial, radius * 0.127 * math.cos(angle),
                                 0.57 + radius * 0.145 * math.sin(angle)))
    ring_count = len(outer)
    for shell in range(2):
        offset = shell * ring_count * segments
        for ring in range(ring_count - 1):
            for sector in range(segments):
                following = (sector + 1) % segments
                face = (offset + ring * segments + sector, offset + ring * segments + following,
                        offset + (ring + 1) * segments + following, offset + (ring + 1) * segments + sector)
                faces.append(face if shell == 0 else tuple(reversed(face)))
                sectors.append(sector % 3 if shell == 0 else 3)
    faces.append(tuple(reversed(range(segments))))
    faces.append(tuple(ring_count * segments + sector for sector in range(segments)))
    sectors.extend((0, 3))
    outer_last = (ring_count - 1) * segments
    inner_last = (2 * ring_count - 1) * segments
    for sector in range(segments):
        following = (sector + 1) % segments
        faces.append((outer_last + sector, outer_last + following,
                      inner_last + following, inner_last + sector))
        sectors.append(1)
    return vertices, faces, sectors


def cup_binding_geometry(axial, segments=32, sides=6):
    profile = [(-.085, .09), (-.065, .58), (-.015, .90), (.060, 1.0)]
    radius = None
    for start, end in zip(profile, profile[1:]):
        if start[0] <= axial <= end[0]:
            fraction = (axial - start[0]) / (end[0] - start[0])
            radius = start[1] + fraction * (end[1] - start[1])
            break
    if radius is None:
        raise ValueError("Binding must lie on the cup shell")
    vertices, faces = [], []
    for segment in range(segments):
        angle = segment * math.tau / segments
        for side in range(sides):
            cross = side * math.tau / sides
            offset = .009 * math.sin(cross)
            vertices.append((axial + .009 * math.cos(cross),
                             (.127 * radius + .006 + offset) * math.cos(angle),
                             .57 + (.145 * radius + .006 + offset) * math.sin(angle)))
    for segment in range(segments):
        for side in range(sides):
            current = segment * sides + side
            following = segment * sides + (side + 1) % sides
            next_current = ((segment + 1) % segments) * sides + side
            next_following = ((segment + 1) % segments) * sides + (side + 1) % sides
            faces.append((current, following, next_following, next_current))
    return vertices, faces


def support_result(gaps_m, missing, non_upward, tolerance_m=.002):
    if not gaps_m:
        return {"passed": False, "reason": "no support samples", "sample_count": 0}
    return {"sample_count": len(gaps_m), "missing_rays": missing, "non_upward_hits": non_upward,
            "min_gap_mm": min(gaps_m) * 1000, "max_gap_mm": max(gaps_m) * 1000,
            "penetrating_samples": sum(gap < -tolerance_m for gap in gaps_m),
            "floating_samples": sum(gap > tolerance_m for gap in gaps_m),
            "within_tolerance_samples": sum(abs(gap) <= tolerance_m for gap in gaps_m),
            "tolerance_mm": tolerance_m * 1000,
            "passed": not missing and not non_upward and all(abs(gap) <= tolerance_m for gap in gaps_m)}


def clipped_surface_polygon(polygon, rectangle):
    result = [tuple(point) for point in polygon]
    for axis, limit, keep_above in ((0, rectangle[0], True), (0, rectangle[1], False),
                                    (1, rectangle[2], True), (1, rectangle[3], False)):
        previous_result, result = result, []
        if not previous_result:
            break
        for previous, current in zip(previous_result[-1:] + previous_result[:-1], previous_result):
            previous_inside = previous[axis] >= limit if keep_above else previous[axis] <= limit
            current_inside = current[axis] >= limit if keep_above else current[axis] <= limit
            if previous_inside != current_inside:
                fraction = (limit - previous[axis]) / (current[axis] - previous[axis])
                crossing = tuple(previous[index] + fraction * (current[index] - previous[index]) for index in range(3))
                result.append(crossing)
            if current_inside:
                result.append(current)
        cleaned = []
        for point in result:
            if not cleaned or math.dist(point, cleaned[-1]) > 1e-9:
                cleaned.append(point)
        if len(cleaned) > 1 and math.dist(cleaned[0], cleaned[-1]) < 1e-9:
            cleaned.pop()
        result = cleaned
    return result


def projected_area(polygon):
    return sum(first[0] * second[1] - second[0] * first[1]
               for first, second in zip(polygon, polygon[1:] + polygon[:1])) / 2


def matched_pad_geometry(patches, rectangle, top_z):
    vertices, bottom_faces, source_faces, indices = [], [], [], {}
    for source_face, polygon in patches:
        if projected_area(polygon) < 0:
            polygon = list(reversed(polygon))
        face_indices = []
        for point in polygon:
            key = tuple(round(value, 7) for value in point)
            if key not in indices:
                indices[key] = len(vertices)
                vertices.append(tuple(point))
            face_indices.append(indices[key])
        for offset in range(1, len(face_indices) - 1):
            face = (face_indices[0], face_indices[offset], face_indices[offset + 1])
            if projected_area([vertices[index] for index in face]) > 1e-12:
                bottom_faces.append(face)
                source_faces.append(source_face)
    area = sum(projected_area([vertices[index] for index in face]) for face in bottom_faces)
    target_area = (rectangle[1] - rectangle[0]) * (rectangle[3] - rectangle[2])
    if target_area <= 0 or abs(area - target_area) > max(1e-10, target_area * 1e-6):
        raise ValueError("Pad footprint lacks exactly one complete clipped Base surface")
    if min(top_z - point[2] for point in vertices) < .004999:
        raise ValueError("Matched support requires at least 5 mm actual timber thickness")
    edges = {}
    for face in bottom_faces:
        for first, second in zip(face, face[1:] + face[:1]):
            key = tuple(sorted((first, second)))
            edges.setdefault(key, []).append((first, second))
    if any(len(directions) > 2 for directions in edges.values()):
        raise ValueError("Clipped Base pad contains a nonmanifold seam")
    count = len(vertices)
    vertices += [(point[0], point[1], top_z) for point in vertices]
    faces = [tuple(reversed(face)) for face in bottom_faces]
    faces += [tuple(index + count for index in face) for face in bottom_faces]
    faces += [(first, second, second + count, first + count)
              for directions in edges.values() if len(directions) == 1 for first, second in directions]
    return vertices, faces, {"source_base_faces": source_faces, "bottom_triangles": len(bottom_faces),
                             "projected_area_m2": area, "minimum_thickness_mm": min(top_z - point[2] for point in vertices[:count]) * 1000,
                             "maximum_thickness_mm": max(top_z - point[2] for point in vertices[:count]) * 1000}


def mount_lift(pad_height_offsets, clearance_requirements, maximum_m=.020):
    values = list(pad_height_offsets) + list(clearance_requirements)
    if not pad_height_offsets or any(not math.isfinite(value) for value in values):
        raise ValueError("Lift needs finite actual surface evidence")
    required = max(.005, max(pad_height_offsets) + .005, max(clearance_requirements, default=0))
    result = math.ceil((required - 1e-10) * 1000) / 1000
    if result > maximum_m:
        raise ValueError("Required local lift exceeds the declared 20 mm maximum; no hidden clamp")
    return result


def source_contract():
    references = []
    for role, expected in REFERENCE_HASHES.items():
        path = ART / "prepared_tripo_canonical" / ASSET_ID / (role + ".png")
        record = file_record(path)
        if record["sha256"] != expected:
            raise ValueError("Canonical input changed: " + role)
        references.append({**record, "api_role": role, "design_role": "right" if role == "left" else role})
    return references


def base_input_contract(base_manifest):
    manifest = json.loads(Path(base_manifest).read_text(encoding="utf-8-sig"))
    matches = [item for item in manifest["assets"] if item["id"] == "Base_Stone"]
    if len(matches) != 1:
        raise ValueError("Expected exactly one Base_Stone manifest entry")
    asset = matches[0]
    path = (ROOT / asset["file"]).resolve()
    if not path.is_relative_to((ART / "tripo_processed/base_stone_v01").resolve()):
        raise ValueError("Base input must be the existing processed Base_Stone")
    record = file_record(path)
    if record["sha256"] != asset["sha256"]:
        raise ValueError("Frozen Base_Stone hash mismatch")
    return {"manifest": file_record(base_manifest), "model": record,
            "platforms_blender_cm": PLATFORMS_CM, "base_modified": False,
            "source_material_overrides": asset.get("runtime_material_overrides", {}),
            "support_sample_grid_cm": 1, "support_tolerance_mm": 2,
            "full_angle_range_degrees": [RELOAD_ANGLE, FOLLOW_ANGLE], "angle_step_degrees": .5}


def mechanism_plan():
    return {
        "schema_version": 1, "asset_id": ASSET_ID, "status": "script_math_only_no_mesh_execution",
        "route": "mechanism_dcc", "references": source_contract(),
        "source_tools": [file_record(ROOT / "Tools/Blender/build_weapons.py")],
        "units": "metres", "forward": "+X", "up": "+Z", "arm_axis": "+Y",
        "hierarchy": HIERARCHY, "nominal_base_dimensions_cm": [80, 70, 15],
        "pivot_m": PIVOT, "sweep_degrees": [RELOAD_ANGLE, FOLLOW_ANGLE],
        "bearing": {"post_dimensions_m": POST_DIMENSIONS, "post_centre_z_m": POST_CENTRE_Z,
                    "axle_radius_m": AXLE_RADIUS, "bore_radius_m": BORE_RADIUS,
                    "real_boolean_bores": True, "radial_clearance_m": BORE_RADIUS - AXLE_RADIUS},
        "ready_and_release_angle_degrees": READY_ANGLE,
        "release_local_m": RELEASE_LOCAL, "release_world_m": arm_point(RELEASE_LOCAL, READY_ANGLE),
        "release_forward_direction": rotate_y((1, 0, 0), READY_ANGLE),
        "timing": {"source": "FireSeq already fired", "release_seconds": 0.0,
                   "cycle_seconds": CYCLE_SECONDS, "ready_again_seconds": 2.1,
                   "stone_returns_seconds": 1.2, "client_notify_causes_damage": False},
        "cycle_samples_60fps": [{"time_seconds": frame / 60, **sample_cycle(frame / 60)} for frame in range(145)],
        "design_resolution": "One true forward/up-open hollow cup, not contradictory open fronts on both ends; this resolves reference ambiguity and requires visual review.",
        "candidate_revision": "v02_attached_cup_wrappings_and_supported_cloth_hanger",
        "checks_to_execute": ["actual mesh bounds and manifold topology", "continuous rigid swept-AABB separation versus fixed supports",
                              "sampled actual triangle overlap for unresolved pairs with explicit joint exclusions",
                              "GLB and FBX roundtrip scale and named anchors", "optional actual Base_Stone three-platform sweep"],
        "limitations": ["No exact mechanical power simulation; decorative torsion ropes are not gameplay physics.",
                        "Geometry, UV, motion and images remain unexecuted until the Blender lease.",
                        "No UE sockets, no authority changes, no inferred network phase approval."],
        "production_approved": False, "approved_for_ue_import": False,
    }


def build_parts():
    import bpy
    from mathutils import Vector
    helper_spec = importlib.util.spec_from_file_location("cw_weapon_helpers", ROOT / "Tools/Blender/build_weapons.py")
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1
    scene.world = bpy.data.worlds.new("World")
    anchors = {}
    for name, parent in HIERARCHY.items():
        anchors[name] = helper.anchor(name, parent=anchors.get(parent), role="RockTower assembly " + name)
    fixed, moving, joints = [], [], []

    def register(obj, movable=False, joint=False):
        obj["mechanism_group"] = "joint" if joint else "moving" if movable else "fixed"
        (joints if joint else moving if movable else fixed).append(obj)
        return obj

    def block(name, location, dimensions, material, parent="base", movable=False, edge=0.009):
        return register(helper.cube(name, location, dimensions, material, anchors[parent], edge), movable)

    def beam(name, start, end, width, depth, parent="posts"):
        midpoint = (Vector(start) + Vector(end)) / 2
        obj = block(name, midpoint, (width, depth, (Vector(end) - Vector(start)).length), "wood", parent)
        obj.rotation_euler = (Vector(end) - Vector(start)).to_track_quat("Z", "Y").to_euler()
        return obj

    for side in (-1, 1):
        suffix = "N" if side < 0 else "P"
        block("side_rail_" + suffix, (0, side * .29, .09), (.80, .12, .15), "wood")
        block("cross_rail_" + suffix, (side * .34, 0, .09), (.12, .46, .15), "wood_light")
        post = block("post_" + suffix, (-.04, side * .255, POST_CENTRE_Z), POST_DIMENSIONS, "wood_light", "posts", edge=.014)
        for end in (-1, 1):
            beam("brace_" + suffix + str(end), (end * .32, side * .255, .16), (-.04, side * .255, .46), .075, .08)
            block("corner_cap_" + suffix + str(end), (end * .345, side * .295, .087), (.108, .118, .17), "iron", edge=.012)
            block("corner_inset_" + suffix + str(end), (end * .401, side * .295, .087), (.009, .085, .12), "steel", edge=.004)
            register(helper.ico("rivet_" + suffix + str(end), (end * .412, side * .295, .087), (.009, .023, .023), "iron", anchors["base"], 1))
            block("foot_" + suffix + str(end), (end * .27, side * .27, .0125), (.13, .12, .025), "wood")
        for wrap in range(3):
            register(helper.ring("post_binding_" + suffix + str(wrap), (-.04, side * .255, .185 + wrap * .021), .086, .011, "hide", (0, 0, 1), anchors["fixed_bindings"]))
        band = block("bearing_band_" + suffix, (-.04, side * .255, .51), (.175, .141, .17), "iron", "posts", edge=.006)
        cutter = helper.rod("TEMP_bearing_bore_" + suffix, (-.04, side * .15, .51), (-.04, side * .39, .51), BORE_RADIUS, None, vertices=24)
        cutter["civwar_part"] = False
        cutter["temporary_bore_cutter"] = True
        cutter.hide_render = True
        for target in (post, band):
            modifier = target.modifiers.new("True_transverse_bearing_bore", "BOOLEAN")
            modifier.operation = "DIFFERENCE"
            modifier.solver = "EXACT"
            modifier.object = cutter
        register(helper.ring("bearing_face_" + suffix, (-.04, side * .331, .51), .075, .017, "steel", (0, 1, 0), anchors["posts"]), joint=True)
        register(helper.rod("axle_pin_" + suffix, (-.04, side * .34, .51), (-.04, side * .36, .51), .036, "iron", anchors["posts"], vertices=8), joint=True)
        for strand in range(2):
            path = []
            for index in range(73):
                fraction = index / 72
                angle = fraction * math.tau * 3 + strand * math.pi
                path.append((-.04 + .082 * math.cos(angle), side * (.12 + .075 * fraction), .51 + .082 * math.sin(angle)))
            register(helper.tube("torsion_rope_" + suffix + str(strand), path, .009, "hide", anchors["fixed_bindings"], sides=6))
    for index in range(4):
        block("deck_plank_" + str(index), (-.225 + index * .15, 0, .12), (.145, .45, .075), "wood_light" if index % 2 else "wood", edge=.004)
    for side in (-1, 1):
        for height in (.065, .11):
            block("broad_rail_grain_" + str(side) + str(height), (0, side * .351, height), (.59, .0025, .005), "wood_light", edge=.001)
    block("cloth_hanger", (.35, 0, .28), (.085, .30, .047), "wood_light")
    block("cloth_hanger_band", (.398, 0, .28), (.013, .30, .038), "iron", edge=.003)
    for side in (-1, 1):
        block("cloth_hanger_bracket_" + str(side), (.35, side * .105, .21), (.035, .035, .14), "wood", edge=.004)
    cloth_outline = [(-.112, .26), (.112, .26), (.115, .07), (.08, .085), (0, .13), (-.103, .06)]
    cloth_vertices = [(axial, across, vertical) for axial in (.407, .412) for across, vertical in cloth_outline]
    count = len(cloth_outline)
    cloth_faces = [tuple(reversed(range(count))), tuple(range(count, count * 2))]
    cloth_faces += [(index, (index + 1) % count, (index + 1) % count + count, index + count) for index in range(count)]
    mesh = bpy.data.meshes.new("team_cloth_mesh")
    mesh.from_pydata(cloth_vertices, [], cloth_faces)
    cloth = bpy.data.objects.new("team_cloth_panel", mesh)
    scene.collection.objects.link(cloth)
    register(helper.finish(cloth, cloth.name, "cobalt", anchors["team_cloth"]))
    register(helper.rod("axle_core", (0, -.345, 0), (0, .345, 0), AXLE_RADIUS, "wood", anchors["arm_pivot"], vertices=12), movable=True, joint=True)
    register(helper.rod("arm_hub", (0, -.11, 0), (0, .11, 0), .106, "wood_light", anchors["throwing_arm"], vertices=14), movable=True, joint=True)
    shaft_outline = [(-.066, -.12), (.066, -.12), (.059, .12), (.041, .51), (-.046, .51), (-.059, .14)]
    register(helper.poly_xz("arm_shaft", shaft_outline, .094, "wood_light", anchors["throwing_arm"], edge=.009), True)
    for side in (-1, 1):
        block("arm_face_grain_" + str(side), (0, side * .0475, .29), (.018, .002, .27), "wood", "throwing_arm", True, .001)
    for region, start, radius in (("lower", .115, .070), ("cup_neck", .425, .066)):
        for wrap in range(3):
            register(helper.ring("arm_binding_" + region + str(wrap), (0, 0, start + wrap * .020), radius, .010, "hide", (0, 0, 1), anchors["moving_bindings"]), True)
    vertices, faces, sectors = cup_geometry()
    mesh = bpy.data.meshes.new("hollow_wood_cup_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    cup = bpy.data.objects.new("hollow_wood_cup", mesh)
    scene.collection.objects.link(cup)
    helper.finish(cup, cup.name, None, anchors["cup"])
    for name in ("wood", "wood_light", "wood", "leather"):
        mesh.materials.append(helper.material(name))
    for polygon, sector in zip(mesh.polygons, sectors):
        polygon.material_index = sector
    register(cup, True)
    for index, axial in enumerate((-.025, .02)):
        binding_vertices, binding_faces = cup_binding_geometry(axial)
        binding_mesh = bpy.data.meshes.new("cup_binding_mesh_" + str(index))
        binding_mesh.from_pydata(binding_vertices, [], binding_faces)
        binding_mesh.update()
        binding = bpy.data.objects.new("cup_binding_attached_" + str(index), binding_mesh)
        scene.collection.objects.link(binding)
        register(helper.finish(binding, binding.name, "hide", anchors["moving_bindings"]), True)
    register(helper.ico("cup_binding_knot", (0, 0, .432), (.026, .023, .017), "hide", anchors["moving_bindings"], 1), True)
    stone = register(helper.ico("loaded_stone_mesh", RELEASE_LOCAL, (.050, .065, .060), "stone", anchors["loaded_stone"], 2), True)
    stone["visibility_contract"] = "Hide at FireSeq release; restore at cycle 1.2 seconds; cosmetic only"
    anchors["release_point"].location = RELEASE_LOCAL
    anchors["arm_pivot"].location = PIVOT
    anchors["arm_pivot"].rotation_euler[1] = math.radians(READY_ANGLE)
    bpy.context.view_layer.update()
    return helper, anchors, fixed, moving, joints, stone


def apply_and_inspect(objects):
    import bpy
    import bmesh
    reports = []
    for obj in objects:
        bpy.context.view_layer.objects.active = obj
        for modifier in list(obj.modifiers):
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        mesh = obj.data
        editable = bmesh.new()
        editable.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(editable, faces=editable.faces)
        editable.to_mesh(mesh)
        mesh.calc_loop_triangles()
        report = {"name": obj.name, "group": obj["mechanism_group"], "vertices": len(mesh.vertices),
                  "triangles": len(mesh.loop_triangles), "nonmanifold_edges": sum(not edge.is_manifold for edge in editable.edges),
                  "degenerate_faces": sum(face.calc_area() <= 1e-10 for face in editable.faces),
                  "signed_volume_m3": editable.calc_volume(signed=True)}
        editable.free()
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=.025)
        bpy.ops.object.mode_set(mode="OBJECT")
        reports.append(report)
    return reports


def geometry_world(objects):
    vertices, triangles = [], []
    for obj in objects:
        obj.data.calc_loop_triangles()
        offset = len(vertices)
        vertices.extend(obj.matrix_world @ vertex.co for vertex in obj.data.vertices)
        triangles.extend(tuple(offset + index for index in triangle.vertices) for triangle in obj.data.loop_triangles)
    return vertices, triangles


def point_bounds(points):
    return {"min": [min(point[axis] for point in points) for axis in range(3)],
            "max": [max(point[axis] for point in points) for axis in range(3)]}


def actual_sweep(anchors, fixed, moving, joints):
    import bpy
    from mathutils.bvhtree import BVHTree
    pivot = anchors["arm_pivot"]
    pivot.rotation_euler[1] = 0
    bpy.context.view_layer.update()
    inverse = pivot.matrix_world.inverted()
    fixed_trees = {}
    fixed_bounds = {}
    for obj in fixed:
        vertices, triangles = geometry_world([obj])
        fixed_trees[obj.name] = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
        fixed_bounds[obj.name] = point_bounds(vertices)
    moving_bounds = {}
    unresolved = []
    for obj in moving:
        vertices, unused_triangles = geometry_world([obj])
        bounds = swept_point_bounds([tuple(inverse @ vertex) for vertex in vertices])
        moving_bounds[obj.name] = bounds
        for other in fixed:
            if aabb_separation(bounds, fixed_bounds[other.name]) <= 0:
                unresolved.append((obj, other))
    collisions = []
    for angle in range(int(RELOAD_ANGLE * 2), int(FOLLOW_ANGLE * 2) + 1):
        degrees = angle / 2
        pivot.rotation_euler[1] = math.radians(degrees)
        bpy.context.view_layer.update()
        trees = {}
        for moving_obj, fixed_obj in unresolved:
            if moving_obj.name not in trees:
                vertices, triangles = geometry_world([moving_obj])
                trees[moving_obj.name] = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
            overlaps = trees[moving_obj.name].overlap(fixed_trees[fixed_obj.name])
            if overlaps:
                collisions.append({"angle_degrees": degrees, "moving": moving_obj.name,
                                   "fixed": fixed_obj.name, "triangle_pairs": len(overlaps)})
    pivot.rotation_euler[1] = math.radians(READY_ANGLE)
    bpy.context.view_layer.update()
    return {"full_angle_range_degrees": [RELOAD_ANGLE, FOLLOW_ANGLE], "sample_step_degrees": .5,
            "sampled_angles": 211, "actual_mesh_moving_swept_bounds_m": moving_bounds,
            "continuous_aabb_separated_pairs": len(moving) * len(fixed) - len(unresolved),
            "unresolved_aabb_pairs": [{"moving": pair[0].name, "fixed": pair[1].name} for pair in unresolved],
            "sampled_surface_intersections": collisions,
            "joint_contact_exclusions": [{"name": obj.name, "reason": "intentional coaxial axle/hub/bearing contact, not a swept external part"} for obj in joints],
            "continuous_external_clearance_proven": not unresolved,
            "sampled_external_clearance_pass": not collisions,
            "limitation": "Unresolved AABB pairs receive finite 0.5 degree surface tests, not a continuous volume proof. Joint exclusions and all assembly contact still need image review."}


def add_cycle(anchors, stone):
    import bpy
    pivot = anchors["arm_pivot"]
    pivot["loaded_stone_visible"] = True
    bpy.context.scene.render.fps = 60
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = 145
    for frame in range(145):
        state = sample_cycle(frame / 60)
        pivot.rotation_euler[1] = math.radians(state["angle_degrees"])
        pivot.keyframe_insert(data_path="rotation_euler", index=1, frame=frame + 1)
        pivot["loaded_stone_visible"] = state["stone_visible"]
        pivot.keyframe_insert(data_path='["loaded_stone_visible"]', frame=frame + 1)
        stone.hide_render = not state["stone_visible"]
        stone.keyframe_insert(data_path="hide_render", frame=frame + 1)
    pivot.animation_data.action.name = "RockTower_ReleasedFollowThrough_Reload_2p4s"
    stone.animation_data.action.name = "RockTower_LoadedStone_CosmeticVisibility"
    bpy.context.scene.frame_set(145)
    return {"fps": 60, "frames": 145, "duration_seconds": 2.4,
            "arm_action": pivot.animation_data.action.name, "stone_action": stone.animation_data.action.name,
            "time_zero_is_server_already_fired": True, "authority_events_created": False,
            "geometry_exports_animated": False,
            "runtime_clip_mapping": {"idle": "ready constant", "aim": "fixed release direction; target-specific aim unimplemented",
                                     "fire": "cycle 0..0.30", "reload_stone": "cycle 0.30..2.4", "disabled": "ready angle, stone hidden"},
            "visibility_export_limit": "Blender hide_render is a review channel, not portable glTF visibility. UE must drive the separate stone component from the cosmetic cycle contract."}


def export_candidate(out, helper, anchors, meshes):
    import bpy
    objects = list(anchors.values()) + meshes
    helper.current_root = anchors[ASSET_ID]
    helper.select_asset(objects)
    glb = out / (ASSET_ID + ".glb")
    fbx = out / (ASSET_ID + ".fbx")
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", use_selection=True,
                              export_extras=True, export_animations=False, export_apply=False)
    bpy.ops.export_scene.fbx(filepath=str(fbx), use_selection=True, object_types={"EMPTY", "MESH"},
                             apply_unit_scale=True, axis_forward="X", axis_up="Z", use_mesh_modifiers=False,
                             bake_anim=False, add_leaf_bones=False, use_custom_props=True, path_mode="AUTO")
    return [file_record(glb), file_record(fbx)]


def roundtrip(out, expected_bounds, expected_anchors):
    import bpy
    results = {}
    for extension in ("glb", "fbx"):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = out / (ASSET_ID + "." + extension)
        if extension == "glb":
            bpy.ops.import_scene.gltf(filepath=str(path))
        else:
            bpy.ops.import_scene.fbx(filepath=str(path), use_anim=False)
        bpy.context.view_layer.update()
        meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
        vertices, triangles = geometry_world(meshes)
        bounds = point_bounds(vertices)
        errors = [abs(bounds[side][axis] - expected_bounds[side][axis]) for side in ("min", "max") for axis in range(3)]
        anchor_errors = {}
        missing = []
        for name, position in expected_anchors.items():
            obj = bpy.context.scene.objects.get(name)
            if obj is None:
                missing.append(name)
            else:
                anchor_errors[name] = math.dist(position, obj.matrix_world.translation)
        results[extension] = {"triangles": len(triangles), "bounds_m": bounds,
                              "max_bound_error_m": max(errors), "anchor_errors_m": anchor_errors,
                              "missing_anchors": missing,
                              "passed": not missing and max(errors) < .0001 and max(anchor_errors.values(), default=0) < .0001}
    return results


def render_candidate(out, helper, anchors, meshes, resolution, samples, device, specifications=None):
    import bpy
    from mathutils import Vector
    for name in ("DISPLAY_floor", "DISPLAY_camera", "DISPLAY_key", "DISPLAY_fill", "DISPLAY_rim"):
        existing = bpy.context.scene.objects.get(name)
        if existing:
            bpy.data.objects.remove(existing, do_unlink=True)
    camera, centre, span = helper.add_lighting_and_camera(meshes)
    scene = bpy.context.scene
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 2
    scene.render.resolution_x = scene.render.resolution_y = resolution
    scene.cycles.samples = samples
    if device == "HIP":
        preferences = bpy.context.preferences.addons["cycles"].preferences
        preferences.compute_device_type = "HIP"
        preferences.get_devices()
        devices = []
        for item in preferences.devices:
            item.use = item.type == "HIP"
            if item.use:
                devices.append(item.name)
        if not devices:
            raise RuntimeError("No HIP device; refusing silent CPU fallback")
        scene.cycles.device = "GPU"
    camera.data.ortho_scale = span * 1.3
    views = []
    specifications = specifications or [("preview", (2.4, -3.2, 1.7), 145), ("front", (1, 0, 0), 145),
                                       ("left", (0, -1, 0), 145), ("back", (-1, 0, 0), 145), ("right", (0, 1, 0), 145),
                                       ("released", (2.4, -3.2, 1.7), 1), ("follow_through", (2.4, -3.2, 1.7), 11),
                                       ("reload", (2.4, -3.2, 1.7), 73)]
    for name, direction, frame in specifications:
        scene.frame_set(frame)
        if name.startswith(("assembly_", "platform_")):
            scene.objects["DISPLAY_floor"].location.z = -.025
        target, view_span = centre, span
        if name.startswith("platform_"):
            platform_id = name.removeprefix("platform_")
            target = Vector(PLATFORMS_CM[platform_id]) / 100 + Vector((0, 0, .10))
            view_span = 1.05
        camera.data.ortho_scale = view_span * 1.3
        camera.location = target + Vector(direction).normalized() * max(view_span, 1) * 4
        camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
        scene.objects["DISPLAY_floor"].hide_render = name in {"front", "left", "back", "right"}
        path = out / (name + ".png")
        if path.exists():
            raise FileExistsError(path)
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        views.append({"view": name, "frame": frame, "time_seconds": (frame - 1) / 60,
                      "file": file_record(path), "camera_m": list(camera.location),
                      "ortho_scale_m": camera.data.ortho_scale})
    scene.frame_set(145)
    return {"views": views, "resolution": [resolution, resolution], "samples": samples,
            "device": device, "threads": 2, "visual_approval": False}


def tagged_geometry(objects):
    vertices, triangles, owners = [], [], []
    for obj in objects:
        points, faces = geometry_world([obj])
        offset = len(vertices)
        vertices.extend(points)
        triangles.extend(tuple(index + offset for index in face) for face in faces)
        owners.extend([obj.name] * len(faces))
    return vertices, triangles, owners


def foot_samples(objects, grid_m=.01):
    samples = {}
    for obj in objects:
        if not obj.name.startswith(("foot_", "support_pad_")):
            continue
        vertices, triangles = geometry_world([obj])
        for triangle in triangles:
            first, second, third = [vertices[index] for index in triangle]
            normal = (second - first).cross(third - first).normalized()
            if normal.z > (-.96 if obj.name.startswith("support_pad_") else -.99):
                continue
            divisions = max(1, math.ceil(max((first - second).length, (first - third).length, (second - third).length) / grid_m))
            for row in range(divisions + 1):
                for column in range(divisions - row + 1):
                    point = first + (second - first) * (row / divisions) + (third - first) * (column / divisions)
                    key = (obj.name,) + tuple(round(value, 7) for value in point)
                    samples[key] = (obj.name, point)
    return list(samples.values())


def base_surface_patches(vertices, triangles, rectangle, reference_z):
    patches = []
    for face_index, face in enumerate(triangles):
        points = [vertices[index] for index in face]
        if max(point.z for point in points) < reference_z - .05 or min(point.z for point in points) > reference_z + .05:
            continue
        if max(point.x for point in points) < rectangle[0] or min(point.x for point in points) > rectangle[1]:
            continue
        if max(point.y for point in points) < rectangle[2] or min(point.y for point in points) > rectangle[3]:
            continue
        if (points[1] - points[0]).cross(points[2] - points[0]).normalized().z < .96:
            continue
        clipped = clipped_surface_polygon(points, rectangle)
        if len(clipped) >= 3 and abs(projected_area(clipped)) > 1e-12:
            patches.append((face_index, clipped))
    return patches


def measure_support(samples, transform, tree):
    from mathutils import Vector
    groups, evidence = {}, []
    for name, sample in samples:
        point = transform @ sample
        location, normal, face_index, distance = tree.ray_cast(point + Vector((0, 0, .05)), Vector((0, 0, -1)), .25)
        group = groups.setdefault(name, {"gaps": [], "missing": 0, "non_upward": 0})
        if location is None:
            group["missing"] += 1
            evidence.append({"foot": name, "point_cm": list(point * 100), "hit": False})
        else:
            gap = point.z - location.z
            group["gaps"].append(gap)
            group["non_upward"] += int(normal.z < .96)
            evidence.append({"foot": name, "point_cm": list(point * 100), "hit": True,
                             "base_triangle": face_index, "hit_z_cm": location.z * 100,
                             "normal_z": normal.z, "gap_mm": gap * 1000})
    return {name: support_result(item["gaps"], item["missing"], item["non_upward"])
            for name, item in groups.items()}, evidence


def create_platform_pads(platform_id, mount, fixed, base_vertices, base_triangles, base_tree):
    import bpy
    from mathutils import Matrix, Vector
    from mathutils.bvhtree import BVHTree
    patch_sets, pad_heights, clearance = {}, [], []
    for obj in fixed:
        if not obj.name.startswith(("foot_", "corner_cap_")):
            continue
        vertices, unused_faces = geometry_world([obj])
        bounds = point_bounds([mount @ point for point in vertices])
        rectangle = (bounds["min"][0], bounds["max"][0], bounds["min"][1], bounds["max"][1])
        patches = base_surface_patches(base_vertices, base_triangles, rectangle, mount.translation.z)
        if obj.name.startswith("foot_"):
            if not patches:
                raise ValueError("No actual Base surface under " + platform_id + "/" + obj.name)
            patch_sets[obj.name] = (rectangle, patches)
            pad_heights.extend(point[2] - mount.translation.z for unused_index, polygon in patches for point in polygon)
        else:
            clearance.extend(point[2] - bounds["min"][2] + .003 for unused_index, polygon in patches for point in polygon)
    if len(patch_sets) != 4:
        raise ValueError("Four independent foot pads are required")
    lift = mount_lift(pad_heights, clearance)
    adapter = bpy.data.objects.new("platform_adapter_" + platform_id, None)
    bpy.context.scene.collection.objects.link(adapter)
    adapter.location = mount.translation
    adapter["civwar_part"] = True
    adapter["local_upper_lift_m"] = lift
    objects, geometry_reports = [], []
    for foot_name, (rectangle, patches) in patch_sets.items():
        vertices, faces, geometry = matched_pad_geometry(patches, rectangle, mount.translation.z + lift)
        name = "support_pad_" + platform_id + "__" + foot_name
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([Vector(point) - mount.translation for point in vertices], [], faces)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.parent = adapter
        obj["civwar_part"] = True
        obj["mechanism_group"] = "platform_adapter"
        obj["original_foot"] = foot_name
        obj["clipped_base_bottom_faces"] = geometry["bottom_triangles"]
        mesh.materials.append(bpy.data.materials["CW_wood"])
        objects.append(obj)
        geometry_reports.append({"pad": name, "foot": foot_name, "world_rectangle_m": rectangle, **geometry})
    bpy.context.view_layer.update()
    topology = apply_and_inspect(objects)
    vertices, triangles = geometry_world(objects)
    tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
    bottom_support, bottom_evidence = measure_support(foot_samples(objects), Matrix.Identity(4), base_tree)
    overlap = tree.overlap(base_tree)
    bottom_triangles = set()
    allowed_source_faces = {}
    offset = 0
    for obj, geometry in zip(objects, geometry_reports):
        obj.data.calc_loop_triangles()
        bottom_triangles.update(offset + index for index, triangle in enumerate(obj.data.loop_triangles)
                                if triangle.polygon_index < obj["clipped_base_bottom_faces"])
        for index in range(len(obj.data.loop_triangles)):
            allowed_source_faces[offset + index] = set(geometry["source_base_faces"])
        offset += len(obj.data.loop_triangles)
    forbidden_contacts = [(first, second) for first, second in overlap if second not in allowed_source_faces[first]]
    report = {"adapter_anchor": adapter.name, "platform_id": platform_id,
              "authoritative_mount_cm": list(mount.translation * 100),
              "upper_local_translation_cm": [0, 0, lift * 100], "upper_local_rotation_degrees": [0, 0, 0],
              "upper_local_scale": [1, 1, 1], "release_point_world_offset_cm": [0, 0, lift * 100],
              "lift_limit_mm": 20, "minimum_pad_thickness_mm": 5,
              "geometry": geometry_reports, "topology": topology, "actual_extra_triangles": len(triangles),
              "bottom_support": bottom_support, "bottom_support_evidence": bottom_evidence,
              "base_bottom_contact_pairs": sum(first in bottom_triangles for first, second in overlap),
              "base_boundary_contact_pairs": sum(first not in bottom_triangles for first, second in overlap),
              "base_forbidden_contact_pairs": len(forbidden_contacts),
              "base_forbidden_contact_examples": forbidden_contacts[:16],
              "contact_rule": "Only the exact clipped source bottom and its boundary are intentional Base contact; original upper-part intersections remain forbidden.",
              "bottoms_match_source_triangles": True,
              "numeric_pass": not forbidden_contacts and all(item["passed"] for item in bottom_support.values()) and len(bottom_support) == 4
                              and all(item["nonmanifold_edges"] == 0 and item["degenerate_faces"] == 0 and item["signed_volume_m3"] > 0 for item in topology)}
    return lift, objects, adapter, tree, report


def export_platform_pads(out, adapter, objects):
    import bpy
    from mathutils import Vector
    old_location = adapter.location.copy()
    adapter.location = (0, 0, 0)
    bpy.context.view_layer.update()
    expected_vertices, unused_faces = geometry_world(objects)
    expected_bounds = point_bounds(expected_vertices)
    records, roundtrips = [], []
    for extension in ("glb", "fbx"):
        bpy.ops.object.select_all(action="DESELECT")
        for obj in [adapter] + objects:
            obj.select_set(True)
        path = out / (adapter.name + "." + extension)
        if path.exists():
            raise FileExistsError(path)
        if extension == "glb":
            bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True,
                                      export_extras=True, export_animations=False, export_apply=False)
        else:
            bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, object_types={"EMPTY", "MESH"},
                                     apply_unit_scale=True, axis_forward="X", axis_up="Z", use_mesh_modifiers=False,
                                     bake_anim=False, add_leaf_bones=False, use_custom_props=True)
        records.append(file_record(path))
        before = set(bpy.context.scene.objects)
        if extension == "glb":
            bpy.ops.import_scene.gltf(filepath=str(path))
        else:
            bpy.ops.import_scene.fbx(filepath=str(path), use_anim=False)
        bpy.context.view_layer.update()
        imported = [obj for obj in bpy.context.scene.objects if obj not in before]
        points, faces = geometry_world([obj for obj in imported if obj.type == "MESH"])
        actual = point_bounds(points)
        error = max(abs(actual[side][axis] - expected_bounds[side][axis]) for side in ("min", "max") for axis in range(3))
        roundtrips.append({"format": extension, "actual_triangles": len(faces), "max_bound_error_m": error,
                           "passed": error <= .0001 and len(faces) == len(unused_faces)})
        for obj in imported:
            bpy.data.objects.remove(obj, do_unlink=True)
    adapter.location = Vector(old_location)
    bpy.context.view_layer.update()
    return {"files": records, "roundtrips": roundtrips, "origin": "unchanged platform mount; upper is a separate child with explicit local Z lift",
            "passed": all(item["passed"] for item in roundtrips)}


def inspect_base_assembly(out, base_manifest, anchors, meshes, scale, support_pads=False):
    import bpy
    from mathutils import Matrix, Vector
    from mathutils.bvhtree import BVHTree
    if out.exists():
        raise FileExistsError(out)
    if support_pads and scale != 1:
        raise ValueError("Support-only adaptation keeps the frozen upper mechanism at scale 1")
    manifest = json.loads(Path(base_manifest).read_text(encoding="utf-8-sig"))
    asset = next(item for item in manifest["assets"] if item["id"] == "Base_Stone")
    base_path = (ROOT / asset["file"]).resolve()
    if not base_path.is_relative_to((ART / "tripo_processed/base_stone_v01").resolve()):
        raise ValueError("Base input must be the existing Base_Stone processed asset")
    base_source = file_record(base_path)
    if base_source["sha256"] != asset["sha256"]:
        raise ValueError("Base hash differs from its manifest")
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(base_path))
    bpy.context.view_layer.update()
    base_meshes = [obj for obj in bpy.context.scene.objects if obj not in before and obj.type == "MESH"]
    base_vertices, base_triangles = geometry_world(base_meshes)
    bounds = point_bounds(base_vertices)
    expected = asset["expected_bounds_cm"]
    bound_error_cm = max(abs(bounds[side][axis] * 100 - expected[side][axis]) for side in ("min", "max") for axis in range(3))
    if bound_error_cm > .001:
        raise ValueError("Base import unit/basis does not match normalized bounds")
    if asset.get("runtime_material_overrides", {}).get("Metallic") == 0:
        for obj in base_meshes:
            for material in obj.data.materials:
                if material and material.use_nodes:
                    for node in material.node_tree.nodes:
                        if node.type == "BSDF_PRINCIPLED":
                            for link in list(node.inputs["Metallic"].links):
                                material.node_tree.links.remove(link)
                            node.inputs["Metallic"].default_value = 0
    base_tree = BVHTree.FromPolygons(base_vertices, base_triangles, all_triangles=True)
    pivot = anchors["arm_pivot"]
    moving, fixed = [], []
    for obj in meshes:
        ancestor = obj.parent
        while ancestor and ancestor != pivot:
            ancestor = ancestor.parent
        (moving if ancestor == pivot else fixed).append(obj)
    moving_world, moving_faces, moving_owners = tagged_geometry(moving)
    pivot_inverse = pivot.matrix_world.inverted()
    moving_local = [pivot_inverse @ point for point in moving_world]
    fixed_points, fixed_faces, fixed_owners = tagged_geometry(fixed)
    samples = foot_samples(fixed)
    ready_matrix = Matrix.Translation(Vector(PIVOT)) @ Matrix.Rotation(math.radians(READY_ANGLE), 4, "Y")
    ready_reconstruction_error_m = max((ready_matrix @ local - world).length for local, world in zip(moving_local, moving_world))
    if ready_reconstruction_error_m > 1e-6:
        raise ValueError("Actual rigid hierarchy differs from the proposed Y-axis sweep")
    platform_reports, platform_lifts, all_pads = [], {}, []
    out.mkdir(parents=True)
    for platform_id, position_cm in PLATFORMS_CM.items():
        mount = Matrix.Translation(Vector(position_cm) / 100) @ Matrix.Diagonal(Vector((scale, scale, scale, 1)))
        pad_report, pad_tree = None, None
        if support_pads:
            lift, pads, adapter, pad_tree, pad_report = create_platform_pads(
                platform_id, mount, fixed, base_vertices, base_triangles, base_tree)
            platform_lifts[platform_id] = lift
            all_pads.extend(pads)
            mount.translation.z += lift
            pad_report["exports"] = export_platform_pads(out, adapter, pads)
            pad_report["numeric_pass"] = pad_report["numeric_pass"] and pad_report["exports"]["passed"]
        transformed_fixed = [mount @ point for point in fixed_points]
        fixed_tree = BVHTree.FromPolygons(transformed_fixed, fixed_faces, all_triangles=True)
        fixed_pairs = fixed_tree.overlap(base_tree)
        contact_pairs = [pair for pair in fixed_pairs if not support_pads and fixed_owners[pair[0]].startswith("foot_")]
        forbidden_fixed = [pair for pair in fixed_pairs if support_pads or not fixed_owners[pair[0]].startswith("foot_")]
        supports, support_evidence = measure_support(samples, mount, pad_tree or base_tree)
        if pad_tree is not None:
            pad_upper_pairs = fixed_tree.overlap(pad_tree)
            forbidden_upper = [pair for pair in pad_upper_pairs if not fixed_owners[pair[0]].startswith("foot_")]
            pad_report["upper_intended_foot_contact_pairs"] = len(pad_upper_pairs) - len(forbidden_upper)
            pad_report["upper_forbidden_triangle_pairs"] = len(forbidden_upper)
            pad_report["numeric_pass"] = pad_report["numeric_pass"] and not forbidden_upper
        sweep_rows = []
        for half_degree in range(int(RELOAD_ANGLE * 2), int(FOLLOW_ANGLE * 2) + 1):
            angle = half_degree / 2
            transform = mount @ Matrix.Translation(Vector(PIVOT)) @ Matrix.Rotation(math.radians(angle), 4, "Y")
            points = [transform @ point for point in moving_local]
            tree = BVHTree.FromPolygons(points, moving_faces, all_triangles=True)
            pairs = tree.overlap(base_tree)
            if pairs:
                examples = []
                for part_triangle, base_triangle in pairs[:16]:
                    centre = sum((base_vertices[index] for index in base_triangles[base_triangle]), Vector()) / 3
                    examples.append({"part": moving_owners[part_triangle], "part_triangle": part_triangle,
                                     "base_triangle": base_triangle, "base_face_centroid_cm": [value * 100 for value in centre]})
                sweep_rows.append({"angle_degrees": angle, "triangle_pairs": len(pairs), "examples": examples})
        fixed_examples = [{"part": fixed_owners[first], "part_triangle": first, "base_triangle": second}
                          for first, second in forbidden_fixed[:32]]
        platform_reports.append({"id": platform_id, "blender_mount_cm": position_cm,
                                 "ue_mount_cm_basis_note_only": [position_cm[0], -position_cm[1], position_cm[2]],
                                 "uniform_turret_scale": scale, "foot_samples": supports,
                                 "foot_support_surface": "adapter top" if support_pads else "original Base",
                                 "platform_adapter": pad_report,
                                 "foot_support_evidence": support_evidence,
                                 "intended_foot_contact_triangle_pairs": len(contact_pairs),
                                 "contact_allowed_only_if_all_foot_samples_within_2mm": True,
                                 "forbidden_fixed_triangle_pairs": len(forbidden_fixed), "fixed_examples": fixed_examples,
                                 "moving_surface_collision_angles": sweep_rows,
                                 "sampled_mechanism_surface_clear": not forbidden_fixed and not sweep_rows and (pad_report is None or pad_report["numeric_pass"]),
                                 "all_feet_supported": len(supports) == 4 and all(item["passed"] for item in supports.values())})
        print("CIVWAR_ROCKTOWER_PLATFORM " + platform_id + " " + str(len(sweep_rows)) + " collision angles", flush=True)
    result = {"schema_version": 1, "status": "actual_base_mesh_assembly_candidate_not_approved",
              "base_source": base_source, "base_manifest": file_record(base_manifest),
              "base_import_bound_error_cm": bound_error_cm,
              "actual_rigid_pose_reconstruction_error_m": ready_reconstruction_error_m,
              "source_base_modified": False, "authoritative_coordinates_modified": False,
              "candidate_scale": scale, "platforms": platform_reports,
              "support_adapters_enabled": support_pads,
              "upper_local_lifts_m": platform_lifts,
              "sweep": {"angle_range": [RELOAD_ANGLE, FOLLOW_ANGLE], "step_degrees": .5, "angles_per_platform": 211,
                        "method": "actual exported candidate mesh triangles transformed by the checked rigid hierarchy versus actual normalized Base_Stone triangles; includes loaded stone conservatively at all angles",
                        "limit": "Finite angular surface-intersection tests are not a continuous swept-volume or fully-enclosed-volume proof. Foot support tests use all sampled flat sole triangles, not one centre ray."},
              "numeric_pass": all(item["sampled_mechanism_surface_clear"] and item["all_feet_supported"] for item in platform_reports),
              "production_approved": False, "approved_for_ue_import": False}
    write_new(out / "inspection.json", result)
    originals = list(anchors.values()) + meshes
    first_id = next(iter(PLATFORMS_CM))
    roots = {first_id: anchors[ASSET_ID]}
    for platform_id in list(PLATFORMS_CM)[1:]:
        copies = {}
        for obj in originals:
            copied = obj.copy()
            copied.name = platform_id + "__" + obj.name
            bpy.context.scene.collection.objects.link(copied)
            copies[obj] = copied
        for source, copied in copies.items():
            copied.parent = copies.get(source.parent)
        roots[platform_id] = copies[anchors[ASSET_ID]]
    for platform_id, root in roots.items():
        root.location = Vector(PLATFORMS_CM[platform_id]) / 100
        root.location.z += platform_lifts.get(platform_id, 0)
        root.scale = (scale, scale, scale)
    bpy.context.scene.frame_set(145)
    bpy.context.view_layer.update()
    if file_record(base_path)["sha256"] != base_source["sha256"]:
        raise RuntimeError("Frozen Base_Stone input changed during assembly")
    return result, base_meshes + [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.get("civwar_part") and obj not in base_meshes]


def build(out, render=False, resolution=512, samples=8, device="HIP", base_manifest=None, assembly_out=None, assembly_scale=1.0):
    import bpy
    if out.exists():
        raise FileExistsError("Candidate directory already exists: " + str(out))
    plan = mechanism_plan()
    if base_manifest:
        plan["assembly_input"] = base_input_contract(base_manifest)
        plan["assembly_input"]["uniform_candidate_scale"] = assembly_scale
    out.mkdir(parents=True)
    write_new(out / "input_plan.json", plan)
    helper, anchors, fixed, moving, joints, stone = build_parts()
    meshes = fixed + moving + joints
    topology = apply_and_inspect(meshes)
    for cutter in [obj for obj in bpy.context.scene.objects if obj.get("temporary_bore_cutter")]:
        bpy.data.objects.remove(cutter, do_unlink=True)
    sweep = actual_sweep(anchors, fixed, moving, joints)
    bpy.context.view_layer.update()
    vertices, triangles = geometry_world(meshes)
    bounds = point_bounds(vertices)
    anchor_positions = {name: list(obj.matrix_world.translation) for name, obj in anchors.items()}
    exports = export_candidate(out, helper, anchors, meshes)
    motion = add_cycle(anchors, stone)
    blend = out / (ASSET_ID + ".blend")
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    imported = roundtrip(out, bounds, anchor_positions)
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    anchors = {name: bpy.context.scene.objects[name] for name in HIERARCHY}
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.get("civwar_part")]
    report = {
        "schema_version": 1, "asset_id": ASSET_ID, "status": "candidate_geometry_not_approved",
        "script": file_record(Path(__file__)), "plan": file_record(out / "input_plan.json"),
        "blender": bpy.app.version_string, "units": "metres", "mesh_count": len(meshes),
        "actual_triangles": len(triangles), "actual_ready_bounds_m": bounds,
        "actual_ready_dimensions_cm": [(bounds["max"][axis] - bounds["min"][axis]) * 100 for axis in range(3)],
        "anchors_world_m": anchor_positions, "hierarchy": HIERARCHY,
        "topology": topology, "sweep": sweep, "motion": motion,
        "exports": exports + [file_record(blend)], "roundtrip": imported,
        "base_platform_fit": {"status": "not_verified", "reason": "Only isolated mechanism is built; exact normalized Base_Stone mounting and sweep remains a separate actual-mesh gate."},
        "material_note": "Reusable broad palette and physically-based factors; no generated textures or packed shared atlas. Smart-projected per-part UVs; overlap is not independently audited and no atlas is approved.",
        "production_approved": False, "approved_for_ue_import": False,
    }
    write_new(out / "inspection.json", report)
    if render:
        focus = [("connections_side", (0, 1, 0), 145), ("connections_oblique", (2.4, -3.2, 1.7), 145)] if base_manifest else None
        views = render_candidate(out, helper, anchors, meshes, resolution, samples, device, focus)
        write_new(out / "views.json", views)
    assembly = None
    if base_manifest:
        assembly, assembly_meshes = inspect_base_assembly(assembly_out, base_manifest, anchors, meshes, assembly_scale)
        if render:
            specifications = [("assembly_ready", (2.4, -3.2, 2.6), 145), ("assembly_followthrough", (2.4, -3.2, 2.6), 11)]
            assembly_views = render_candidate(assembly_out, helper, anchors, assembly_meshes, resolution, samples, device, specifications)
            write_new(assembly_out / "views.json", assembly_views)
        bpy.ops.wm.save_as_mainfile(filepath=str(assembly_out / "assembly_scene.blend"))
    topology_pass = all(item["nonmanifold_edges"] == 0 and item["degenerate_faces"] == 0 and item["signed_volume_m3"] > 0 for item in topology)
    status = {"status": "candidate_requires_visual_and_base_fit_review", "inspection": file_record(out / "inspection.json"),
              "topology_pass": topology_pass, "roundtrip_pass": all(item["passed"] for item in imported.values()),
              "sampled_self_sweep_pass": sweep["sampled_external_clearance_pass"],
              "rendered": render, "production_approved": False,
              "assembly_report": file_record(assembly_out / "inspection.json") if assembly else None,
              "assembly_numeric_pass": assembly["numeric_pass"] if assembly else None}
    write_new(out / "checkpoint.json", status)
    print("CIVWAR_ROCKTOWER_CANDIDATE " + json.dumps(status), flush=True)
    if not topology_pass or not status["roundtrip_pass"] or not status["sampled_self_sweep_pass"] or (assembly and not assembly["numeric_pass"]):
        raise RuntimeError("Candidate numeric gate failed; evidence retained; no approval")


def frozen_upper_contract(source):
    path = Path(source).resolve()
    if not path.is_relative_to(OUTPUT_ROOT.resolve()) or path.suffix != ".blend":
        raise ValueError("Assembly source must be a frozen RockTower candidate blend")
    report_path = path.parent / "inspection.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    record = file_record(path)
    matches = [item for item in report["exports"] if item["file"] == record["file"]]
    if len(matches) != 1 or matches[0]["sha256"] != record["sha256"]:
        raise ValueError("Frozen upper model differs from its actual inspection")
    if not report["topology"] or not all(item["nonmanifold_edges"] == 0 and item["degenerate_faces"] == 0 and item["signed_volume_m3"] > 0 for item in report["topology"]):
        raise ValueError("Frozen upper topology did not pass")
    if not all(report["roundtrip"][extension]["passed"] for extension in ("glb", "fbx")):
        raise ValueError("Frozen upper roundtrip did not pass")
    return {"model": record, "inspection": file_record(report_path), "mesh_count": report["mesh_count"],
            "triangles": report["actual_triangles"], "exports": report["exports"],
            "reuse_upper_geometry_unmodified": True, "reuse_axis_and_cycle_unmodified": True}


def geometry_data_signature(objects):
    result = {}
    for obj in objects:
        obj.data.calc_loop_triangles()
        data = {"vertices": [list(vertex.co) for vertex in obj.data.vertices],
                "triangles": [list(triangle.vertices) for triangle in obj.data.loop_triangles]}
        result[obj.name] = hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()
    return result


def assemble_frozen_upper(out, source, base_manifest, assembly_out, render, resolution, samples, device):
    import bpy
    contract = frozen_upper_contract(source)
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    write_new(out / "input_plan.json", {"upper": contract, "base": base_input_contract(base_manifest),
                                       "support_adapters": True, "maximum_local_lift_mm": 20,
                                       "minimum_pad_thickness_mm": 5, "support_tolerance_mm": 2,
                                       "production_approved": False})
    bpy.ops.wm.open_mainfile(filepath=str(Path(source).resolve()))
    bpy.context.scene.frame_set(145)
    bpy.context.view_layer.update()
    anchors = {name: bpy.context.scene.objects[name] for name in HIERARCHY}
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.get("civwar_part")]
    if len(meshes) != contract["mesh_count"]:
        raise ValueError("Frozen upper mesh count changed")
    before_geometry = geometry_data_signature(meshes)
    helper_spec = importlib.util.spec_from_file_location("cw_weapon_helpers", ROOT / "Tools/Blender/build_weapons.py")
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    assembly, assembly_meshes = inspect_base_assembly(assembly_out, base_manifest, anchors, meshes, 1.0, True)
    if geometry_data_signature(meshes) != before_geometry or file_record(source)["sha256"] != contract["model"]["sha256"]:
        raise RuntimeError("Frozen upper geometry changed during adaptation")
    if render:
        specifications = [("assembly_ready", (2.4, -3.2, 2.6), 145),
                          ("platform_front_negative_y", (2.4, -3.2, 1.7), 145),
                          ("platform_front_positive_y", (2.4, 3.2, 1.7), 145),
                          ("platform_rear", (-3.2, -2.4, 1.7), 145)]
        views = render_candidate(assembly_out, helper, anchors, assembly_meshes, resolution, samples, device, specifications)
        write_new(assembly_out / "views.json", views)
    bpy.ops.wm.save_as_mainfile(filepath=str(assembly_out / "assembly_scene.blend"))
    status = {"status": "adapter_geometry_candidate_not_approved", "upper_source": contract,
              "upper_per_mesh_geometry_signature": before_geometry, "upper_geometry_unchanged": True,
              "assembly_numeric_pass": assembly["numeric_pass"], "inspection": file_record(assembly_out / "inspection.json"),
              "upper_local_lifts_m": assembly["upper_local_lifts_m"], "rendered": render,
              "authority_modified": False, "paid_tasks": 0, "approved_for_ue_import": False, "production_approved": False}
    write_new(out / "checkpoint.json", status)
    print("CIVWAR_ROCKTOWER_ADAPTER " + json.dumps(status), flush=True)
    if not assembly["numeric_pass"]:
        raise RuntimeError("Adapter numeric gate failed; evidence retained; no approval")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--device", choices=("CPU", "HIP"), default="HIP")
    parser.add_argument("--resolution", type=int, choices=(512, 768, 1024), default=512)
    parser.add_argument("--samples", type=int, choices=(8, 12, 16), default=8)
    parser.add_argument("--base-manifest")
    parser.add_argument("--assembly-out")
    parser.add_argument("--assembly-scale", type=float, choices=(1.0, .95, .9), default=1.0)
    parser.add_argument("--assemble-source")
    parser.add_argument("--support-pads", action="store_true")
    arguments = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    out = safe_output(arguments.out)
    if bool(arguments.base_manifest) != bool(arguments.assembly_out):
        parser.error("Base manifest and fresh assembly output must be supplied together")
    assembly_out = safe_output(arguments.assembly_out) if arguments.assembly_out else None
    if assembly_out and assembly_out.exists():
        raise FileExistsError(assembly_out)
    if arguments.support_pads or arguments.assemble_source:
        if not arguments.support_pads or not arguments.assemble_source or not arguments.base_manifest or arguments.assembly_scale != 1:
            parser.error("Support-only adaptation requires frozen source, Base manifest, fresh assembly output and upper scale 1")
        contract = frozen_upper_contract(arguments.assemble_source)
        if arguments.build:
            assemble_frozen_upper(out, arguments.assemble_source, arguments.base_manifest, assembly_out,
                                  arguments.render, arguments.resolution, arguments.samples, arguments.device)
        else:
            if arguments.render:
                parser.error("Render requires explicit --build")
            write_new(out / "mechanism_plan.json", {"frozen_upper": contract, "base": base_input_contract(arguments.base_manifest),
                                                   "assembly_only": True, "four_real_support_pads_per_platform": True,
                                                   "maximum_local_lift_mm": 20, "minimum_pad_thickness_mm": 5,
                                                   "support_tolerance_mm": 2, "paid_tasks": 0,
                                                   "approved_for_ue_import": False, "production_approved": False})
        return
    if not arguments.build:
        if arguments.render:
            parser.error("Render requires explicit --build")
        plan = mechanism_plan()
        if arguments.base_manifest:
            plan["assembly_input"] = base_input_contract(arguments.base_manifest)
            plan["assembly_input"]["uniform_candidate_scale"] = arguments.assembly_scale
        write_new(out / "mechanism_plan.json", plan)
        return
    build(out, arguments.render, arguments.resolution, arguments.samples, arguments.device,
          arguments.base_manifest, assembly_out, arguments.assembly_scale)


if __name__ == "__main__":
    main()
