"""Adapt a real Tripo terrain mesh to the flat gameplay corridor without replacing its UVs."""
import math
import statistics


def smooth(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


def apply(objects, profile):
    length = float(profile["length_cm"]) / 100.0
    width = float(profile["width_cm"]) / 100.0
    lane = float(profile["road_half_width_cm"]) / 100.0
    if not (length > 2 * lane and width > 2 * lane and lane > 0):
        raise ValueError("Invalid terrain footprint")
    vertices = [v for obj in objects for v in obj.data.vertices]
    low = [min(v.co[i] for v in vertices) for i in range(3)]
    high = [max(v.co[i] for v in vertices) for i in range(3)]
    # Work in the already grounded, world-baked Blender mesh.
    sx, sy = length / (high[0] - low[0]), width / (high[1] - low[1])
    centre = [(low[i] + high[i]) / 2 for i in range(2)]
    for v in vertices:
        v.co.x = (v.co.x - centre[0]) * sx
        v.co.y = (v.co.y - centre[1]) * sy
    top = [v.co.z for v in vertices
           if abs(v.co.y) < lane and abs(v.co.x) < length * .42 and v.normal.z > .25]
    if len(top) < 10:
        raise ValueError("Could not identify the top of the generated road; inspect its orientation")
    road_height = statistics.median(top)
    amplitude = float(profile.get("height_multiplier", .65))
    max_height = float(profile.get("max_height_cm", 100)) / 100.0
    edge_band = float(profile.get("edge_blend_cm", 90)) / 100.0
    bottom = -.15
    road_count = 0
    for v in vertices:
        z = v.co.z - road_height
        is_bottom = v.normal.z < -.25 and z < -.02
        # The underside stays below the walk plane. Top geometry across the
        # corridor is exactly z=0; authoritative unit feet already use z=0.
        if is_bottom:
            v.co.z = bottom
            continue
        shoulder = smooth(lane, lane + 2.0, abs(v.co.y))
        seam_x = smooth(0, edge_band, length / 2 - abs(v.co.x))
        seam_y = smooth(0, edge_band, width / 2 - abs(v.co.y))
        v.co.z = min(max_height, max(0.0, z * amplitude)) * shoulder * seam_x * seam_y
        if abs(v.co.y) <= lane:
            road_count += 1
    for obj in objects:
        obj.data.update()
    if not all(math.isfinite(c) for v in vertices for c in v.co):
        raise ValueError("Non-finite terrain coordinate")
    return {
        "source": "Tripo geometry with original topology, UVs and PBR textures",
        "footprint_cm": [length * 100, width * 100],
        "xy_fit": [sx, sy], "road_half_width_cm": lane * 100,
        "road_surface_z_cm": 0, "source_road_height_m": road_height,
        "flattened_top_road_vertices": road_count,
        "edge_blend_cm": edge_band * 100, "underside_z_cm": bottom * 100,
        "height_multiplier": amplitude, "max_height_cm": max_height * 100,
    }
