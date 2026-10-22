"""Build the 15 independent CivWar weapon prototypes with explicit assembly anchors.

Run: blender --background --python Tools/Blender/build_weapons.py -- --all
All source dimensions are metres; +X is aim/forward, +Y is right, +Z is up.
These are original stylized game props, not functional weapon specifications.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "RawAssets/Art/Tripo_v01/weapons"
RENDER_DEVICE="CPU"
SKIP_EXISTING=False
COLORS = {
    "wood": (0.24, 0.105, 0.045), "wood_light": (0.40, 0.235, 0.10),
    "leather": (0.11, 0.055, 0.029), "hide": (0.53, 0.36, 0.18),
    "stone": (0.34, 0.36, 0.35), "stone_light": (0.46, 0.48, 0.46),
    "steel": (0.38, 0.44, 0.46), "iron": (0.075, 0.095, 0.105),
    "graphite": (0.055, 0.070, 0.080), "cobalt": (0.055, 0.16, 0.34),
    "olive": (0.22, 0.28, 0.13), "ivory": (0.73, 0.73, 0.63),
    "cyan": (0.27, 0.68, 0.70), "shield": (0.14, 0.22, 0.27),
}
METALLIC = {"steel": 0.65, "iron": 0.48, "graphite": 0.32}


def material(name):
    key = "CW_" + name
    mat = bpy.data.materials.get(key) or bpy.data.materials.new(key)
    mat.diffuse_color = (*COLORS[name], 1)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*COLORS[name], 1)
    bsdf.inputs["Metallic"].default_value = METALLIC.get(name, 0)
    bsdf.inputs["Roughness"].default_value = 0.66 if name != "steel" else 0.45
    return mat


def bevel(obj, amount=0.005, segments=1):
    if amount:
        mod = obj.modifiers.new("Edge_readability", "BEVEL")
        mod.width, mod.segments = min(amount,min(d for d in obj.dimensions if d>0)*.40), segments
        mod.affect = "EDGES"
    return obj


def finish(obj, name, mat, parent=None):
    name=name.replace("+", "P").replace("-", "N")
    candidate=name
    index=2
    while bpy.data.objects.get(candidate) and bpy.data.objects.get(candidate)!=obj:
        candidate=f"{name}_{index:02}"
        index+=1
    obj.name = candidate
    if mat:
        obj.data.materials.append(material(mat))
    if parent:
        bpy.context.view_layer.update()
        world = obj.matrix_world.copy()
        obj.parent = parent
        obj.matrix_world = world
    obj["civwar_part"] = True
    return obj


def cube(name, loc, size, mat, parent=None, edge=0.004):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return bevel(finish(obj, name, mat, parent), edge)


def rod(name, a, b, radius, mat, parent=None, radius2=None, vertices=12):
    a, b = Vector(a), Vector(b)
    bpy.ops.mesh.primitive_cone_add(vertices=vertices, radius1=radius,
                                  radius2=radius if radius2 is None else radius2,
                                  depth=(b-a).length, location=(a+b)*0.5)
    obj = bpy.context.object
    obj.rotation_euler = (b-a).to_track_quat("Z", "Y").to_euler()
    return finish(obj, name, mat, parent)


def ico(name, loc, scale, mat, parent=None, subdivisions=1):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subdivisions, radius=1, location=loc)
    obj = bpy.context.object
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return finish(obj, name, mat, parent)


def poly_xz(name, outline, thick, mat, parent=None, y=0, edge=0.003):
    n = len(outline)
    vertices = [(x, y-thick/2, z) for x, z in outline] + [(x, y+thick/2, z) for x, z in outline]
    faces = [tuple(reversed(range(n))), tuple(range(n, n*2))]
    faces += [(i, (i+1) % n, (i+1) % n+n, i+n) for i in range(n)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return bevel(finish(obj, name, mat, parent), edge)


def tube(name, path, radius, mat, parent=None, target=None, sides=8):
    """A closed mesh cable, optionally with a matching topology deformation key."""
    def vertices_for(points):
        points = [Vector(p) for p in points]
        vertices = []
        for i, p in enumerate(points):
            tangent = points[min(i+1, len(points)-1)]-points[max(i-1, 0)]
            tangent.normalize()
            ref = Vector((0, 1, 0)) if abs(tangent.y) < .9 else Vector((0, 0, 1))
            u = tangent.cross(ref).normalized()
            v = tangent.cross(u).normalized()
            vertices.extend(p + radius*(math.cos(j*math.tau/sides)*u + math.sin(j*math.tau/sides)*v) for j in range(sides))
        return vertices
    verts = vertices_for(path)
    faces = [tuple(reversed(range(sides)))]
    for i in range(len(path)-1):
        for j in range(sides):
            a = i*sides+j
            b = i*sides+(j+1) % sides
            faces.append((a,b,b+sides,a+sides))
    faces.append(tuple((len(path)-1)*sides+j for j in range(sides)))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    finish(obj, name, mat, parent)
    bm=bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    if target:
        obj.shape_key_add(name="Basis")
        key = obj.shape_key_add(name="Draw")
        for vertex, co in zip(key.data, vertices_for(target)):
            vertex.co = co
        key.value=0
        obj.active_shape_key_index=0
        obj.show_only_shape_key=False
        obj["control"] = "shape_keys.Draw: 0 rest / 1 drawn; drive with matching limb/pouch controls"
    return obj


def ring(name, loc, radius, tube_radius, mat, normal=(0,0,1), parent=None):
    bpy.ops.mesh.primitive_torus_add(major_radius=radius, minor_radius=tube_radius,
                                   major_segments=24, minor_segments=6, location=loc)
    obj = bpy.context.object
    obj.rotation_euler = Vector(normal).to_track_quat("Z", "Y").to_euler()
    return finish(obj, name, mat, parent)


def anchor(name, loc=(0,0,0), parent=None, role="assembly", rot=(0,0,0)):
    name=name.replace("+", "P").replace("-", "N")
    obj = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(obj)
    obj.empty_display_type = "ARROWS"
    obj.empty_display_size = .055
    obj.location = loc
    obj.rotation_euler = rot
    if parent:
        bpy.context.view_layer.update()
        world = obj.matrix_world.copy()
        obj.parent = parent
        obj.matrix_world = world
    obj["civwar_anchor"] = True
    obj["role"] = role
    return obj


def wrap_z(prefix, z, radius=.025, count=3, x=0):
    for i in range(count):
        rod(f"{prefix}_{i:02}", (x,0,z+i*.018), (x,0,z+i*.018+.015), radius, "hide", current_root)


def blade(name, base, tip, width, thick, mat="steel", parent=None):
    bx, by, bz = base
    tx, ty, tz = tip
    # This blade is upright in the XZ plane. A pronounced central ridge catches light.
    vertices = [(bx-width/2,by,bz),(bx,by-thick/2,bz),(bx+width/2,by,bz),(bx,by+thick/2,bz),tip]
    faces = [(0,3,2,1),(0,1,4),(1,2,4),(2,3,4),(3,0,4)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return finish(obj, name, mat, parent)


def stone_axe():
    rod("shaft", (0,0,-.19), (-.018,0,.55), .023, "wood", current_root, .028)
    # Broad wedge edge at +X, deliberately faceted rather than photorealistic chips.
    poly_xz("stone_head", [(-.105,.43),(-.08,.59),(.04,.64),(.245,.59),(.267,.39),(.09,.35)], .10, "stone", current_root, edge=.014)
    poly_xz("stone_edge_facet", [(.19,.405),(.207,.585),(.245,.59),(.267,.39)], .066, "stone_light", current_root, edge=.001)
    for z in (.45,.53):
        cube("hide_head_lashing", (0,0,z), (.088,.125,.035), "hide", current_root, .008)
    wrap_z("grip_wrap", -.07, .025, 6)
    anchor("grip_r", parent=current_root, role="right palm centre; shaft along local Z; diameter 5 cm prototype")
    anchor("blade_base", (.12,0,.39), current_root)
    anchor("blade_tip", (.263,0,.49), current_root, "edge contact / VFX only")
    return "one_hand_axe", ["Final handle diameter and thumb closure await the approved body mesh."]


def sling():
    anchor("grip_r", parent=current_root, role="hold both cord ends; release one end at confirmed release")
    pouch = anchor("sling_pouch", (.025,0,-.52), current_root, "movable pouch pivot; coordinate with both cord Draw keys")
    ico("leather_pouch", (.025,0,-.52), (.09,.045,.05), "leather", pouch, 2)
    ico("loaded_stone", (.025,0,-.492), (.045,.038,.042), "stone", pouch, 1)
    for side in (-1,1):
        path, target = [], []
        for i in range(11):
            t=i/10
            path.append((side*(.035*math.sin(t*math.pi)+.075*t)+.025*t, side*.019*(1-t), -.52*t))
            target.append(((.58+side*.075)*t,side*.019*(1-t),.05*t+side*.018*math.sin(t*math.pi)))
        tube(f"cord_{side:+}", path, .008, "hide", current_root, target)
    anchor("release_point", (.025,0,-.492), pouch, "stone launch pivot; animate with pouch")
    return "flexible_sling", ["Draw morphs are authored deformation controls, not a finished sling attack.", "Move sling_pouch from (0.025,0,-0.52) to (0.58,0,0.05) while setting both cord Draw keys to 1.", "Stone visibility and cord release must use the server-confirmed attack event."]


def stone_spear():
    rod("shaft", (-.62,0,0), (.94,0,0), .021, "wood", current_root, .016)
    # Broad ridged spear point, mounted horizontally along +X.
    obj=blade("stone_tip", (0,0,0), (0,0,.27), .095,.046,"stone",current_root)
    obj.location=(.90,0,0)
    obj.rotation_euler[1]=math.pi/2
    for x in (.87,.92):
        rod("hide_bind", (x-.013,0,0),(x+.013,0,0), .026,"hide",current_root)
    for x in (-.05,0,.05):
        rod("grip_wrap", (x-.02,0,0),(x+.02,0,0), .023,"leather",current_root)
    anchor("grip_r", parent=current_root, role="right palm; shaft along +X")
    anchor("blade_base", (.92,0,0),current_root)
    anchor("blade_tip", (1.17,0,0),current_root)
    return "mounted_spear", ["Adjust length only after saddle and combat range assembly review."]


def sword():
    rod("leather_grip", (0,0,-.10),(0,0,.09),.022,"leather",current_root)
    cube("crossguard", (0,0,.10),(.245,.06,.04),"iron",current_root,.012)
    ico("pommel", (0,0,-.12),(.036,.026,.033),"steel",current_root,1)
    blade("steel_blade", (0,0,.12),(0,0,.72),.105,.033,"steel",current_root)
    anchor("grip_r",parent=current_root)
    anchor("blade_base",(0,0,.15),current_root)
    anchor("blade_tip",(0,0,.72),current_root)
    return "one_hand_sword", []


def round_shield():
    rod("wood_disk", (.005,0,0),(.045,0,0),.31,"wood_light",current_root,vertices=24)
    rod("painted_face", (.045,0,0),(.057,0,0),.29,"cobalt",current_root,vertices=24)
    ring("iron_rim",(.035,0,0),.302,.026,"iron",(1,0,0),current_root)
    ico("steel_boss",(.08,0,0),(.05,.105,.105),"steel",current_root,2)
    # Discrete rear mounts leave real volume for hand and forearm.
    for z in (-.10,.10):
        cube("grip_mount",(-.035,-.09,z),(.085,.04,.035),"iron",current_root,.006)
    rod("shield_rear_grip",(-.075,-.09,-.10),(-.075,-.09,.10),.019,"leather",current_root)
    tube("forearm_cuff",[(0,.045,-.11),(-.09,.075,-.11),(-.13,.075,0),(-.09,.075,.11),(0,.045,.11)],.021,"leather",current_root)
    anchor("shield_l",(-.083,.07,0),current_root,"left forearm attachment; shield face +X")
    anchor("shield_grip",(-.075,-.09,0),current_root,"left palm centre; visible rear handle")
    return "left_arm_shield", ["Separate infantry and mounted attachment offsets must be measured on their bodies."]


def crossbow():
    poly_xz("wood_stock",[(-.35,-.025),(-.35,.055),(.46,.055),(.49,.012),(.10,-.025),(-.025,-.085),(-.09,-.08),(-.11,-.025)],.075,"wood",current_root,edge=.008)
    cube("cobalt_grip",(-.045,0,-.045),(.055,.086,.08),"cobalt",current_root,.008)
    for side in (-1,1):
        limb=anchor(f"limb_pivot_{side:+}",(.33,side*.045,.04),current_root,"small elastic limb rotation; synchronize string Draw")
        tube(f"limb_{side:+}",[(.33,side*.04,.04),(.32,side*.16,.045),(.25,side*.29,.05),(.19,side*.35,.05)],.024,"wood_light",limb)
    tube("bow_string",[(.19,-.35,.05),(.055,0,.05),(.19,.35,.05)],.005,"hide",current_root,[(.19,-.35,.05),(-.18,0,.05),(.19,.35,.05)])
    bolt=anchor("bolt_socket",(.08,0,.073),current_root,"bolt actor attach; hide at release")
    rod("loaded_bolt",(-.16,0,.073),(.48,0,.073),.008,"wood_light",bolt,vertices=8)
    rod("bolt_tip",(.46,0,.073),(.52,0,.073),.019,"iron",bolt,0,8)
    anchor("grip_r",(-.045,0,-.045),current_root)
    anchor("grip_l",(.19,0,-.045),current_root,"left supporting palm; release IK for reload")
    anchor("muzzle",(.535,0,.073),current_root,"+X forward; projectile source")
    anchor("string_center",(.055,0,.05),current_root,"rest centre; drawn centre (-.18,0,.05)")
    return "two_hand_crossbow", ["String Draw and limb pivots are exportable controls; matching hand reload animation remains to be authored."]


def lance():
    rod("lance_shaft",(-.50,0,0),(1.40,0,0),.047,"wood_light",current_root,.016)
    rod("lance_tip",(1.36,0,0),(1.64,0,0),.040,"steel",current_root,0)
    rod("grip",(-.10,0,0),(.08,0,0),.041,"cobalt",current_root)
    rod("hand_guard",(.10,0,0),(.17,0,0),.105,"iron",current_root,.055)
    anchor("grip_r",parent=current_root)
    anchor("blade_base",(1.36,0,0),current_root)
    anchor("blade_tip",(1.64,0,0),current_root)
    return "mounted_lance", ["Prototype total length 2.14 m; shorten if gameplay range or horse-neck clearance fails."]


def shovel():
    rod("wood_handle",(0,0,-.13),(0,0,.38),.022,"wood",current_root)
    tube("D_grip",[(-.015,0,-.12),(-.075,0,-.19),(-.065,0,-.28),(.065,0,-.28),(.075,0,-.19),(.015,0,-.12)],.016,"iron",current_root)
    poly_xz("spade",[(-.11,.33),(.11,.33),(.14,.50),(.08,.57),(-.08,.57),(-.14,.50)],.035,"iron",current_root,edge=.012)
    cube("blade_spine",(0,-.018,.39),(.055,.025,.16),"steel",current_root,.005)
    anchor("grip_r",parent=current_root)
    anchor("blade_base",(0,0,.34),current_root)
    anchor("blade_tip",(0,0,.57),current_root)
    return "one_hand_spade", []


def rifle():
    poly_xz("wood_stock",[(-.40,-.08),(-.40,.07),(-.23,.065),(-.11,.025),(.015,.045),(.49,.045),(.49,-.018),(.12,-.036),(-.035,-.044),(-.13,-.018),(-.23,-.07)],.065,"wood",current_root,edge=.009)
    cube("butt_pad",(-.406,0,-.005),(.025,.078,.166),"iron",current_root,.006)
    cube("receiver",(.08,0,.065),(.27,.058,.05),"iron",current_root,.005)
    rod("barrel",(.17,0,.077),(.70,0,.077),.018,"iron",current_root,.015,12)
    rod("muzzle_ring",(.67,0,.077),(.72,0,.077),.023,"steel",current_root,vertices=12)
    rod("muzzle_dark_inset",(.7201,0,.077),(.721,0,.077),.012,"graphite",current_root,vertices=12)
    for x in (.06,.63):
        cube("sight",(x,0,.099),(.025,.018,.033),"iron",current_root,.002)
    for x in (.25,.46):
        cube("stock_band",(x,0,.025),(.025,.076,.075),"iron",current_root,.004)
    tube("trigger_guard",[(-.018,-.005,-.033),(.015,-.005,-.087),(.09,-.005,-.083),(.105,-.005,-.032)],.007,"iron",current_root)
    bolt=anchor("bolt_handle_pivot",(.11,.035,.065),current_root,"decorative bolt travel only; no ammunition mechanics added")
    rod("bolt_handle",(.11,.025,.065),(.11,.075,.045),.008,"steel",bolt,vertices=8)
    ico("bolt_knob",(.11,.078,.043),(.015,.015,.015),"iron",bolt,1)
    anchor("grip_r",(-.055,0,-.027),current_root,"right palm around stock wrist")
    anchor("grip_l",(.30,0,-.037),current_root,"left palm under fore-end; primary attachment remains right hand")
    anchor("stock_contact",(-.42,0,0),current_root,"right shoulder contact")
    anchor("muzzle",(.728,0,.077),current_root,"+X; outside visible muzzle")
    return "two_hand_rifle", ["Two-hand spacing is 35.5 cm before character fitting; shoulder contact is 36.5 cm behind right grip.", "No character hand pose, arm IK, or firing timing is claimed by this prop."]


def baton():
    rod("baton_body",(0,0,-.13),(0,0,.48),.025,"graphite",current_root,.022)
    ico("rounded_tip",(0,0,.48),(.022,.022,.022),"graphite",current_root,2)
    rod("grip",(0,0,-.10),(0,0,.08),.028,"leather",current_root)
    rod("grip_collar",(0,0,.08),(0,0,.105),.037,"iron",current_root)
    anchor("grip_r",parent=current_root)
    anchor("blade_base",(0,0,.12),current_root)
    anchor("blade_tip",(0,0,.50),current_root)
    return "one_hand_baton", []


def riot_shield():
    # Build in XZ first, rotate so the protective face points +X.
    shape=[(-.24,-.40),(.24,-.40),(.28,-.34),(.28,.35),(.22,.42),(-.22,.42),(-.28,.35),(-.28,-.34)]
    for name,scale,thick,mat,x in [("dark_rim",1,.045,"graphite",.015),("shield_plate",.92,.025,"shield",.045)]:
        obj=poly_xz(name,[(a*scale,b*scale) for a,b in shape],thick,mat,current_root,edge=.013)
        obj.rotation_euler[2]=math.pi/2
        obj.location.x=x
    cube("cobalt_band",(.065,0,.265),(.015,.49,.09),"cobalt",current_root,.004)
    for z in (-.10,.10):
        cube("handle_mount",(-.025,-.09,z),(.095,.04,.035),"iron",current_root,.006)
    rod("rear_handle",(-.075,-.09,-.10),(-.075,-.09,.10),.02,"leather",current_root)
    tube("forearm_cuff",[(0,.055,-.12),(-.10,.09,-.12),(-.135,.09,0),(-.10,.09,.12),(0,.055,.12)],.021,"leather",current_root)
    anchor("shield_l",(-.09,.09,0),current_root,"left forearm; opaque face points +X")
    anchor("shield_grip",(-.075,-.09,0),current_root)
    return "left_arm_shield", ["82 cm shield height is provisional until knee and floor clearance is checked."]


def rocket_launcher():
    rod("olive_tube",(-.40,0,.16),(.49,0,.16),.082,"olive",current_root,vertices=16)
    for x in (-.39,.46):
        rod("tube_collar",(x-.035,0,.16),(x+.035,0,.16),.098,"iron",current_root,vertices=16)
    for x in (-.426,.496):
        rod("dark_opening",(x,0,.16),(x+.001,0,.16),.075,"graphite",current_root,vertices=16)
    cube("primary_grip",(0,0,.02),(.05,.055,.16),"graphite",current_root,.009)
    cube("shoulder_pad",(-.24,0,.055),(.24,.14,.045),"graphite",current_root,.012)
    cube("fore_support",(.22,0,.075),(.17,.095,.045),"olive",current_root,.008)
    cube("sight_block",(.12,-.085,.23),(.07,.035,.055),"iron",current_root,.005)
    anchor("grip_r",(0,0,.015),current_root)
    anchor("grip_l",(.22,0,.042),current_root)
    anchor("shoulder_contact",(-.24,0,.03),current_root)
    anchor("muzzle",(.51,0,.16),current_root,"+X; game projectile source")
    anchor("rear_fx",(-.44,0,.16),current_root,"rear effect only; rotate local +X toward rear",rot=(0,0,math.pi))
    return "shoulder_launcher", ["Stylized closed internal mesh; no functional construction detail.","Helmet, face and backpack clearance require body assembly; rear FX must stay clear of body."]


def energy_blade():
    rod("graphite_grip",(0,0,-.12),(0,0,.10),.030,"graphite",current_root)
    cube("hilt",(0,0,.11),(.19,.07,.07),"ivory",current_root,.012)
    cube("cobalt_inset",(0,-.033,.02),(.025,.012,.10),"cobalt",current_root,.003)
    blade("energy_blade",(0,0,.16),(0,0,.77),.115,.032,"cyan",current_root)
    blade("inner_blade",(0,-.017,.17),(0,-.008,.73),.035,.010,"ivory",current_root)
    anchor("grip_r",parent=current_root)
    anchor("blade_base",(0,0,.17),current_root)
    anchor("blade_tip",(0,0,.77),current_root)
    return "one_hand_energy_blade", ["Solid cyan blade is deliberately unlit; final emission and trails belong to UE material/VFX."]


def laser_rifle():
    cube("main_casing",(.15,0,.085),(.48,.115,.14),"ivory",current_root,.025)
    cube("upper_spine",(.18,0,.17),(.44,.075,.035),"graphite",current_root,.008)
    poly_xz("stock",[(-.39,-.015),(-.39,.13),(-.10,.13),(-.08,.05),(-.22,.04),(-.27,-.015)],.085,"graphite",current_root,edge=.012)
    cube("stock_pad",(-.40,0,.05),(.035,.10,.17),"ivory",current_root,.009)
    grip=cube("pistol_grip",(-.025,0,-.055),(.065,.065,.17),"graphite",current_root,.01)
    grip.rotation_euler[1]=.20
    cube("grip_panel",(-.025,-.035,-.05),(.04,.01,.08),"cobalt",current_root,.003)
    cube("foregrip",(.26,0,-.015),(.16,.095,.045),"graphite",current_root,.009)
    cube("barrel_sleeve",(.47,0,.085),(.22,.09,.095),"graphite",current_root,.01)
    cube("emitter_insert",(.583,0,.085),(.01,.055,.055),"cyan",current_root,.003)
    for side in (-1,1):
        cube("cobalt_side_panel",(.20,side*.059,.085),(.15,.012,.075),"cobalt",current_root,.006)
    energy=anchor("energy_cell_socket",(.13,0,-.035),current_root,"optional visual energy module; no reload gameplay")
    cube("energy_cell",(.13,0,-.055),(.09,.075,.095),"ivory",energy,.008)
    anchor("grip_r",(-.025,0,-.055),current_root)
    anchor("grip_l",(.26,0,-.042),current_root)
    anchor("stock_contact",(-.421,0,.05),current_root)
    anchor("muzzle",(.599,0,.085),current_root,"+X; one pulse per confirmed attack")
    return "two_hand_energy_rifle", ["No beam geometry or light halo is baked into the prop."]


def bow():
    rod("leather_grip",(0,0,-.085),(0,0,.085),.025,"leather",current_root)
    for side in (-1,1):
        pivot=anchor(f"limb_pivot_{side:+}",(0,0,side*.08),current_root,"limb bend pivot; coordinate with string Draw")
        tube(f"wood_limb_{side:+}",[(0,0,side*.07),(.055,0,side*.24),(.07,0,side*.40),(-.035,0,side*.56)],.022,"wood_light",pivot)
    tube("bow_string",[(-.035,0,-.56),(-.035,0,0),(-.035,0,.56)],.005,"hide",current_root,[(-.035,0,-.56),(-.33,0,0),(-.035,0,.56)])
    anchor("grip_l",parent=current_root,role="bow is left-hand primary attachment; right hand follows string")
    anchor("string_center",(-.035,0,0),current_root,"drawn centre (-.33,0,0); right-hand target")
    anchor("arrow_socket",(0,-.027,.04),current_root)
    anchor("muzzle",(.05,-.027,.04),current_root,"+X; arrow leaves toward forward")
    return "left_hand_bow", ["String Draw morph and separate limb pivots are controls; proper elastic limb bending and right hand draw remain assembly work."]


BUILDERS = {
    "Weapon_StoneAxe":stone_axe,"Weapon_Sling":sling,"Weapon_StoneSpear":stone_spear,
    "Weapon_Sword":sword,"Weapon_RoundShield":round_shield,"Weapon_Crossbow":crossbow,
    "Weapon_Lance":lance,"Weapon_Shovel":shovel,"Weapon_Rifle":rifle,
    "Weapon_Baton":baton,"Weapon_RiotShield":riot_shield,"Weapon_RocketLauncher":rocket_launcher,
    "Weapon_EnergyBlade":energy_blade,"Weapon_LaserRifle":laser_rifle,"Weapon_Bow":bow,
}


def mesh_bounds(objects):
    points=[obj.matrix_world@Vector(c) for obj in objects if obj.type=="MESH" for c in obj.bound_box]
    low=Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high=Vector(tuple(max(p[i] for p in points) for i in range(3)))
    return low,high


def add_lighting_and_camera(objects):
    low,high=mesh_bounds(objects)
    centre=(low+high)/2
    span=max(high-low)
    scene=bpy.context.scene
    scene.render.engine="CYCLES"
    scene.cycles.samples=12
    scene.cycles.device="CPU"
    scene.cycles.use_denoising=True
    scene.render.threads_mode="FIXED"
    scene.render.threads=4
    scene.render.resolution_x=1200
    scene.render.resolution_y=1200
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format="PNG"
    scene.render.film_transparent=False
    scene.world.color=(.22,.22,.22)
    scene.world.use_nodes=True
    bg=scene.world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value=(.75,.78,.79,1)
    bg.inputs["Strength"].default_value=.4
    scene.view_settings.view_transform="AgX"
    floor=cube("DISPLAY_floor",(centre.x,centre.y,low.z-.035),(span*200,span*200,.05),"ivory",edge=0)
    floor["civwar_part"]=False
    floor.data.materials.clear()
    floor_mat=bpy.data.materials.new("DISPLAY_floor_matte")
    floor_mat.diffuse_color=(.75,.77,.76,1)
    floor.data.materials.append(floor_mat)
    for name,offset,energy,size in [("key",(-2,-3,5),550,4),("fill",(3,2,3),350,3),("rim",(-2,3,4),450,3)]:
        bpy.ops.object.light_add(type="AREA",location=centre+Vector(offset)*max(span,1))
        light=bpy.context.object
        light.name="DISPLAY_"+name
        light.data.energy=energy*max(span,1)**2
        light.data.shape="DISK"
        light.data.size=size*max(span,1)
        light.rotation_euler=(centre-light.location).to_track_quat("-Z","Y").to_euler()
    bpy.ops.object.camera_add(location=centre+Vector((2.4,-3.2,1.7))*max(span,1))
    cam=bpy.context.object
    cam.name="DISPLAY_camera"
    cam.rotation_euler=(centre-cam.location).to_track_quat("-Z","Y").to_euler()
    cam.data.type="ORTHO"
    rotation=cam.rotation_euler.to_quaternion()
    right=rotation@Vector((1,0,0))
    up=rotation@Vector((0,1,0))
    corners=[o.matrix_world@Vector(c) for o in objects if o.type=="MESH" for c in o.bound_box]
    projected_width=max(p.dot(right) for p in corners)-min(p.dot(right) for p in corners)
    projected_height=max(p.dot(up) for p in corners)-min(p.dot(up) for p in corners)
    cam.data.ortho_scale=max(projected_width,projected_height)*1.22
    scene.camera=cam
    return cam,centre,span


def select_asset(objects):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active=current_root


def export_and_report(asset_id, family, notes, objects, out, render=True, turnarounds=False):
    bpy.context.view_layer.update()
    low,high=mesh_bounds(objects)
    links={}
    for obj in objects:
        if obj.get("civwar_anchor"):
            links[obj.name]={"position_m":[round(float(v),6) for v in obj.matrix_world.translation],
                             "rotation_euler_deg":[round(math.degrees(v),4) for v in obj.matrix_world.to_euler()],
                             "parent":obj.parent.name if obj.parent else None,"role":obj.get("role","assembly")}
    controls=[{"object":o.name,"keys":[k.name for k in o.data.shape_keys.key_blocks if k.name!="Basis"]}
              for o in objects if o.type=="MESH" and o.data.shape_keys]
    notes=list(notes)+["Named empties are assembly metadata; they are not automatically authored UE StaticMesh sockets."]
    if controls:
        notes.append("Flexible controls are shape keys. UE still needs a skeletal/morph or procedural component setup before these controls play in game.")
    select_asset(objects)
    glb=out/(asset_id+".glb")
    bpy.ops.export_scene.gltf(filepath=str(glb),export_format="GLB",use_selection=True,
                              export_extras=True,export_animations=False,export_apply=False)
    bpy.ops.export_scene.fbx(filepath=str(out/(asset_id+".fbx")),use_selection=True,
                             object_types={"EMPTY","MESH"},apply_unit_scale=True,
                             axis_forward="X",axis_up="Z",use_mesh_modifiers=False,
                             bake_anim=False,add_leaf_bones=False,use_custom_props=True,
                             path_mode="AUTO")
    contract={"asset_id":asset_id,"revision":"dcc_v01","status":"generated_dcc_prototype_not_character_validated",
              "family":family,"units":"metres","source_basis":{"forward":"+X","right":"+Y","up":"+Z"},
              "ue_units":"centimetres; preserve import unit conversion; verify 100 cm gauge before attachment",
              "glb_basis":"glTF exporter performs standard Y-up conversion; use a standard glTF importer",
              "fbx_basis":"export axis_forward=X axis_up=Z with metre scene and apply_unit_scale=True; UE import transform still requires in-engine verification",
              "root":asset_id,"root_origin_m":[0,0,0],
              "root_origin_is_grip":any(name in ("grip_r","grip_l","shield_grip") and all(abs(v)<1e-6 for v in value["position_m"]) for name,value in links.items()),
              "attachment":"Align named grip anchor to hand/forearm socket; do not assume mesh origin equals grip.",
              "anchors":links,"deformation_controls":controls,
              "bbox_min_m":list(low),"bbox_max_m":list(high),"dimensions_m":list(high-low),
              "materials":sorted({m.name for o in objects if o.type=="MESH" for m in o.data.materials if m}),
              "notes":notes,"completed":["independent mesh","named assembly anchors","shared palette","BLEND/GLB/FBX export"],
              "remaining":["fit to approved body dimensions","close fingers around grip","character IK and attacks","UE import scale/orientation and multiplayer timing validation"],
              "files":{"blend":asset_id+".blend","glb":asset_id+".glb","fbx":asset_id+".fbx","preview":"preview.png","rear":"rear.png"}}
    (out/"interface.json").write_text(json.dumps(contract,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    cam,centre,span=add_lighting_and_camera(objects)
    bpy.ops.wm.save_as_mainfile(filepath=str(out/(asset_id+".blend")))
    if render:
        render_views(out,cam,centre,span,turnarounds)
    return contract


def render_views(out,cam,centre,span,turnarounds):
    if RENDER_DEVICE=="HIP":
        prefs=bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type="HIP"
        prefs.get_devices()
        enabled=[]
        for device in prefs.devices:
            device.use=device.type=="HIP"
            if device.use: enabled.append(device.name)
        if not enabled: raise RuntimeError("HIP requested but no HIP render device was detected")
        bpy.context.scene.cycles.device="GPU"
        print("CIVWAR_RENDER_HIP "+str(enabled),flush=True)
    def render_image(path):
        if SKIP_EXISTING and path.is_file():
            print("CIVWAR_KEEP_RENDER "+str(path),flush=True)
            return
        bpy.context.scene.render.filepath=str(path)
        bpy.ops.render.render(write_still=True)
    render_image(out/"preview.png")
    cam.location=centre+Vector((-2.4,3.2,1.7))*max(span,1)
    cam.rotation_euler=(centre-cam.location).to_track_quat("-Z","Y").to_euler()
    render_image(out/"rear.png")
    if turnarounds:
        bpy.context.scene.objects["DISPLAY_floor"].hide_render=True
        scene=bpy.context.scene
        scene.render.resolution_x=scene.render.resolution_y=1024
        scene.cycles.samples=8
        cam.data.ortho_scale=span*1.22
        for name,direction in (("front",(1,0,0)),("right",(0,1,0)),("back",(-1,0,0))):
            cam.location=centre+Vector(direction)*max(span,1)*4
            cam.rotation_euler=(centre-cam.location).to_track_quat("-Z","Y").to_euler()
            render_image(out/(name+".png"))
        (out/"views.json").write_text(json.dumps({"type":"orthographic_DCC_render","image_size":[1024,1024],"ortho_scale_m":span*1.22,"centre_m":list(centre),"views":{"front":"camera at +X","right":"camera at +Y","back":"camera at -X"},"lighting":"same studio lights, no camera-specific material change","status":"exact geometry reference; no character fit implied"},indent=2)+"\n",encoding="utf-8")


def render_existing(asset_id,turnarounds):
    out=OUT/asset_id
    contract=json.loads((out/"interface.json").read_text(encoding="utf-8"))
    bpy.ops.wm.open_mainfile(filepath=str(out/(asset_id+".blend")))
    centre=(Vector(contract["bbox_min_m"])+Vector(contract["bbox_max_m"]))/2
    span=max(contract["dimensions_m"])
    render_views(out,bpy.context.scene.camera,centre,span,turnarounds)
    return contract


def build(asset_id, render=True, turnarounds=False):
    global current_root
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.world=bpy.data.worlds.new("World")
    bpy.context.scene.unit_settings.system="METRIC"
    bpy.context.scene.unit_settings.scale_length=1
    current_root=anchor(asset_id,role="independent prop root; no actor body is included")
    family,notes=BUILDERS[asset_id]()
    bpy.context.view_layer.update()
    objects=list(bpy.context.scene.objects)
    for obj in objects:
        if obj.type=="MESH":
            if obj.data.shape_keys:
                continue  # BMesh writeback with an active morph can overwrite its Basis.
            bm=bmesh.new()
            bm.from_mesh(obj.data)
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            bm.to_mesh(obj.data)
            bm.free()
            if not obj.data.shape_keys:
                bpy.context.view_layer.objects.active=obj
                for modifier in list(obj.modifiers):
                    bpy.ops.object.modifier_apply(modifier=modifier.name)
    out=OUT/asset_id
    out.mkdir(parents=True,exist_ok=True)
    return export_and_report(asset_id,family,notes,objects,out,render,turnarounds)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--all",action="store_true")
    parser.add_argument("--asset",choices=list(BUILDERS),action="append")
    parser.add_argument("--no-render",action="store_true")
    parser.add_argument("--render-existing",action="store_true",help="Render saved .blend files without overwriting validated models")
    parser.add_argument("--device",choices=("CPU","HIP"),default="CPU")
    parser.add_argument("--skip-existing",action="store_true")
    parser.add_argument("--turnarounds",action="store_true",help="Also render matching 1024 px front/right/back views from actual geometry")
    args=parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    global RENDER_DEVICE,SKIP_EXISTING
    RENDER_DEVICE=args.device
    SKIP_EXISTING=args.skip_existing
    ids=list(BUILDERS) if args.all else (args.asset or ["Weapon_StoneAxe","Weapon_Rifle"])
    catalogue=json.loads((ROOT/"RawAssets/Art/Tripo_v01/catalog.json").read_text(encoding="utf-8"))
    expected={x["id"] for values in catalogue.values() if isinstance(values,list) for x in values if x.get("id","").startswith("Weapon_")}
    if set(BUILDERS)!=expected:
        raise RuntimeError("Weapon builders do not match current asset catalogue")
    results=[]
    for asset_id in ids:
        results.append(render_existing(asset_id,args.turnarounds) if args.render_existing else build(asset_id,not args.no_render,args.turnarounds))
        print("CIVWAR_WEAPON_COMPLETE "+asset_id,flush=True)
    record="last_render.json" if args.render_existing else "last_build.json"
    (OUT/record).write_text(json.dumps({"assets":[r["asset_id"] for r in results],"blender":bpy.app.version_string,"status":"rendered_not_gameplay_accepted" if args.render_existing else "built_not_gameplay_accepted"},indent=2)+"\n",encoding="utf-8")


if __name__=="__main__":
    main()
