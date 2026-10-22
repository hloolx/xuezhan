"""Bake genuine bow/crossbow source deformation into ordinary skeletal bones."""
from math import pi, sin
import bpy
from mathutils import Matrix, Vector


class FlexibleEquipment:
    def __init__(self, rig, module, profile, parent_bone):
        self.rig, self.module, self.profile = rig, module, profile
        self.parts, self.meshes, self.bones = [], [], []
        inverse = rig.matrix_world.inverted()
        for index, original in enumerate(module["meshes"]):
            transform = module["original_matrices"][original]
            keys = original.data.shape_keys
            points = [transform @ v.co for v in original.data.vertices]
            deltas = ([transform.to_3x3() @ (draw.co-base.co)
                       for base, draw in zip(keys.key_blocks["Basis"].data, keys.key_blocks["Draw"].data)]
                      if keys and "Draw" in keys.key_blocks else None)
            # These are the actual module's mesh vertices, with existing UVs
            # and materials. Fine cable controls preserve the source Draw shape.
            copied = original.copy()
            copied.data = original.data.copy()
            copied.name = "Skinned_"+original.name
            copied.animation_data_clear()
            if copied.data.shape_keys:
                copied.shape_key_clear()
            copied.data.transform(transform)
            copied.parent = None
            copied.matrix_world = Matrix.Identity(4)
            copied.modifiers.clear()
            bpy.context.scene.collection.objects.link(copied)
            copied.vertex_groups.clear()
            deform = copied.modifiers.new("ActualEquipmentSkin", "ARMATURE")
            deform.object = rig
            varying = deltas is not None or (profile == "bow_crew" and original.name.startswith("wood_limb")) or (
                profile == "crossbow" and original.name.startswith("limb_"))
            names = [f"eq_{index:02d}_{j:03d}" for j in range(len(points) if varying else 1)]
            item = {"object": copied, "source_name": original.name, "points": points,
                    "deltas": deltas, "varying": varying, "names": names}
            self.parts.append(item)
            self.meshes.append(copied)
            self.bones.extend(names)
            original.hide_render = True
            original.hide_set(True)
        bpy.ops.object.select_all(action="DESELECT")
        rig.select_set(True)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode="EDIT")
        for part in self.parts:
            for index, name in enumerate(part["names"]):
                head = part["points"][index] if part["varying"] else Vector()
                bone = rig.data.edit_bones.new(name)
                bone.head = inverse @ head
                bone.tail = inverse @ (head+Vector((0, .012, 0)))
                bone.parent = rig.data.edit_bones[parent_bone]
        bpy.ops.object.mode_set(mode="OBJECT")
        for part in self.parts:
            for index, name in enumerate(part["names"]):
                group = part["object"].vertex_groups.new(name=name)
                group.add([index] if part["varying"] else list(range(len(part["points"]))), 1., "REPLACE")
        self.rest = {name: rig.matrix_world @ rig.data.bones[name].matrix_local for name in self.bones}
        self.inverse = inverse

    def pose(self, prop_world, draw, visible=True):
        for part in self.parts:
            for index, name in enumerate(part["names"]):
                point = part["points"][index].copy() if part["varying"] else Vector()
                scale = 1.
                if part["deltas"] is not None:
                    point += part["deltas"][index]*draw
                elif self.profile == "bow_crew" and part["source_name"].startswith("wood_limb"):
                    # Bend the actual wooden limb between its fixed grip/tip.
                    # The supplied string's endpoints remain exactly attached.
                    fraction = min(1., max(0., (abs(point.z)-.07)/.49))
                    point.x -= .045*draw*sin(pi*fraction)
                elif self.profile == "crossbow" and part["source_name"].startswith("limb_"):
                    point.x -= .025*draw*sin(pi*min(1., abs(point.y)/.35))
                if part["source_name"].startswith(("loaded_bolt", "bolt_tip", "loaded_arrow", "arrow_tip")):
                    scale = 1. if visible else .001
                    if self.profile == "bow_crew":
                        point.x += .295*(1-draw)
                world = Matrix.LocRotScale(prop_world @ point,
                    prop_world.to_quaternion() @ self.rest[name].to_quaternion(),
                    self.rig.matrix_world.to_scale()*scale)
                self.rig.pose.bones[name].matrix = self.inverse @ world
        bpy.context.view_layer.update()

    def material_specs(self):
        specs = {}
        for obj in self.meshes:
            for material in obj.data.materials:
                if material and material.name not in specs:
                    bsdf = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
                    specs[material.name] = {"base_color": list(bsdf.inputs["Base Color"].default_value),
                        "metallic": float(bsdf.inputs["Metallic"].default_value),
                        "roughness": float(bsdf.inputs["Roughness"].default_value),
                        "team_color": material.name.startswith("CW_cobalt")}
        return specs
