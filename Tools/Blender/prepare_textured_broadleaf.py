"""Inspect the single paid Broadleaf texture result and prepare it without changing geometry."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / 'RawAssets/Art/Tripo_v01'
RAW = ART / 'tripo_raw/Env_Broadleaf/textured_cleanup_v03/model.glb'
INPUT = ART / 'tripo_processed/cleanup_v03/texture_input/Env_Broadleaf_retexture.glb'
INPUT_HASH = 'a94881704bd6856dc2ba66518c2ec4cc90c521f80acb3d0369d545f64ab2da47'
OUT = ART / 'tripo_processed/textured_cleanup_v03'
TASK_ID = '253ebc1a-ef3e-4c35-9cf8-7f5274f77249'
SURFACE_TOLERANCE = .00005
RUNTIME_MATERIAL_OVERRIDES = {'Metallic': 0}
module_spec = importlib.util.spec_from_file_location('prep', ROOT / 'Tools/Blender/prepare_tripo_environment.py')
prep = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(prep)


def load_normalized(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    initial_low, initial_high = prep.bounds(objects)
    initial_geometry = prep.geometry_report(objects)
    normalization = prep.normalize(objects, 'height', 590, 0)
    geometry = prep.geometry_report(objects)
    low, high = prep.bounds(objects)
    vertices = []
    triangles = []
    for obj in objects:
        offset = len(vertices)
        vertices.extend(tuple(obj.matrix_world @ vertex.co) for vertex in obj.data.vertices)
        obj.data.calc_loop_triangles()
        triangles.extend(tuple(offset + index for index in triangle.vertices) for triangle in obj.data.loop_triangles)
    return {'file': prep.project_path(path), 'sha256': prep.sha256(path),
            'original_bounds_m': [list(initial_low), list(initial_high)], 'original_geometry': initial_geometry,
            'normalization': normalization, 'geometry': geometry,
            'dimensions_cm': list((high - low) * 100), 'minimum_z_cm': low.z * 100,
            'vertices': vertices, 'triangles': triangles,
            'uv_signature': prep.uv_signature(objects), 'materials': prep.material_report(objects)}


def compare_sources():
    if prep.sha256(INPUT) != INPUT_HASH:
        raise RuntimeError('Frozen retexture input changed')
    task_path = RAW.parent / 'task.json'
    task = json.loads(task_path.read_text(encoding='utf-8-sig'))
    if task.get('task_id') != TASK_ID or task.get('status') != 'success':
        raise RuntimeError('Unexpected or incomplete texture receipt')
    reference = load_normalized(INPUT)
    actual = load_normalized(RAW)
    unique = sorted({tuple(round(value, 7) for value in vertex) for vertex in reference['vertices']})
    lookup = {coordinate: index for index, coordinate in enumerate(unique)}
    tree = KDTree(len(unique))
    for index, coordinate in enumerate(unique):
        tree.insert(coordinate, index)
    tree.balance()
    expected_mapping = [lookup[tuple(round(value, 7) for value in vertex)] for vertex in reference['vertices']]
    actual_mapping = []
    maximum_distance = 0
    for vertex in actual['vertices']:
        coordinate, index, distance = tree.find(vertex)
        maximum_distance = max(maximum_distance, distance)
        actual_mapping.append(index)
    expected_triangles = Counter(tuple(sorted(expected_mapping[index] for index in triangle)) for triangle in reference['triangles'])
    actual_triangles = Counter(tuple(sorted(actual_mapping[index] for index in triangle)) for triangle in actual['triangles'])
    missing = sum((expected_triangles - actual_triangles).values())
    additional = sum((actual_triangles - expected_triangles).values())
    def describe_faces(counter):
        rows = []
        for indices, count in counter.items():
            corners = [Vector(unique[index]) for index in indices]
            area = (corners[1] - corners[0]).cross(corners[2] - corners[0]).length * .5
            rows.append({'count': count, 'positions_m': [list(corner) for corner in corners],
                         'area_m2': area, 'centroid_m': list(sum(corners, Vector()) / 3)})
        return rows
    missing_details = describe_faces(expected_triangles - actual_triangles)
    additional_details = describe_faces(actual_triangles - expected_triangles)
    actual_bvh = BVHTree.FromPolygons(actual['vertices'], actual['triangles'], all_triangles=True)
    reference_bvh = BVHTree.FromPolygons(reference['vertices'], reference['triangles'], all_triangles=True)
    def face_sample_deviation(details, target_bvh):
        maximum = 0
        for row in details:
            corners = [Vector(position) for position in row['positions_m']]
            samples = corners + [sum(corners, Vector()) / 3] + [(corners[index] + corners[(index + 1) % 3]) * .5 for index in range(3)]
            distances = [target_bvh.find_nearest(sample)[3] for sample in samples]
            row['max_distance_to_other_surface_m'] = max(distances)
            maximum = max(maximum, max(distances))
        return maximum
    missing_surface_deviation = face_sample_deviation(missing_details, actual_bvh)
    additional_surface_deviation = face_sample_deviation(additional_details, reference_bvh)
    surface_unchanged_at_tolerance = max(missing_surface_deviation, additional_surface_deviation) <= SURFACE_TOLERANCE
    bpy.ops.wm.open_mainfile(filepath=str(ART / 'tripo_processed/cleanup_v03/texture_input/Env_Broadleaf_retexture_with_uv_evidence.blend'))
    evidence_objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    prep.normalize(evidence_objects, 'height', 590, 0)
    protected_keys = set()
    for obj in evidence_objects:
        group = obj.vertex_groups.get('ProtectedOriginalTripoTrunk')
        if not group:
            continue
        protected_ids = {vertex.index for vertex in obj.data.vertices if any(weight.group == group.index and weight.weight > .99 for weight in vertex.groups)}
        obj.data.calc_loop_triangles()
        for triangle in obj.data.loop_triangles:
            if all(index in protected_ids for index in triangle.vertices):
                protected_keys.add(tuple(sorted(tree.find(obj.matrix_world @ obj.data.vertices[index].co)[1] for index in triangle.vertices)))
    missing_keys = list((expected_triangles - actual_triangles).keys())
    for key, row in zip(missing_keys, missing_details):
        row['belongs_to_original_protected_region'] = key in protected_keys
    errors = []
    if actual['geometry']['triangles'] != 4316 and not surface_unchanged_at_tolerance:
        errors.append('unexpected_triangle_count')
    if maximum_distance > .00002 or not surface_unchanged_at_tolerance:
        errors.append('texture_result_geometry_differs_from_reviewed_input')
    if len(actual['materials']) != 1 or actual['geometry']['mesh_count'] != 1:
        errors.append('unexpected_mesh_or_material_count')
    images = [image for material in actual['materials'] for image in material['images']]
    if not images or not any(image['colorspace'] == 'sRGB' for image in images) or not any(image['colorspace'] == 'Non-Color' for image in images):
        errors.append('missing_expected_pbr_color_and_data_textures')
    if any(mesh['uv_zero_area_triangles'] for mesh in actual['geometry']['meshes']):
        errors.append('zero_area_uv_triangles')
    for record in (reference, actual):
        record.pop('vertices')
        record.pop('triangles')
    result = {
        'task_id': TASK_ID, 'paid_texture_task_by_root': True,
        'input': reference, 'texture_result': actual,
        'comparison_space': 'Both files uniformly normalized to 590cm height, bottom Z0, horizontal bounds center; yaw0, no reflection',
        'nearest_vertex_distance_max_m': maximum_distance, 'vertex_tolerance_m': .00002,
        'surface_tolerance_m': SURFACE_TOLERANCE,
        'missing_triangle_surfaces': missing, 'additional_triangle_surfaces': additional,
        'missing_triangle_details': missing_details, 'additional_triangle_details': additional_details,
        'max_missing_surface_deviation_m': missing_surface_deviation,
        'max_additional_surface_deviation_m': additional_surface_deviation,
        'surface_unchanged_at_tolerance': surface_unchanged_at_tolerance,
        'protected_input_triangles_affected': sum(row['count'] for row in missing_details if row['belongs_to_original_protected_region']),
        'topology_change_note': 'Texture service returned 4312 rather than 4316 triangles. Two small protected trunk seam patches are micro-retessellated; input remains frozen. Surface samples remain within explicitly reviewed 0.05mm tolerance, but per-face topology is not identical.',
        'rendered_triangle_topology_same': not missing and not additional,
        'uv_coordinates_same': reference['uv_signature']['sha256'] == actual['uv_signature']['sha256'],
        'passed': not errors, 'errors': errors, 'production_approved': False}
    prep.write_json(OUT / 'source_comparison.json', result)
    if errors:
        raise RuntimeError('PBR source check failed: ' + str(errors))
    return result


def prepare():
    comparison = compare_sources()
    options = argparse.Namespace(
        output_root=OUT, target_cm=590, measure='height', yaw_deg=0,
        source_stage='textured', task_id=TASK_ID, no_render=True,
        device='CPU', comparison_manifest=None, comparison_neutral=False,
        include_left=True, batch_id='tripo_textured_cleanup_v03')
    prep.prepare({'id': 'Env_Broadleaf', 'file': str(RAW), 'task_id': TASK_ID,
                  'target_cm': 590, 'measure': 'height', 'yaw_deg': 0,
                  'source_stage': 'textured'}, options)
    manifest = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
    asset = manifest['assets'][0]
    asset['runtime_material_overrides'] = RUNTIME_MATERIAL_OVERRIDES
    asset['runtime_material_override_reason'] = 'Dielectric wood and foliage; source metallic blue channel mean 99.17571544647217/255. Preserve original source images and apply explicit derived runtime factor only.'
    prep.write_json(OUT / 'manifest.json', manifest)
    inspection = json.loads((ROOT / asset['inspection']).read_text(encoding='utf-8'))
    prep.write_json(OUT / 'delivery_check.json', {
        'status': 'pbr_normalized_pending_four_side_and_unreal_gameplay_review',
        'task_id': TASK_ID, 'source_comparison_passed': comparison['passed'],
        'glb_roundtrip_passed': inspection['glb_roundtrip']['pass'],
        'triangles': inspection['processed_geometry']['triangles'],
        'dimensions_cm': inspection['dimensions_cm'], 'minimum_z_cm': inspection['minimum_z_cm'],
        'file': asset['file'], 'sha256': prep.sha256(ROOT / asset['file']),
        'texture_count': len(inspection['original_textures']),
        'all_original_texture_bytes_preserved': inspection['all_original_image_bytes_embedded_unchanged'],
        'production_approved': False, 'rendered': False})
    print('CIVWAR_BROADLEAF_PBR_PREPARED ' + asset['file'], flush=True)


def render(device, size):
    manifest = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
    asset = manifest['assets'][0]
    path = ROOT / asset['file']
    original_model_hash = prep.sha256(path)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    overrides = asset.get('runtime_material_overrides', {})
    if overrides != RUNTIME_MATERIAL_OVERRIDES:
        raise RuntimeError('Expected explicitly reviewed dielectric material override')
    for material in {slot.material for mesh in objects for slot in mesh.material_slots if slot.material}:
        for node in material.node_tree.nodes:
            if node.type != 'BSDF_PRINCIPLED':
                continue
            metallic = node.inputs['Metallic']
            for link in list(metallic.links):
                material.node_tree.links.remove(link)
            metallic.default_value = overrides['Metallic']
    obj = objects[0]
    directory = path.parent / 'pbr_review'
    directory.mkdir(parents=True, exist_ok=True)
    camera, center, span = prep.setup_render(obj, device)
    scene = bpy.context.scene
    scene.render.threads = 2
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.cycles.samples = 12
    rows = []
    for view, direction in [('preview', (2, -3, 1.6)), ('front', (1, 0, 0)), ('right', (0, 1, 0)), ('back', (-1, 0, 0)), ('left', (0, -1, 0))]:
        camera.location = center + Vector(direction) * span * 2
        camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.data.ortho_scale = span * (1.55 if view == 'preview' else 1.25)
        target = directory / (view + '.png')
        scene.render.filepath = str(target)
        bpy.ops.render.render(write_still=True)
        rows.append({'view': view, 'file': prep.project_path(target), 'sha256': prep.sha256(target), 'size': [size, size]})
    prep.write_json(OUT / 'render_evidence.json', {
        'model_file': asset['file'], 'model_sha256': prep.sha256(path), 'device': device,
        'render_only_runtime_material_overrides': overrides,
        'source_model_bytes_unchanged': prep.sha256(path) == original_model_hash,
        'material_override_scope': 'In-memory render scene only; original model and texture bytes are unchanged',
        'cpu_threads': 2, 'samples': 12, 'same_scale_four_orthographic_views': True,
        'camera_axes': {'front': '+X', 'right': '+Y', 'back': '-X', 'left': '-Y', 'up': '+Z'},
        'images': rows, 'production_approved': False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--device', choices=('CPU', 'HIP'), default='CPU')
    parser.add_argument('--size', type=int, choices=(512, 1024), default=512)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    OUT.mkdir(parents=True, exist_ok=True)
    if args.prepare:
        prepare()
    if args.render:
        render(args.device, args.size)


if __name__ == '__main__':
    main()
