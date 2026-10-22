"""Versioned crown-only cleanup experiments on an actual Tripo Broadleaf mesh.

Original files are read-only. All trial files live in tripo_processed/cleanup_v03.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import math
import shutil
import sys

import bpy
import bmesh
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'RawAssets/Art/Tripo_v01/tripo_processed/geometry_v03_canonical/Env_Broadleaf/h1d9fb6d0b738/Env_Broadleaf.glb'
OUT=ROOT/'RawAssets/Art/Tripo_v01/tripo_processed/cleanup_v03'
spec=importlib.util.spec_from_file_location('prep',ROOT/'Tools/Blender/prepare_tripo_environment.py')
prep=importlib.util.module_from_spec(spec);spec.loader.exec_module(prep)

def load_source():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(SOURCE))
    objects=[o for o in bpy.context.scene.objects if o.type=='MESH']
    prep.select(objects);bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    return prep.join_static(objects,'Env_Broadleaf')

def components(bm):
    bm.verts.ensure_lookup_table();bm.verts.index_update()
    unseen=set(bm.verts);rows=[]
    while unseen:
        seed=unseen.pop();verts={seed};stack=[seed]
        while stack:
            v=stack.pop()
            for e in v.link_edges:
                n=e.other_vert(v)
                if n in unseen: unseen.remove(n);verts.add(n);stack.append(n)
        faces={f for v in verts for f in v.link_faces}
        low=[min(v.co[i] for v in verts) for i in range(3)]
        high=[max(v.co[i] for v in verts) for i in range(3)]
        rows.append({'vertices':len(verts),'faces':len(faces),'bounds_m':[low,high],
                     'vertex_indices':sorted(v.index for v in verts)})
    return sorted(rows,key=lambda r:r['faces'],reverse=True)

def diagnose():
    obj=load_source()
    bm=bmesh.new();bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=0.00001)
    bm.normal_update()
    rows=components(bm)
    prep.write_json(OUT/'diagnostic_components.json',{'components':rows,'vertices':len(bm.verts),'faces':len(bm.faces),
                      'bounds_m':[[float(n) for n in v] for v in prep.bounds([obj])],
                      'vertices_m':[[float(c) for c in v.co] for v in bm.verts]})
    print(json.dumps({'components':[{k:v for k,v in row.items() if k!='vertex_indices'} for row in rows]},indent=2))
    bm.free()

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnose',action='store_true')
    parser.add_argument('--segment', action='store_true')
    parser.add_argument('--trials', action='store_true')
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--texture-input', action='store_true')
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--no-render', action='store_true')
    parser.add_argument('--device', choices=('CPU', 'HIP'), default='CPU')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    if args.diagnose: diagnose()
    if args.segment: segment(args)
    if args.trials: trials(args)
    if args.render: render_candidates(args)
    if args.texture_input: texture_input(args)


def checked_source():
    expected = '114fc9b0405872c56af03e6c6c02f2f23200ebbd918b2cb813e75ee8a7700e19'
    if prep.sha256(SOURCE) != expected:
        raise RuntimeError('Source differs from restart checkpoint')
    return load_source()


def neutral_material(name, color):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.diffuse_color = (*color, 1)
    shader = material.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Metallic'].default_value = 0
    shader.inputs['Roughness'].default_value = .8
    return material


def crown_face(face):
    point = face.center
    radial = math.hypot(point.x, point.y)
    for start, end, radius in [
        ((-.3, -.5, 1.3), (.3, -1.9, 2.9), .5),
        ((-.1, -.5, 1.5), (-.8, -2.1, 3.2), .55),
        ((0, 0, 1.3), (1.2, 1.6, 2.25), .4),
        ((1.2, 1.6, 2.25), (1.9, 2.1, 2.5), .25),
        ((0, 0, 3), (.3, 0, 4.4), .45),
    ]:
        start = Vector(start)
        direction = Vector(end) - start
        fraction = max(0, min(1, (point - start).dot(direction) / direction.length_squared))
        if (point - start - direction * fraction).length < radius:
            return False
    if point.z < 1.8: return False
    if point.z > 4.35: return True
    if point.z > 3.85 and radial > .95: return True
    if point.z > 2.25 and radial > 1.28: return True
    if point.z > 1.8 and radial > 2: return True
    return False


def face_signature(obj):
    layers = obj.data.uv_layers
    rows = []
    for face in obj.data.polygons:
        corners = []
        for loop_index in face.loop_indices:
            vertex = obj.data.vertices[obj.data.loops[loop_index].vertex_index]
            corners.append({'position': list(vertex.co), 'uv': [list(layer.data[loop_index].uv) for layer in layers]})
        rows.append(corners)
    return hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()


def extract_faces(source, face_ids, name):
    face_ids = sorted(face_ids)
    vertex_ids = sorted({vertex_id for face_id in face_ids for vertex_id in source.data.polygons[face_id].vertices})
    vertex_map = {source_id: target_id for target_id, source_id in enumerate(vertex_ids)}
    mesh = bpy.data.meshes.new(name + '_Mesh')
    mesh.from_pydata([tuple(source.data.vertices[index].co) for index in vertex_ids], [],
                     [[vertex_map[index] for index in source.data.polygons[face_id].vertices] for face_id in face_ids])
    mesh.update()
    for source_layer in source.data.uv_layers:
        target_layer = mesh.uv_layers.new(name=source_layer.name)
        for target_face, source_id in zip(mesh.polygons, face_ids):
            for target_loop, source_loop in zip(target_face.loop_indices, source.data.polygons[source_id].loop_indices):
                target_layer.data[target_loop].uv = source_layer.data[source_loop].uv
    for target_face, source_id in zip(mesh.polygons, face_ids):
        target_face.use_smooth = source.data.polygons[source_id].use_smooth
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj['source_task_id'] = '14f98998-e7a7-49bb-8196-0080d50c015c'
    obj['source_face_count'] = len(face_ids)
    return obj


def root_connected_faces(source, face_ids):
    vertex_faces = {}
    face_keys = {}
    for face_id in face_ids:
        coordinates = [source.data.vertices[index].co for index in source.data.polygons[face_id].vertices]
        keys = {tuple(round(value, 5) for value in coordinate) for coordinate in coordinates}
        face_keys[face_id] = keys
        for key in keys:
            vertex_faces.setdefault(key, set()).add(face_id)
    retained = {face_id for face_id in face_ids if source.data.polygons[face_id].center.z < .5}
    stack = list(retained)
    while stack:
        face_id = stack.pop()
        for key in face_keys[face_id]:
            for neighbor in vertex_faces[key] - retained:
                retained.add(neighbor)
                stack.append(neighbor)
    return sorted(retained)


def segmentation(source):
    crown_ids = [face.index for face in source.data.polygons if crown_face(face)]
    crown_set = set(crown_ids)
    initial_trunk_ids = [face.index for face in source.data.polygons if face.index not in crown_set]
    trunk_ids = root_connected_faces(source, initial_trunk_ids)
    detached_ids = sorted(set(initial_trunk_ids) - set(trunk_ids))
    crown_ids = sorted(crown_set | set(detached_ids))
    trunk = extract_faces(source, trunk_ids, 'Protected_Tripo_Trunk_MainBranches')
    crown = extract_faces(source, crown_ids, 'Tripo_Crown_RepairRegion')
    trunk.data.materials.append(neutral_material('MASK_Protected_Teal', (.04, .52, .55)))
    crown.data.materials.append(neutral_material('MASK_Crown_Orange', (.95, .24, .045)))
    report = {
        'source_file': prep.project_path(SOURCE), 'source_sha256': prep.sha256(SOURCE),
        'task_id': '14f98998-e7a7-49bb-8196-0080d50c015c', 'source_faces': len(source.data.polygons),
        'protected_source_face_ids': trunk_ids, 'crown_source_face_ids': crown_ids,
        'protected_faces': len(trunk_ids), 'crown_faces': len(crown_ids),
        'protected_vertices': len(trunk.data.vertices),
        'detached_underside_faces_transferred_to_crown_repair': detached_ids,
        'protected_position_topology_uv_sha256': face_signature(trunk),
        'method': 'Spatial face mask with explicit branch-protection capsules and root connectivity. Original faces copied without moving vertices or changing per-corner UVs. Disconnected underside islands join crown repair. Four-view color-mask review required.',
        'mask_colors': {'teal': 'protected original trunk/main branches', 'orange': 'original crown repair region'},
        'source_uvs_kept_on_protected_mesh': True, 'mask_review_required_before_trials': True}
    source.hide_render = True
    source.hide_set(True)
    return trunk, crown, report


def render_objects(objects, directory, device, frame, quick=False):
    directory.mkdir(parents=True, exist_ok=True)
    camera, center, span = prep.setup_render(objects[0], device, frame)
    scene = bpy.context.scene
    scene.render.threads = 2
    if quick:
        scene.render.resolution_x = scene.render.resolution_y = 512
        scene.cycles.samples = 8
    for view, direction in [('preview', (2, -3, 1.6)), ('front', (1, 0, 0)), ('right', (0, 1, 0)), ('back', (-1, 0, 0)), ('left', (0, -1, 0))]:
        camera.location = center + Vector(direction) * span * 2
        camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.data.ortho_scale = span * (1.55 if view == 'preview' else 1.25)
        scene.render.filepath = str(directory / (view + '.png'))
        bpy.ops.render.render(write_still=True)


def segment(args):
    source = checked_source()
    low, high = prep.bounds([source])
    trunk, crown, report = segmentation(source)
    prep.write_json(OUT / 'segmentation.json', report)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'segmentation.blend'))
    if not args.no_render:
        render_objects([trunk, crown], OUT / 'segmentation', args.device, ((low + high) * .5, max(high - low)), args.quick)


def repair_crown(obj, voxel_size):
    prep.select([obj])
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    bmesh.ops.remove_doubles(mesh, verts=list(mesh.verts), dist=.00001)
    bmesh.ops.recalc_face_normals(mesh, faces=list(mesh.faces))
    boundary_edges = [edge for edge in mesh.edges if edge.is_boundary]
    holes = bmesh.ops.holes_fill(mesh, edges=boundary_edges, sides=0)
    filled_faces = len(holes.get('faces', []))
    bmesh.ops.recalc_face_normals(mesh, faces=list(mesh.faces))
    mesh.to_mesh(obj.data)
    mesh.free()
    obj.data.update()
    obj.data.validate(verbose=True, clean_customdata=True)
    solidify = obj.modifiers.new('CrownOnly_Solidify', 'SOLIDIFY')
    solidify.thickness = voxel_size * 2
    solidify.offset = -.3
    solidify.use_even_offset = False
    solidify.thickness_clamp = .5
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    obj.data.remesh_voxel_size = voxel_size
    obj.data.remesh_voxel_adaptivity = 0
    obj.data.use_remesh_preserve_volume = True
    bpy.ops.object.voxel_remesh()
    pre_smooth = prep.geometry_report([obj])
    smooth = obj.modifiers.new('CrownOnly_Relax', 'SMOOTH')
    smooth.factor = .65
    smooth.iterations = 4
    bpy.ops.object.modifier_apply(modifier=smooth.name)
    obj.data.calc_loop_triangles()
    if len(obj.data.loop_triangles) > 3200:
        decimate = obj.modifiers.new('CrownOnly_GameBudget', 'DECIMATE')
        decimate.ratio = 3200 / len(obj.data.loop_triangles)
        decimate.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=decimate.name)
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    bmesh.ops.remove_doubles(mesh, verts=list(mesh.verts), dist=.00001)
    bmesh.ops.dissolve_degenerate(mesh, dist=.00001, edges=list(mesh.edges))
    bmesh.ops.recalc_face_normals(mesh, faces=list(mesh.faces))
    mesh.to_mesh(obj.data)
    mesh.free()
    obj.data.update()
    obj.data.validate(verbose=True, clean_customdata=True)
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    residual_boundaries = [edge for edge in mesh.edges if edge.is_boundary]
    residual_caps = bmesh.ops.holes_fill(mesh, edges=residual_boundaries, sides=4)
    bmesh.ops.triangulate(mesh, faces=list(mesh.faces))
    bmesh.ops.recalc_face_normals(mesh, faces=list(mesh.faces))
    mesh.to_mesh(obj.data)
    mesh.free()
    obj.data.validate(verbose=True, clean_customdata=True)
    obj.data.update()
    for face in obj.data.polygons:
        face.use_smooth = True
    for layer in list(obj.data.uv_layers):
        obj.data.uv_layers.remove(layer)
    prep.select([obj])
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=1.151917306, island_margin=.025)
    bpy.ops.object.mode_set(mode='OBJECT')
    return {'voxel_size_m': voxel_size, 'solidify_thickness_m': voxel_size * 2,
            'solidify_offset': -.3, 'boundary_caps_added': filled_faces,
            'residual_boundary_caps_after_decimation': len(residual_caps.get('faces', [])),
            'pre_smoothing_geometry': pre_smooth, 'smoothing_factor': .65, 'smoothing_iterations': 4,
            'crown_triangle_target': 3200,
            'uv_policy': 'New crown smart-project UVs. Old crown UVs discarded. Original protected trunk UVs unchanged.',
            'volume_note': 'Source crown is nonmanifold/open, so source signed volume is not ground truth. Capping, thickness and voxel closure are explicit repair assumptions.'}


def export_objects(objects, stem):
    stem.parent.mkdir(parents=True, exist_ok=True)
    prep.select(objects)
    bpy.ops.export_scene.gltf(filepath=str(stem.with_suffix('.glb')), export_format='GLB', use_selection=True,
                              export_apply=False, export_yup=True, export_extras=True, export_animations=False)
    bpy.ops.export_scene.fbx(filepath=str(stem.with_suffix('.fbx')), use_selection=True, object_types={'MESH'},
                             apply_unit_scale=True, apply_scale_options='FBX_SCALE_UNITS', axis_forward='X', axis_up='Z',
                             use_mesh_modifiers=False, bake_anim=False, use_custom_props=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(stem.with_suffix('.blend')))


def trials(args):
    mask_review = OUT / 'segmentation_review.json'
    if not mask_review.is_file() or not json.loads(mask_review.read_text(encoding='utf-8')).get('approved_for_local_trials'):
        raise RuntimeError('Review color-mask renders and write segmentation_review.json before trials')
    approved = json.loads(mask_review.read_text(encoding='utf-8'))
    if approved['segmentation_sha256'] != prep.sha256(OUT / 'segmentation.json'):
        raise RuntimeError('Segmentation differs from reviewed mask')
    for voxel_size in (.06, .10):
        source = checked_source()
        trunk, crown, segmentation_report = segmentation(source)
        original_signature = face_signature(trunk)
        trial_name = 'voxel_' + str(round(voxel_size * 100)).zfill(2) + 'cm'
        directory = OUT / trial_name
        directory.mkdir(parents=True, exist_ok=True)
        process = repair_crown(crown, voxel_size)
        pre_height = max(vertex.co.z for vertex in crown.data.vertices)
        crown_height_scale = (5.9 - 1.8) / (pre_height - 1.8)
        for vertex in crown.data.vertices:
            vertex.co.z = 1.8 + (vertex.co.z - 1.8) * crown_height_scale
        crown.data.update()
        process['crown_only_vertical_normalization'] = {
            'target_height_m': 5.9, 'anchor_z_m': 1.8, 'scale_factor': crown_height_scale,
            'pre_normalization_maximum_z_m': pre_height,
            'protected_trunk_and_branches_scaled': False}
        signature = face_signature(trunk)
        if signature != original_signature:
            raise RuntimeError('Protected source trunk/branch data changed')
        material = neutral_material('Broadleaf_UV_Ready_Untextured', (.4, .4, .4))
        for obj in (trunk, crown):
            obj.data.materials.clear()
            obj.data.materials.append(material)
        bpy.data.objects.remove(source, do_unlink=True)
        stem = directory / 'Env_Broadleaf_cleaned'
        geometry = prep.geometry_report([trunk, crown])
        low, high = prep.bounds([trunk, crown])
        export_objects([trunk, crown], stem)
        report = {'status': 'candidate_pending_visual_review', 'source_file': prep.project_path(SOURCE),
                  'source_sha256': prep.sha256(SOURCE), 'task_id': segmentation_report['task_id'],
                  'method': process, 'geometry': geometry, 'dimensions_cm': list((high - low) * 100),
                  'minimum_z_cm': low.z * 100,
                  'protected_faces': segmentation_report['protected_faces'],
                  'protected_vertices': segmentation_report['protected_vertices'],
                  'protected_position_topology_uv_sha256_before': original_signature,
                  'protected_position_topology_uv_sha256_after': signature,
                  'protected_geometry_and_uv_exact': original_signature == signature,
                  'changed_region': 'original Tripo crown faces only', 'production_approved': False,
                  'textures_present': False, 'requires_retexturing': True,
                  'junction_policy': 'Original branch surfaces retained exactly. Crown-side cuts capped/solidified/remeshed; overlap reviewed in four views.',
                  'outputs': {extension: prep.project_path(stem.with_suffix('.' + extension)) for extension in ('glb', 'fbx', 'blend')}}
        report['glb_roundtrip'] = prep.verify_roundtrip(stem.with_suffix('.glb'), report['dimensions_cm'], geometry['triangles'], 1, True)
        prep.write_json(directory / 'inspection.json', report)
        if not report['glb_roundtrip']['pass']:
            raise RuntimeError('Candidate GLB roundtrip failed: ' + str(report['glb_roundtrip']['errors']))
        print('CIVWAR_CROWN_TRIAL ' + trial_name + ' ' + str(geometry['triangles']), flush=True)


def render_candidates(args):
    source = checked_source()
    low, high = prep.bounds([source])
    frame = ((low + high) * .5, max(high - low))
    entries = [('source_control', SOURCE)] + [(name, OUT / name / 'Env_Broadleaf_cleaned.glb') for name in ('voxel_06cm', 'voxel_10cm')]
    for name, path in entries:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(path))
        objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
        neutral = neutral_material('REVIEW_Same_Neutral_Material', (.4, .4, .4))
        for obj in objects:
            obj.data.materials.clear()
            obj.data.materials.append(neutral)
        render_objects(objects, OUT / name / 'renders', args.device, frame, args.quick)
    prep.write_json(OUT / 'camera_comparison.json', {'shared_camera_center_m': list(frame[0]), 'shared_span_m': frame[1],
        'views': ['preview', 'front', 'right', 'back', 'left'], 'identical_camera_lighting_and_material': True,
        'size': [512, 512] if args.quick else [1024, 1024], 'device': args.device})


def geometry_signature(obj):
    obj.data.calc_loop_triangles()
    faces = []
    for triangle in obj.data.loop_triangles:
        faces.append(sorted(tuple(round(value, 6) for value in obj.matrix_world @ obj.data.vertices[index].co) for index in triangle.vertices))
    return hashlib.sha256(json.dumps(sorted(faces), separators=(',', ':')).encode()).hexdigest()


def texture_input(args):
    source = checked_source()
    protected, unused_crown, mask = segmentation(source)
    protected_signature = geometry_signature(protected)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    candidate = OUT / 'voxel_10cm/Env_Broadleaf_cleaned.glb'
    bpy.ops.import_scene.gltf(filepath=str(candidate))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    prep.select(objects)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    protected = next(obj for obj in objects if obj.name.startswith('Protected_'))
    crown = next(obj for obj in objects if obj.name.startswith('Tripo_Crown'))
    if geometry_signature(protected) != protected_signature:
        raise RuntimeError('Exported candidate changed protected triangle geometry')
    cavity = bmesh.new()
    cavity.from_mesh(crown.data)
    bmesh.ops.remove_doubles(cavity, verts=list(cavity.verts), dist=.00001)
    edges = [edge for edge in cavity.edges if edge.is_boundary]
    boundary_vertices = {vertex for edge in edges for vertex in edge.verts}
    adjacent_faces = {face for edge in edges for face in edge.link_faces}
    boundary_report = {
        'boundary_edges': len(edges), 'boundary_vertices_m': [list(vertex.co) for vertex in boundary_vertices],
        'adjacent_face_count': len(adjacent_faces), 'adjacent_face_areas_m2': [face.calc_area() for face in adjacent_faces],
        'action': 'none'}
    if len(edges) == 3 and len(boundary_vertices) == 3 and len(adjacent_faces) == 1:
        isolated_face = next(iter(adjacent_faces))
        if all(edge.is_boundary for edge in isolated_face.edges):
            boundary_report['diagnosis'] = 'Isolated single triangle, not a missing face in a surrounding shell'
            if isolated_face.calc_area() < .001:
                bmesh.ops.delete(cavity, geom=list(adjacent_faces), context='FACES')
                boundary_report['action'] = 'Remove one tiny isolated crown remesh artifact; no protected face touched'
    elif len(edges) == 3 and len(boundary_vertices) == 3 and len(adjacent_faces) >= 2:
        created = bmesh.ops.holes_fill(cavity, edges=edges, sides=3)
        boundary_report['action'] = 'Cap triangular crown boundary with ' + str(len(created.get('faces', []))) + ' face'
    bmesh.ops.recalc_face_normals(cavity, faces=list(cavity.faces))
    cavity.to_mesh(crown.data)
    cavity.free()
    crown.data.validate(verbose=True, clean_customdata=True)
    crown.data.update()
    if geometry_signature(protected) != protected_signature:
        raise RuntimeError('Micro-boundary processing touched protected geometry')
    directory = OUT / 'texture_input'
    directory.mkdir(parents=True, exist_ok=True)
    prep.write_json(directory / 'micro_boundary_review.json', boundary_report)
    for obj in objects:
        for layer in obj.data.uv_layers:
            layer.name = 'OriginalEvidenceUV'
    protected_group = protected.vertex_groups.new(name='ProtectedOriginalTripoTrunk')
    protected_group.add(list(range(len(protected.data.vertices))), 1, 'REPLACE')
    prep.select(objects)
    bpy.ops.object.join()
    joined = bpy.context.object
    joined.name = 'Env_Broadleaf_Cleaned_RetextureInput'
    original_layer = joined.data.uv_layers.get('OriginalEvidenceUV')
    if original_layer is None:
        raise RuntimeError('Original UV evidence layer missing after join')
    evidence_uv_hash = prep.uv_signature([joined])['sha256']
    atlas = joined.data.uv_layers.new(name='RetextureUV')
    joined.data.uv_layers.active = atlas
    atlas.active_render = True
    prep.select([joined])
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=1.151917306, island_margin=.02)
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.average_islands_scale()
    bpy.ops.uv.pack_islands(rotate=True, margin_method='FRACTION', margin=.01, shape_method='CONVEX')
    bpy.ops.object.mode_set(mode='OBJECT')
    joined.data.update()
    uv_spec = importlib.util.spec_from_file_location('uvcheck', directory / 'validate_texture_uv.py')
    uvcheck = importlib.util.module_from_spec(uv_spec)
    uv_spec.loader.exec_module(uvcheck)
    uv_repairs = []
    for iteration in range(4):
        joined.data.calc_loop_triangles()
        atlas = joined.data.uv_layers.get('RetextureUV')
        triangle_uvs = [[tuple(atlas.data[index].uv) for index in triangle.loops] for triangle in joined.data.loop_triangles]
        pair_count, overlaps = uvcheck.overlapping_pairs(triangle_uvs)
        if not overlaps:
            break
        if iteration == 3:
            raise RuntimeError('UV atlas still overlaps after three targeted seam repairs')
        affected_faces = {joined.data.loop_triangles[index].polygon_index for row in overlaps for index in row['triangles']}
        uv_repairs.append({'iteration': iteration + 1, 'overlapping_triangle_pairs': len(overlaps), 'isolated_faces': len(affected_faces)})
        for island_index, face_id in enumerate(sorted(affected_faces)):
            offset = Vector((10 + (island_index % 16) * 2, 10 + (island_index // 16) * 2))
            for loop_index in joined.data.polygons[face_id].loop_indices:
                atlas.data[loop_index].uv += offset
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.select_all(action='SELECT')
        bpy.ops.uv.pack_islands(rotate=True, margin_method='FRACTION', margin=.01, shape_method='CONVEX')
        bpy.ops.object.mode_set(mode='OBJECT')
        joined.data.update()
    material = neutral_material('Broadleaf_Untextured_RetextureAtlas', (.4, .4, .4))
    joined.data.materials.clear()
    joined.data.materials.append(material)
    for face in joined.data.polygons:
        face.material_index = 0
    group_index = joined.vertex_groups.get('ProtectedOriginalTripoTrunk').index
    protected_vertex_ids = {vertex.index for vertex in joined.data.vertices if any(group.group == group_index and group.weight > .99 for group in vertex.groups)}
    protected_face_ids = [face.index for face in joined.data.polygons if all(index in protected_vertex_ids for index in face.vertices)]
    check = extract_faces(joined, protected_face_ids, 'TEMP_Protected_Geometry_Check')
    protected_final_signature = geometry_signature(check)
    bpy.data.objects.remove(check, do_unlink=True)
    if protected_final_signature != protected_signature:
        raise RuntimeError('Joining or UV atlas processing changed protected triangles')
    atlas = joined.data.uv_layers.get('RetextureUV')
    original_layer = joined.data.uv_layers.get('OriginalEvidenceUV')
    uv_min = [min(loop.uv[axis] for loop in atlas.data) for axis in range(2)]
    uv_max = [max(loop.uv[axis] for loop in atlas.data) for axis in range(2)]
    geometry = prep.geometry_report([joined])
    low, high = prep.bounds([joined])
    stem = directory / 'Env_Broadleaf_retexture'
    bpy.ops.wm.save_as_mainfile(filepath=str(directory / 'Env_Broadleaf_retexture_with_uv_evidence.blend'))
    joined.data.uv_layers.remove(original_layer)
    joined.data.uv_layers.active_index = 0
    joined.data.uv_layers[0].active_render = True
    export_objects([joined], stem)
    report = {
        'status': 'local_geometry_approved_for_texture_validation_only', 'production_approved': False,
        'source_task_id': mask['task_id'], 'source_sha256': prep.sha256(SOURCE),
        'candidate_file': prep.project_path(candidate), 'candidate_sha256': prep.sha256(candidate),
        'file': prep.project_path(stem.with_suffix('.glb')), 'sha256': prep.sha256(stem.with_suffix('.glb')),
        'triangles': geometry['triangles'], 'dimensions_cm': list((high - low) * 100),
        'minimum_z_cm': low.z * 100, 'materials': 1, 'meshes': 1,
        'protected_original_faces': len(protected_face_ids),
        'protected_geometry_signature_before': protected_signature,
        'protected_geometry_signature_after': protected_final_signature,
        'protected_geometry_exact': protected_signature == protected_final_signature,
        'original_uv_evidence_file': prep.project_path(directory / 'Env_Broadleaf_retexture_with_uv_evidence.blend'),
        'original_uv_evidence_sha256': evidence_uv_hash,
        'uv_policy': 'Single new packed RetextureUV atlas for all geometry. Original per-corner UVs retained in separate evidence BLEND, not reused on changed crown topology.',
        'uv_pack': {'operator': 'smart_project, average_islands_scale, pack_islands', 'shape_method': 'CONVEX', 'margin_fraction': .01, 'minimum': uv_min, 'maximum': uv_max},
        'uv_overlap_repairs': uv_repairs,
        'uv_overlap_check': {'candidate_pairs': pair_count, 'overlapping_triangle_pairs': len(overlaps), 'area_tolerance_uv2': 1e-10},
        'micro_boundary': boundary_report,
        'requires_local_mesh_import_before_texture': True,
        'must_not_texture_original_task_geometry': True,
        'pending': ['new Tripo texture on this exact local mesh', 'PBR four-side review', 'UE import and both-team game cameras/performance']}
    report['glb_roundtrip'] = prep.verify_roundtrip(stem.with_suffix('.glb'), report['dimensions_cm'], geometry['triangles'], 1, True)
    prep.write_json(directory / 'review.json', report)
    if not report['glb_roundtrip']['pass']:
        raise RuntimeError('Texture input GLB roundtrip failed')
    if any(mesh['uv_zero_area_triangles'] for mesh in report['glb_roundtrip']['geometry']['meshes']):
        raise RuntimeError('Texture input has zero-area UV triangles')
    print('CIVWAR_BROADLEAF_TEXTURE_INPUT ' + report['sha256'] + ' ' + str(report['triangles']), flush=True)

if __name__=='__main__': main()
