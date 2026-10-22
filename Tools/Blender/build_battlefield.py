"""Build the CivWar environment DCC pilot; run with Blender's Python.

blender --background --python Tools/Blender/build_battlefield.py -- --version v01
All geometry is authored in centimetres. This is a reusable DCC first pass,
not a Tripo generation or a claim of final in-game acceptance.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
PALETTE = {}
MOTHERS = {}
INSTANCES = []
RNG = random.Random(20261020)


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def material(name, color, roughness=0.9):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    p = mat.node_tree.nodes.get("Principled BSDF")
    p.inputs["Base Color"].default_value = (*color, 1)
    p.inputs["Roughness"].default_value = roughness
    return mat


def mesh_object(name, vertices, faces, mat, collection=None):
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    (collection or bpy.context.scene.collection).objects.link(obj)
    obj.data.materials.append(mat)
    return obj


def move_collection(obj, collection):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    collection.objects.link(obj)


def bevel(obj, amount, segments=2):
    mod = obj.modifiers.new("Broad_worn_edges", "BEVEL")
    mod.width = amount
    mod.segments = segments
    mod.affect = 'EDGES'
    mod.limit_method = 'ANGLE'
    mod.angle_limit = math.radians(26)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)


def joined(name, parts, normalize_bottom=True):
    bpy.ops.object.select_all(action='DESELECT')
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    if len(parts)>1:bpy.ops.object.join()
    obj = bpy.context.object
    obj.name = name
    bpy.context.scene.cursor.location = (0, 0, 0)
    bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    if normalize_bottom:
        minimum_z=min(v.co.z for v in obj.data.vertices)
        for v in obj.data.vertices:
            v.co.z-=minimum_z
    bm=bmesh.new();bm.from_mesh(obj.data)
    bmesh.ops.recalc_face_normals(bm,faces=bm.faces)
    bm.to_mesh(obj.data);bm.free()
    # Explicit UVs are supplied so engine import can generate a separate lightmap.
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.025)
    bpy.ops.object.mode_set(mode='OBJECT')
    return obj


def ring_solid(name, rings, mat, fan_caps=False):
    n = len(rings[0])
    verts = [v for ring in rings for v in ring]
    faces = [] if fan_caps else [tuple(reversed(range(n)))]
    for j in range(len(rings)-1):
        for i in range(n):
            k = (i+1) % n
            faces.append((j*n+i, j*n+k, (j+1)*n+k, (j+1)*n+i))
    if fan_caps:
        bottom_index=len(verts)
        verts.append(tuple(sum(v[k] for v in rings[0])/n for k in range(3)))
        top_index=len(verts)
        verts.append(tuple(sum(v[k] for v in rings[-1])/n for k in range(3)))
        first_top=(len(rings)-1)*n
        for i in range(n):
            j=(i+1)%n
            faces.append((j,i,bottom_index))
            faces.append((first_top+i,first_top+j,top_index))
    else:
        faces.append(tuple((len(rings)-1)*n+i for i in range(n)))
    return mesh_object(name, verts, faces, mat)


def boulder_a():
    radial = [1.0, .89, 1.1, .94, .87, 1.06, .96, .90, 1.04]
    rings = []
    for radius, z, offset in [(.86, 0, (0,0)), (1.0, 25, (2,-1)), (.73, 61, (-7,4)), (.38, 75, (-10,6))]:
        ring = []
        for i, r in enumerate(radial):
            a = i * math.tau / len(radial)
            ring.append((math.cos(a)*64*radius*r+offset[0], math.sin(a)*51*radius*r+offset[1], z+(math.sin(i*2.1)*4 if z else 0)))
        rings.append(ring)
    obj = ring_solid("Env_BoulderA", rings, PALETTE['stone'])
    bevel(obj, 2.8)
    obj.data.materials.append(PALETTE['stone_light'])
    for poly in obj.data.polygons:
        if poly.normal.z > .65:
            poly.material_index = 1
    return joined("Env_BoulderA", [obj])


def boulder_b():
    outline = [(-86,-29),(-59,-47),(43,-41),(80,-18),(67,31),(16,45),(-61,35)]
    rings = []
    for level in range(3):
        ring=[]
        for x,y in outline:
            if level == 0: ring.append((x*.92,y*.94,0))
            elif level == 1: ring.append((x,y,16))
            else: ring.append((x*.71-12,y*.76,37+(86-x)*.19))
        rings.append(ring)
    obj=ring_solid("Env_BoulderB",rings,PALETTE['stone'])
    bevel(obj,2.4)
    return joined("Env_BoulderB",[obj])


def slab():
    outline=[(-61,-21),(-39,-41),(34,-38),(55,-17),(51,29),(18,31),(6,43),(-53,32)]
    rings=[[(x*.95,y*.95,0) for x,y in outline],[(x,y,13) for x,y in outline],[(x*.92,y*.93,22+(i%3)*1.3) for i,(x,y) in enumerate(outline)]]
    obj=ring_solid('Env_RockSlab',rings,PALETTE['stone'])
    bevel(obj,1.7)
    return joined('Env_RockSlab',[obj])


def branch(name, start, end, radius, mat, end_radius=None, vertices=8):
    start, end = Vector(start), Vector(end)
    delta=end-start
    bpy.ops.mesh.primitive_cone_add(vertices=vertices, radius1=radius, radius2=end_radius or radius*.65, depth=delta.length, location=(start+end)*.5)
    obj=bpy.context.object
    obj.name=name
    obj.rotation_euler=delta.to_track_quat('Z','Y').to_euler()
    obj.data.materials.append(mat)
    return obj


def foliage(name, location, scale, mat, seed):
    rnd=random.Random(seed)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1, location=location)
    obj=bpy.context.object
    obj.name=name
    for v in obj.data.vertices:
        v.co *= rnd.uniform(.91,1.08)
        if v.co.z < -.57: v.co.z = -.57+(v.co.z+.57)*.35
        if v.co.z > .78: v.co.z = .78+(v.co.z-.78)*.5
        v.co.x*=scale[0]; v.co.y*=scale[1]; v.co.z*=scale[2]
    obj.data.materials.append(mat)
    bevel(obj,min(scale)*.035,1)
    return obj


def shrub():
    parts=[branch('Shrub_stem',(0,0,0),(0,0,43),7,PALETTE['bark'])]
    for i,(loc,sz) in enumerate([((-28,-8,40),(44,40,38)),((27,3,43),(39,43,40)),((-5,24,58),(43,37,34))]):
        parts.append(foliage('Shrub_mass',loc,sz,PALETTE[['leaf_dark','leaf','leaf_light'][i]],200+i))
    return joined('Env_Shrub',parts)


def pine():
    parts=[branch('Pine_trunk',(0,0,0),(8,-3,575),22,PALETTE['bark'],8,10)]
    for layer,(z,r,h,ox,oy) in enumerate([(150,173,242,-13,5),(300,137,227,7,-8),(447,95,214,13,5)]):
        n=11
        rings=[]
        for frac,rad in [(0,.73),(.12,1),(.28,.78),(.57,.49),(.95,.045)]:
            ring=[]
            for i in range(n):
                a=math.tau*i/n+layer*.27
                rr=r*rad*(1+.11*math.sin(i*2.15+layer))
                zz=z+h*frac+(math.sin(i*2.7+layer)*r*.07 if frac<.8 else 0)
                ring.append((ox+math.cos(a)*rr,oy+math.sin(a)*rr,zz))
            rings.append(ring)
        crown=ring_solid('Pine_layer',rings,PALETTE[['pine_dark','pine','pine_light'][layer]],fan_caps=True)
        # Overlap-clamped micro-bevels produce tiny crown triangles/UV slivers
        # that Unreal's tangent builder rejects. The ring profile already has
        # broad rounded corners; retain those substantial planes without slivers.
        parts.append(crown)
    return joined('Env_Pine',parts)


def broadleaf():
    parts=[branch('Broadleaf_trunk',(0,0,0),(-12,4,325),26,PALETTE['bark'],16,9)]
    clusters=[((-125,12,350),(147,133,132)),((123,30,365),(150,140,143)),((-35,-89,423),(150,134,140)),((20,70,458),(143,145,148))]
    for i,(loc,sz) in enumerate(clusters):
        parts.append(branch('Branch',(-10,0,230),(loc[0],loc[1],loc[2]-25),12,PALETTE['bark'],6))
        parts.append(foliage('Broadleaf_crown',loc,sz,PALETTE[['leaf_dark','leaf','leaf','leaf_light'][i]],300+i))
    return joined('Env_Broadleaf',parts)


def grass():
    parts=[]
    for i in range(5):
        a=i*math.tau/5+.2
        h=[31,37,28,43,34][i]
        w=[6,7,5,7,6][i]
        bx,by=math.cos(a)*3,math.sin(a)*3
        wx,wy=-math.sin(a)*w,math.cos(a)*w
        verts=[(bx-wx,by-wy,0),(bx+wx,by+wy,0),(wx*.48+bx+math.cos(a)*5,wy*.48+by+math.sin(a)*6,h*.58),(-wx*.48+bx+math.cos(a)*5,-wy*.48+by+math.sin(a)*6,h*.58),(bx+math.cos(a)*13,by+math.sin(a)*14,h)]
        # A closed thick wedge avoids two-sided material requirements in Unreal.
        vertices=verts+[(x+math.cos(a)*1.2,y+math.sin(a)*1.2,z) for x,y,z in verts]
        faces=[(0,1,2,3),(3,2,4),(8,7,6,5),(9,7,8),(0,5,6,1),(1,6,7,2),(2,7,9,4),(4,9,8,3),(3,8,5,0)]
        parts.append(mesh_object('Grass_blade',vertices,faces,PALETTE['grass']))
    return joined('Env_GrassClump',parts)


def smoothstep(a,b,x):
    t=max(0,min(1,(x-a)/(b-a)))
    return t*t*(3-2*t)


def noise(x,y):
    return .5*math.sin(x*.0011+y*.0007)+.3*math.sin(x*.0023-y*.0019+1.7)+.2*math.sin(x*.0051+y*.0043+4.1)


def ground(x,y,lane=6000):
    ay=abs(y)
    if ay<420:return 0
    near=smoothstep(420,900,ay)
    h=(noise(x,y)*.5+.5)*55*near
    h+=smoothstep(3600,7000,ay)*(500+700*(noise(x*.6,y*.6+300)*.5+.5))
    end=max(-x-1500,x-lane-1500)
    if end>0:h+=smoothstep(0,3000,end)*400*near
    return h


def make_terrain(collection,lane):
    xs=list(range(-4500,int(lane)+4501,200))
    # Include exact edges; unlike the old grid this keeps all 840 cm of battle lane flat.
    ys=sorted(set(list(range(-9500,9501,200))+[-420,0,420]))
    verts=[(x,y,ground(x,y,lane)) for y in ys for x in xs]
    faces=[]; slots=[]
    nx=len(xs)
    for row in range(len(ys)-1):
        for col in range(nx-1):
            i=row*nx+col
            faces.append((i,i+1,i+1+nx,i+nx))
            cy=(ys[row]+ys[row+1])*.5;cx=(xs[col]+xs[col+1])*.5
            zone=0 if abs(cy)<420 and -600<cx<lane+600 else 1 if abs(cy)<3600 else 2
            # The low-poly grid must not appear as a checkerboard in gameplay.
            slots.append(zone*2)
    obj=mesh_object('Env_BattlefieldGroundRoad',verts,faces,PALETTE['dirt'],collection)
    for key in ['dirt_light','meadow','meadow_light','hill','hill_light']:
        obj.data.materials.append(PALETTE[key])
    for poly,slot in zip(obj.data.polygons,slots):
        poly.material_index=slot
        poly.use_smooth=True
    uv=obj.data.uv_layers.new(name='UVMap')
    for poly in obj.data.polygons:
        for li in poly.loop_indices:
            v=obj.data.vertices[obj.data.loops[li].vertex_index].co
            uv.data[li].uv=(v.x/1000,v.y/1000)
    return obj


def instance(asset,x,y,scale=1,yaw=0,collection=None,lane=6000):
    src=MOTHERS[asset]
    ob=bpy.data.objects.new(asset+'_instance',src.data)
    collection.objects.link(ob)
    z=ground(x,y,lane)
    ob.location=(x,y,z)
    ob.rotation_euler.z=math.radians(yaw)
    ob.scale=(scale,scale,scale) if isinstance(scale,(float,int)) else scale
    INSTANCES.append({'id':f'env_{len(INSTANCES):04d}','asset_id':asset,'location_cm':[round(x,3),round(y,3),round(z,3)],'rotation_deg':[0,0,round(yaw,3)],'scale':[round(float(s),4) for s in ob.scale]})
    return ob


def build_scatter(collection,lane):
    def side(minimum,maximum):return RNG.choice([-1,1])*RNG.uniform(minimum,maximum)
    for asset,count,yrange,srange in [('Env_BoulderA',90,(720,3400),(.45,1.2)),('Env_BoulderB',50,(800,3400),(.45,1.0)),('Env_RockSlab',40,(650,3300),(.5,1)),('Env_Shrub',150,(850,3400),(.45,1.05)),('Env_GrassClump',500,(470,2600),(.4,.85))]:
        for _ in range(count):instance(asset,RNG.uniform(-2500,lane+2500),side(*yrange),RNG.uniform(*srange),RNG.uniform(0,360),collection,lane)
    for _ in range(260):
        asset='Env_Pine' if RNG.random()<.6 else 'Env_Broadleaf'
        instance(asset,RNG.uniform(-4000,lane+4000),side(3800,8000),RNG.uniform(.7,1.25),RNG.uniform(0,360),collection,lane)
    for _ in range(60):
        x=RNG.uniform(-4000,-1300) if RNG.random()<.5 else RNG.uniform(lane+1300,lane+4000)
        instance('Env_Pine',x,RNG.uniform(-3000,3000),RNG.uniform(.72,1.2),RNG.uniform(0,360),collection,lane)


def mountain(name,x,y,w,h,collection,seed):
    rnd=random.Random(seed)
    n=9; rings=[]
    for level,(r,z) in enumerate([(1,-100),(.65,h*.30),(.30,h*.68),(.025,h)]):
        rings.append([(x+math.cos(i*math.tau/n)*w*r*rnd.uniform(.83,1.18)+level*w*.025,y+math.sin(i*math.tau/n)*w*.66*r,z+rnd.uniform(-h*.06,h*.06)) for i in range(n)])
    obj=ring_solid(name,rings,PALETTE['mountain'])
    move_collection(obj,collection)
    obj.data.materials.append(PALETTE['snow'])
    for p in obj.data.polygons:
        if p.center.z>h*.64:p.material_index=1
    return obj


def camera(name,location,target,lens=43,ortho=None):
    data=bpy.data.cameras.new(name)
    ob=bpy.data.objects.new(name,data)
    bpy.context.scene.collection.objects.link(ob)
    ob.location=location
    ob.rotation_euler=(Vector(target)-ob.location).to_track_quat('-Z','Y').to_euler()
    data.clip_start=5;data.clip_end=100000
    if ortho:
        data.type='ORTHO';data.ortho_scale=ortho
    else:
        data.lens=lens;data.sensor_width=36
    return ob


def lighting():
    world=bpy.data.worlds.new('Warm_daylight')
    bpy.context.scene.world=world;world.use_nodes=True
    world.node_tree.nodes['Background'].inputs['Color'].default_value=(.50,.61,.73,1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value=.65
    d=bpy.data.lights.new('Sun','SUN');d.energy=2.8;d.angle=math.radians(12);d.color=(1,.93,.81)
    ob=bpy.data.objects.new('Sun',d);bpy.context.scene.collection.objects.link(ob)
    ob.rotation_euler=(math.radians(30),math.radians(-22),math.radians(-30))
    return ob


def render(path,camera_obj,res=(1600,900)):
    scene=bpy.context.scene;scene.camera=camera_obj
    scene.render.resolution_x=res[0];scene.render.resolution_y=res[1]
    scene.render.resolution_percentage=100
    scene.render.filepath=str(path)
    bpy.ops.render.render(write_still=True)


def export_asset(obj,path):
    bpy.ops.object.select_all(action='DESELECT')
    obj.hide_set(False);obj.hide_render=False;obj.select_set(True)
    bpy.context.view_layer.objects.active=obj
    bpy.ops.export_scene.fbx(filepath=str(path.with_suffix('.fbx')),use_selection=True,object_types={'MESH'},apply_unit_scale=True,apply_scale_options='FBX_SCALE_UNITS',bake_space_transform=False,axis_forward='X',axis_up='Z',mesh_smooth_type='FACE',use_mesh_modifiers=True,add_leaf_bones=False,bake_anim=False,path_mode='AUTO',use_custom_props=True)
    bpy.ops.export_scene.gltf(filepath=str(path.with_suffix('.glb')),export_format='GLB',use_selection=True,export_apply=True,export_yup=True)


def stats(obj):
    obj.data.calc_loop_triangles()
    dimensions=list(obj.dimensions)
    uv_areas=[]
    if obj.data.uv_layers:
        uv=obj.data.uv_layers.active.data
        for triangle in obj.data.loop_triangles:
            a,b,c=[uv[i].uv for i in triangle.loops]
            uv_areas.append(abs((b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x))*.5)
    return {'vertices':len(obj.data.vertices),'triangles':len(obj.data.loop_triangles),'materials':len(obj.data.materials),'dimensions_cm':[round(x,3) for x in dimensions],'uv_layers':len(obj.data.uv_layers),'origin_cm':[round(x,3) for x in obj.location], 'minimum_z_cm':round(min(v.co.z for v in obj.data.vertices),4),'uv_zero_area_triangles':sum(a<1e-10 for a in uv_areas),'uv_near_zero_area_triangles':sum(a<1e-7 for a in uv_areas),'uv_min_triangle_area':min(uv_areas) if uv_areas else None}


def main():
    args=argparse.ArgumentParser()
    args.add_argument('--version',default='v01')
    args.add_argument('--no-render',action='store_true')
    args.add_argument('--render-samples',type=int,default=48)
    args.add_argument('--turnaround-size',type=int,default=1024)
    opts=args.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    if not opts.version.replace('_','').isalnum():raise ValueError('Use a simple version folder name')
    out=ROOT/'RawAssets/Art/Tripo_v01/environment'/opts.version
    for sub in ['meshes','renders','turnarounds']:(out/sub).mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene=bpy.context.scene
    scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=.01
    scene.unit_settings.length_unit='CENTIMETERS'
    scene.render.engine='CYCLES';scene.cycles.samples=opts.render_samples
    scene.cycles.use_denoising=True
    render_device='CPU'
    try:
        prefs=bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type='HIP'
        prefs.get_devices()
        gpu=[d for d in prefs.devices if d.type=='HIP']
        if gpu:
            for d in prefs.devices:d.use=d.type=='HIP'
            scene.cycles.device='GPU'
            render_device=', '.join(d.name for d in gpu)
    except Exception as exc:
        print('HIP unavailable; using CPU:',exc)
    bpy.context.preferences.filepaths.save_version=0
    scene.render.image_settings.file_format='PNG'
    scene.render.film_transparent=False
    scene.view_settings.view_transform='AgX'
    scene.view_settings.look='AgX - Medium High Contrast'
    scene.view_settings.exposure=.5
    for name,color in {
        'stone':(.25,.252,.235),'stone_light':(.32,.32,.285),'bark':(.17,.09,.038),
        'leaf_dark':(.075,.12,.035),'leaf':(.15,.20,.055),'leaf_light':(.205,.255,.075),
        'pine_dark':(.025,.07,.04),'pine':(.04,.115,.063),'pine_light':(.067,.15,.077),
        'grass':(.205,.245,.065),'dirt':(.30,.205,.115),'dirt_light':(.33,.228,.13),
        'meadow':(.255,.28,.105),'meadow_light':(.28,.305,.12),'hill':(.165,.195,.08),
        'hill_light':(.19,.217,.092),'mountain':(.25,.30,.33),'snow':(.65,.72,.72)
    }.items():PALETTE[name]=material('M_CW_'+name,color)
    mother_collection=bpy.data.collections.new('Reusable_mothers');scene.collection.children.link(mother_collection)
    builders=[boulder_a,boulder_b,slab,shrub,pine,broadleaf,grass]
    report={};assets=[]
    catalog=json.loads((ROOT/'RawAssets/Art/Tripo_v01/catalog.json').read_text(encoding='utf-8'))
    expected={a['id'] for a in catalog['support'] if a['kind']=='environment'}
    for builder in builders:
        obj=builder();move_collection(obj,mother_collection)
        MOTHERS[obj.name]=obj
        obj['asset_id']=obj.name;obj['source']='DCC procedural initial pass';obj['production_approved']=False
        report[obj.name]=stats(obj)
        path=out/'meshes'/obj.name
        export_asset(obj,path)
        assets.append({'id':obj.name,'role':'environment_mother','file':str(path.with_suffix('.fbx').relative_to(ROOT)).replace('\\','/'),'glb':str(path.with_suffix('.glb').relative_to(ROOT)).replace('\\','/'),'type':'static_mesh','expected_dimensions_cm':report[obj.name]['dimensions_cm'],'import_materials':True,'combine_meshes':True,'source':'blender_dcc_v01','production_approved':False})
        obj.hide_render=True;obj.hide_set(True)
    assert set(MOTHERS)==expected,(set(MOTHERS),expected)
    rules=json.loads((ROOT/'Content/Data/Rules.json').read_text(encoding='utf-8-sig'))
    def find_lane(value):
        if isinstance(value,dict):
            if 'LaneLength' in value:return float(value['LaneLength'])
            for item in value.values():
                r=find_lane(item)
                if r:return r
        return None
    lane=find_lane(rules) or 6000
    terrain_collection=bpy.data.collections.new('Battlefield_ground');scene.collection.children.link(terrain_collection)
    scatter_collection=bpy.data.collections.new('Battlefield_instances');scene.collection.children.link(scatter_collection)
    backdrop_collection=bpy.data.collections.new('Distant_ridges');scene.collection.children.link(backdrop_collection)
    terrain=make_terrain(terrain_collection,lane);build_scatter(scatter_collection,lane)
    ridges=[]
    for side in [-1,1]:
        for i in range(13):
            ridges.append(mountain(f'Ridge_{side}_{i}',-6500+i*(lane+13000)/12,side*RNG.uniform(11200,13500),RNG.uniform(1600,2700),RNG.uniform(2400,3900),backdrop_collection,i+100*(side+1)))
    ridges_obj=joined('Env_DistantRidges',ridges,normalize_bottom=False)
    preview_instances=[]
    for obj in [terrain,ridges_obj]:
        path=out/'meshes'/obj.name
        export_asset(obj,path)
        s=stats(obj)
        assets.append({'id':obj.name,'role':'preview_only','file':str(path.with_suffix('.fbx').relative_to(ROOT)).replace('\\','/'),'glb':str(path.with_suffix('.glb').relative_to(ROOT)).replace('\\','/'),'type':'static_mesh','expected_dimensions_cm':s['dimensions_cm'],'import_materials':True,'combine_meshes':True,'source':'blender_dcc_v01','production_approved':False})
        preview_instances.append({'id':obj.name+'_preview','asset_id':obj.name,'location_cm':[0,0,0],'rotation_deg':[0,0,0],'scale':[1,1,1]})
    sun=lighting()
    distance=2300;pitch=math.radians(20)
    game0=camera('Game_camera_team0',(lane*.5,math.cos(pitch)*distance,110+math.sin(pitch)*distance),(lane*.5,0,110),lens=36/(2*math.tan(math.radians(45/2))))
    game1=camera('Game_camera_team1',(lane*.5,-math.cos(pitch)*distance,110+math.sin(pitch)*distance),(lane*.5,0,110),lens=game0.data.lens)
    overview=camera('Layout_overview',(lane*.5+3500,15500,12500),(lane*.5,0,600),ortho=19000)
    scene.camera=game0
    write_json(out/'manifest.json',{'schema_version':1,'batch_id':'environment_'+opts.version,'status':'dcc_initial_meshes_pending_ue_acceptance','units':'cm','assets':assets})
    write_json(out/'manifest_pine_fix.json',{'schema_version':1,'batch_id':'environment_'+opts.version+'_pine_fix','status':'dcc_uv_fix_pending_ue_tangent_validation','units':'cm','assets':[a for a in assets if a['id']=='Env_Pine']})
    clearance=[]
    for item in INSTANCES:
        x,y,z=item['location_cm'];half_y=report[item['asset_id']]['dimensions_cm'][1]*max(item['scale'])/2
        if -600<x<lane+600 and abs(y)-half_y<420:clearance.append(item['id'])
    write_json(out/'layout.json',{'schema_version':1,'units':'cm','coordinate_system':'Unreal Z-up +X-forward +Y-right','rotation_order':'[roll,pitch,yaw] degrees','lane_length_cm':lane,'flat_lane_half_width_cm':420,'terrain_source':'Source/CivWar/View/CWBattlefield.cpp::GroundHeight','terrain_generated_for_preview':True,'base_envelopes':[{'team':0,'location_cm':[0,0,0],'half_width_cm':300},{'team':1,'location_cm':[lane,0,0],'half_width_cm':300}],'instances':INSTANCES,'preview_instances':preview_instances})
    checks={'catalog_coverage':set(MOTHERS)==expected,'all_meshes_have_uvs':all(v['uv_layers']>0 for v in report.values()),'all_meshes_nonzero_uv_triangles':all(v['uv_zero_area_triangles']==0 for v in report.values()),'all_meshes_no_near_zero_uv_triangles':all(v['uv_near_zero_area_triangles']==0 for v in report.values()),'all_origins_at_ground':all(abs(v['minimum_z_cm'])<.01 for v in report.values()),'battle_lane_clear':not clearance,'lane_clearance_failures':clearance}
    write_json(out/'inspection.json',{'schema_version':1,'blender_version':bpy.app.version_string,'render_device':render_device,'source':'Generated in Blender, not Tripo','status':'dcc_initial_pass','production_approved':False,'mesh_stats':report,'instance_count':len(INSTANCES),'turnaround_image_size_px':[opts.turnaround_size,opts.turnaround_size],'turnaround_scale_policy':'Three orthographic views share max(asset dimensions) * 1.38 framing; no independent view normalization','checks':checks,'pending':['Unreal FBX import axis and dimensions','Two team game-camera obstruction review with characters and bases','Runtime instancing and GPU performance','Base / turret platform geometry is a separate Tripo architectural task']})
    bpy.ops.wm.save_as_mainfile(filepath=str(out/('CivWar_Battlefield_'+opts.version+'.blend')))
    if not opts.no_render:
        render(out/'renders'/'battlefield_game_team0.png',game0)
        sun.rotation_euler.z+=math.pi
        render(out/'renders'/'battlefield_game_team1.png',game1)
        sun.rotation_euler.z-=math.pi
        render(out/'renders'/'battlefield_overview.png',overview,(1800,1100))
        # Individually framed, square asset views; fixed object and camera rotations.
        terrain_collection.hide_render=True;scatter_collection.hide_render=True;backdrop_collection.hide_render=True
        scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.68,.69,.65,1)
        scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.8
        for aid,obj in MOTHERS.items():
            obj.hide_render=False;obj.hide_set(False)
            size=max(obj.dimensions);center=Vector((0,0,obj.dimensions.z*.48))
            for label,offset in [('front',(size*2.3,0,size*.35)),('right',(0,size*2.3,size*.35)),('back',(-size*2.3,0,size*.35))]:
                cam=camera(aid+'_'+label,center+Vector(offset),center,ortho=size*1.38)
                render(out/'turnarounds'/f'{aid}_{label}.png',cam,(opts.turnaround_size,opts.turnaround_size))
            obj.hide_render=True;obj.hide_set(True)
        terrain_collection.hide_render=False;scatter_collection.hide_render=False;backdrop_collection.hide_render=False
        image_checks=[]
        for aid in MOTHERS:
            for view in ['front','right','back']:
                preview=bpy.data.images.load(str(out/'turnarounds'/f'{aid}_{view}.png'),check_existing=False)
                size=list(preview.size)
                image_checks.append({'asset':aid,'view':view,'size':size,'valid':size==[opts.turnaround_size,opts.turnaround_size]})
                bpy.data.images.remove(preview)
        write_json(out/'image_checks.json',{'all_equal_expected_size':all(i['valid'] for i in image_checks),'all_equal_1024':all(i['size']==[1024,1024] for i in image_checks),'count':len(image_checks),'images':image_checks})
        inspection=json.loads((out/'inspection.json').read_text(encoding='utf-8'))
        inspection['rendered_turnaround_count']=len(image_checks)
        inspection['checks']['all_turnaround_images_expected_size']=all(i['valid'] for i in image_checks)
        inspection['checks']['all_turnaround_images_1024']=all(i['size']==[1024,1024] for i in image_checks)
        write_json(out/'inspection.json',inspection)
    scene.camera=game0
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.50,.61,.73,1)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.65
    bpy.ops.wm.save_as_mainfile(filepath=str(out/('CivWar_Battlefield_'+opts.version+'.blend')))
    print('CIVWAR_ENVIRONMENT_COMPLETE '+str(out))
    if not all(v for k,v in checks.items() if k!='lane_clearance_failures'):raise RuntimeError('Environment inspection requires correction; see inspection.json')


if __name__=='__main__':main()
