"""Read-only source-triangle ray probe for visible ground-edge fragments in the actual game image."""
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from base_stone_validate_ue import BASE, ROOT, read_glb_geometry, sha256, write_new


source = BASE / "pbr_v01/hf150ba0cde05/Base_Stone_PBR.glb"
texture = BASE / "pbr_v01/hf150ba0cde05/textures/tripo_base_color_604f91ce-ac55-41ca-898d-bbb3c25f0165_74d3b750720b.jpg"
screenshot = ROOT / "Saved/Screenshots/WindowsEditor/BaseStoneGame_01_team0_distance1300.png"
corners, triangles = read_glb_geometry(source)
corner_array = np.asarray(corners)
indices = np.asarray(triangles)
positions = corner_array[indices, :3]
first_edge = positions[:, 1] - positions[:, 0]
second_edge = positions[:, 2] - positions[:, 0]
origin = np.asarray((0.0, 1221.600, 554.626))
pitch = math.radians(20)
forward = np.asarray((0.0, -math.cos(pitch), -math.sin(pitch)))
right = np.asarray((1.0, 0.0, 0.0))
up = np.asarray((0.0, -math.sin(pitch), math.cos(pitch)))
focal = 800 / math.tan(math.radians(22.5))
atlas = Image.open(texture).convert("RGB")
game = Image.open(screenshot).convert("RGB")
rows = []
for pixel in ((452, 681), (448, 642), (486, 737)):
    direction = forward + right * ((pixel[0] + 0.5 - 800) / focal) + up * ((450 - pixel[1] - 0.5) / focal)
    direction /= np.linalg.norm(direction)
    cross = np.cross(np.broadcast_to(direction, second_edge.shape), second_edge)
    determinant = np.einsum("ij,ij->i", first_edge, cross)
    valid = np.abs(determinant) > 1e-10
    inverse = np.divide(1.0, determinant, out=np.zeros_like(determinant), where=valid)
    relative = origin - positions[:, 0]
    bary_first = np.einsum("ij,ij->i", relative, cross) * inverse
    another = np.cross(relative, first_edge)
    bary_second = another @ direction * inverse
    distance = np.einsum("ij,ij->i", second_edge, another) * inverse
    valid &= (bary_first >= 0) & (bary_second >= 0) & (bary_first + bary_second <= 1) & (distance > 0)
    choices = np.where(valid)[0]
    row = {"pixel": list(pixel), "game_rgb": list(game.getpixel(pixel))}
    if len(choices):
        index = int(choices[np.argmin(distance[choices])])
        hit = origin + direction * distance[index]
        weights = np.asarray((1 - bary_first[index] - bary_second[index], bary_first[index], bary_second[index]))
        uv = weights @ corner_array[indices[index], 3:]
        atlas_pixel = tuple(min(2047, max(0, int(value * 2048))) for value in uv)
        row.update(source_glb_triangle=index, hit_ue_cm=hit.tolist(), hit_blender_cm=[float(hit[0]), -float(hit[1]), float(hit[2])],
                   source_vertices_ue_cm=positions[index].tolist(), source_uv=uv.tolist(), source_atlas_pixel=list(atlas_pixel),
                   source_atlas_rgb=list(atlas.getpixel(atlas_pixel)), source_min_z_cm=float(positions[index, :, 2].min()),
                   source_max_z_cm=float(positions[index, :, 2].max()), in_front_of_z0_plane=bool(hit[2] >= 0))
    rows.append(row)
report = {"status": "source_ground_fragment_localization_not_mesh_edit_approval", "source": str(source), "source_sha256": sha256(source),
          "screenshot": str(screenshot), "screenshot_sha256": sha256(screenshot), "rows": rows,
          "camera_evidence": "Actual capture log team0/distance1300 location(0,1221.600,554.626),rotation(-20,-90,0); CWCameraRig45deg horizontal FOV.",
          "limitations": "Finite manually selected screen pixels; logged camera is rounded and temporal antialiasing can shift subpixels. Does not prove every grey edge or component intersection.",
          "source_modified": False, "runtime_changed": False}
write_new(BASE / "team_color_v01/ground_pixel_probe.json", report)
print(json.dumps(report, ensure_ascii=False))
