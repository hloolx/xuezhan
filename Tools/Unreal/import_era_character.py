"""Import an actual human bundle, calibrated equipment and masked team PBR.

No runtime configuration is changed. execute() can join a serial UE batch.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).parent))
import import_beast_rider_preview as base
import import_stoneaxe_teamcolor as team
import fit_stoneaxe_socket as fit

VERSION = "era_character_actual_physical_60fps_flexible_slots_v3"
ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked(record):
    path = Path(record["path"])
    if digest(path) != record["sha256"]:
        raise ValueError("Source changed: " + str(path))
    return path


def options(u, skeleton=None):
    value = base.options(u, skeleton)
    if skeleton:
        value.get_editor_property("anim_sequence_import_data").set_editor_property("custom_sample_rate", 60)
    return value


def load_existing(u, path):
    # Unreal logs a commandlet error when load_asset probes a missing asset.
    return u.EditorAssetLibrary.load_asset(path) if u.EditorAssetLibrary.does_asset_exist(path) else None


def evaluate_pose(u, mesh, clips, sample):
    """Evaluate actual raw bones for humans or mounts; callers check names."""
    if sample["clip"] is None:
        pose = u.AnimPoseExtensions.get_reference_pose(mesh.get_editor_property("skeleton"))
    else:
        sequence = clips[sample["clip"]]
        if not 0 <= sample["time_seconds"] <= u.AnimationLibrary.get_sequence_length(sequence)+1e-6:
            raise ValueError("Pose sample is beyond the actual imported animation")
        options = u.AnimPoseEvaluationOptions()
        for key, value in {"evaluation_type": u.AnimDataEvalType.RAW, "should_retarget": False,
                           "extract_root_motion": False, "optional_skeletal_mesh": mesh}.items():
            options.set_editor_property(key, value)
        pose = u.AnimPoseExtensions.get_anim_pose_at_time(sequence, sample["time_seconds"], options)
    if not u.AnimPoseExtensions.is_valid(pose):
        raise ValueError("Actual UE raw pose is invalid")
    return pose


def classify_material_slots(names, manifest):
    """Resolve the actual imported names, never a guessed slot order."""
    embedded = manifest.get("embedded_equipment_materials", {})
    normalize = lambda name: name.replace(".", "_")
    normalized = {normalize(name): name for name in embedded}
    if len(normalized) != len(embedded):
        raise ValueError("Equipment material names collide after FBX sanitization")
    body_name = manifest.get("body_material_name")
    result = []
    for index, name in enumerate(names):
        canonical = normalize(name)
        if (body_name and canonical == normalize(body_name)) or (not body_name and len(names) == 1 and not embedded):
            result.append({"slot": index, "name": name, "kind": "body"})
        elif canonical in normalized:
            result.append({"slot": index, "name": name, "kind": "equipment", "source": normalized[canonical]})
        else:
            raise ValueError("Unknown actual skeletal material slot: "+name)
    if sum(row["kind"] == "body" for row in result) != 1:
        raise ValueError("Exactly one original body PBR slot is required")
    if {row["source"] for row in result if row["kind"] == "equipment"} != set(embedded):
        raise ValueError("Actual skeletal equipment material slots are incomplete")
    return result


def source_pbr(u, manifest, destination, mesh):
    textures = {}
    for channel, record in manifest["textures"].items():
        texture = base.task(u, record["path"], destination+"/Textures", "T_"+channel, factory=u.TextureFactory())
        texture.set_editor_property("srgb", channel == "base_color")
        if channel == "normal":
            texture.set_editor_property("compression_settings", u.TextureCompressionSettings.TC_NORMALMAP)
            texture.set_editor_property("flip_green_channel", True)
        elif channel != "base_color":
            texture.set_editor_property("compression_settings", u.TextureCompressionSettings.TC_MASKS)
        u.EditorAssetLibrary.save_loaded_asset(texture, only_if_is_dirty=False)
        textures[channel] = texture
    lib = u.MaterialEditingLibrary
    material = load_existing(u, destination+"/M_PBR")
    if material is None:
        material = u.AssetToolsHelpers.get_asset_tools().create_asset("M_PBR", destination, u.Material, u.MaterialFactoryNew())
        for index, (channel, texture) in enumerate(textures.items()):
            node = lib.create_material_expression(material, u.MaterialExpressionTextureSample, -400, index*180)
            base.set_properties(node, {"texture": texture, "sampler_type":
                u.MaterialSamplerType.SAMPLERTYPE_COLOR if channel == "base_color" else
                u.MaterialSamplerType.SAMPLERTYPE_NORMAL if channel == "normal" else u.MaterialSamplerType.SAMPLERTYPE_MASKS})
            for pin, prop in {"base_color": [("RGB", u.MaterialProperty.MP_BASE_COLOR)],
                              "normal": [("RGB", u.MaterialProperty.MP_NORMAL)],
                              "metallic_roughness": [("G", u.MaterialProperty.MP_ROUGHNESS), ("B", u.MaterialProperty.MP_METALLIC)]}[channel]:
                if not lib.connect_material_property(node, pin, prop):
                    raise ValueError("Original PBR channel could not connect")
    lib.set_base_material_usage(material, u.MaterialUsage.MATUSAGE_SKELETAL_MESH, True)
    errors = list(lib.recompile_material(material))
    if errors:
        raise ValueError("Original PBR shader failed: "+str(errors))
    slots = list(mesh.get_editor_property("materials"))
    assigned = classify_material_slots([str(s.get_editor_property("imported_material_slot_name")) for s in slots], manifest)
    for row in assigned:
        if row["kind"] == "body":
            actual = material
        else:
            actual = prop_material(u, destination+"/Equipment", row["source"],
                manifest["embedded_equipment_materials"][row["source"]], skeletal=True)
        slots[row["slot"]].set_editor_property("material_interface", actual)
        row["material"] = actual.get_path_name()
    mesh.set_editor_property("materials", slots)
    u.EditorAssetLibrary.save_loaded_asset(material, only_if_is_dirty=False)
    return {"material": material.get_path_name(), "textures": {key: value.get_path_name() for key, value in textures.items()},
            "actual_slots": assigned}


def body_material(u, manifest, destination, mesh):
    original = source_pbr(u, manifest, destination, mesh)
    report = manifest["team_cloth"]
    if report["source"]["sha256"] != manifest["textures"]["base_color"]["sha256"]:
        raise ValueError("Team selection belongs to a different original PBR")
    if report["unmasked_pixels_changed"] != 0 or not 0 < report["fraction_selected"] < .5:
        raise ValueError("Unexpected team cloth selection")
    mask = base.task(u, checked(report["mask"]), destination+"/Textures", "T_ClothMask", factory=u.TextureFactory())
    base.set_properties(mask, team.mask_settings(u))
    u.EditorAssetLibrary.save_loaded_asset(mask)
    name = "M_Body_TeamCloth"
    mat = load_existing(u, destination+"/"+name)
    lib = u.MaterialEditingLibrary
    if mat is None:
        mat = u.AssetToolsHelpers.get_asset_tools().create_asset(name, destination, u.Material, u.MaterialFactoryNew())
        nodes = {}
        for i, (label, cls) in enumerate(team.NODE_CLASSES.items()):
            if label not in {"roughness", "metallic"}:
                nodes[label] = lib.create_material_expression(mat, getattr(u, cls), -1400+(i%4)*320, (i//4)*240)
        for channel in ("base_color", "normal"):
            base.set_properties(nodes[channel], {
                "texture": u.EditorAssetLibrary.load_asset(original["textures"][channel]),
                "sampler_type": u.MaterialSamplerType.SAMPLERTYPE_COLOR if channel == "base_color" else u.MaterialSamplerType.SAMPLERTYPE_NORMAL})
        base.set_properties(nodes["cloth_mask"], {"texture": mask, "sampler_type": u.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE})
        nodes["luminance_weights"].set_editor_property("constant", team.color(u, team.LUMINANCE))
        nodes["safe_team_luminance"].set_editor_property("const_b", .01)
        base.set_properties(nodes["team_color"], {"parameter_name": "TeamColor", "default_value": team.color(u, team.TEAM_COLORS["Blue"])})
        base.set_properties(nodes["team_strength"], {"parameter_name": "TeamColorStrength", "default_value": 0.})
        for source, pin, target, target_pin in team.LINKS:
            if not lib.connect_material_expressions(nodes[source], pin, nodes[target], target_pin):
                raise ValueError("Could not connect masked team shader")
        orm = lib.create_material_expression(mat, u.MaterialExpressionTextureSample, -300, 750)
        base.set_properties(orm, {"texture": u.EditorAssetLibrary.load_asset(original["textures"]["metallic_roughness"]),
                                  "sampler_type": u.MaterialSamplerType.SAMPLERTYPE_MASKS})
        for node, pin, prop in ((nodes["cloth_blend"], "", u.MaterialProperty.MP_BASE_COLOR),
                               (nodes["normal"], "RGB", u.MaterialProperty.MP_NORMAL),
                               (orm, "G", u.MaterialProperty.MP_ROUGHNESS), (orm, "B", u.MaterialProperty.MP_METALLIC)):
            if not lib.connect_material_property(node, pin, prop):
                raise ValueError("Could not connect body PBR")
    lib.set_base_material_usage(mat, u.MaterialUsage.MATUSAGE_SKELETAL_MESH, True)
    errors = list(lib.recompile_material(mat))
    if errors:
        raise ValueError("Body shader failed: "+str(errors))
    u.EditorAssetLibrary.save_loaded_asset(mat, only_if_is_dirty=False)
    teams = [{"slot": row["slot"], "path": mat.get_path_name()} for row in original["actual_slots"] if row["kind"] == "body"]
    teams += [{"slot": row["slot"], "path": row["material"]} for row in original["actual_slots"] if row["kind"] == "equipment"
              and manifest["embedded_equipment_materials"][row["source"]]["team_color"]]
    return {"source_pbr": original, "team_materials": teams,
            "cloth_selection": report}


def prop_material(u, destination, name, spec, skeletal=False):
    if "pbr" in spec:
        from import_era_assets import material as source_material
        for rec in spec["pbr"]["textures"].values():
            checked(rec)
        material = source_material(u, spec["pbr"], destination+"/OriginalPBR")
        if skeletal:
            u.MaterialEditingLibrary.set_base_material_usage(material, u.MaterialUsage.MATUSAGE_SKELETAL_MESH, True)
        errors = list(u.MaterialEditingLibrary.recompile_material(material))
        if errors:
            raise ValueError("Actual source prop PBR shader failed: "+str(errors))
        u.EditorAssetLibrary.save_loaded_asset(material, only_if_is_dirty=False)
        return material
    name = "M_"+name.replace(".", "_")
    material = load_existing(u, destination+"/"+name)
    lib = u.MaterialEditingLibrary
    if material is None:
        material = u.AssetToolsHelpers.get_asset_tools().create_asset(name, destination, u.Material, u.MaterialFactoryNew())
        cls = u.MaterialExpressionVectorParameter if spec["team_color"] else u.MaterialExpressionConstant3Vector
        node = lib.create_material_expression(material, cls, -300, 0)
        if spec["team_color"]:
            base.set_properties(node, {"parameter_name": "TeamColor", "default_value": u.LinearColor(*spec["base_color"])})
        else:
            node.set_editor_property("constant", u.LinearColor(*spec["base_color"]))
        lib.connect_material_property(node, "", u.MaterialProperty.MP_BASE_COLOR)
        for i, (key, prop) in enumerate((("metallic", u.MaterialProperty.MP_METALLIC), ("roughness", u.MaterialProperty.MP_ROUGHNESS))):
            scalar = lib.create_material_expression(material, u.MaterialExpressionConstant, -300, 160+i*160)
            scalar.set_editor_property("r", spec[key])
            lib.connect_material_property(scalar, "", prop)
    if skeletal:
        lib.set_base_material_usage(material, u.MaterialUsage.MATUSAGE_SKELETAL_MESH, True)
    errors = list(lib.recompile_material(material))
    if errors:
        raise ValueError("Prop shader failed: "+str(errors))
    u.EditorAssetLibrary.save_loaded_asset(material, only_if_is_dirty=False)
    return material


def import_attachment(u, row, destination, mesh, clips, bone_names):
    if row["animated_mechanism"]:
        raise ValueError("Flexible equipment requires its skeletal delivery, not a static substitute")
    checked(row["fbx"])
    calibration = read(checked(row["calibration"]))
    bone = calibration["bone"]
    if bone not in bone_names or bone != row["bone"]:
        raise ValueError("Attachment bone missing")
    settings = u.FbxImportUI()
    base.set_properties(settings, {"automated_import_should_detect_type": False, "import_mesh": True,
        "import_as_skeletal": False, "import_animations": False, "import_materials": False,
        "import_textures": False, "mesh_type_to_import": u.FBXImportType.FBXIT_STATIC_MESH})
    base.set_properties(settings.get_editor_property("static_mesh_import_data"), {
        "import_uniform_scale": 1., "convert_scene": True, "convert_scene_unit": True,
        "force_front_x_axis": False, "combine_meshes": True, "auto_generate_collision": False})
    prop = base.task(u, row["fbx"]["path"], destination+"/Equipment", "SM_"+row["asset_id"], settings, u.FbxFactory())
    prop.set_editor_property("allow_cpu_access", True)
    materials, teams = [], []
    for index, slot in enumerate(prop.get_editor_property("static_materials")):
        name = str(slot.get_editor_property("imported_material_slot_name"))
        matches = [key for key in row["materials"] if key.replace(".", "_") == name.replace(".", "_")]
        if len(matches) != 1:
            raise ValueError("Unmatched actual prop material slot: "+name)
        spec = row["materials"][matches[0]]
        material = prop_material(u, destination+"/Equipment", matches[0], spec)
        prop.set_material(index, material)
        materials.append({"slot": index, "name": name, "path": material.get_path_name()})
        if spec["team_color"]:
            teams.append({"slot": index, "path": material.get_path_name()})
    vertices = []
    for index in range(prop.get_num_sections(0)):
        values = u.ProceduralMeshLibrary.get_section_from_static_mesh(prop, 0, index)[0]
        vertices.extend(fit.ue_vector(v) for v in values)
    expected_vertices = [fit.blender_point_to_ue(v) for v in calibration["local_vertices_m"]]
    from compare_equipment_vertices import compare_vertices
    geometry, _ = compare_vertices(vertices, expected_vertices, fit.VERTEX_TOLERANCE_CM)
    if not geometry["passed"]:
        raise ValueError("Actual static equipment geometry differs from source: "+str(geometry))
    local = None
    errors = {}
    for label, sample in calibration["poses"].items():
        evaluated = evaluate_pose(u, mesh, clips, sample)
        actual = u.AnimPoseExtensions.get_bone_pose(evaluated, bone, u.AnimPoseSpaces.WORLD)
        world = fit.ue_transform(actual)
        if local is None:
            fitted = fit.fit_socket(world, sample["weapon_rigid_world_matrix"])
            local = fit.compose(fitted["translation_cm"], fitted["rotation_xyzw"], fitted["scale"])
        predicted = fit.multiply(world, local)
        desired = fit.blender_transform_to_ue(sample["weapon_rigid_world_matrix"])
        errors[label] = max(fit.distance(fit.transform_point(predicted, vertex), fit.transform_point(desired, vertex))
                            for vertex in expected_vertices)
    if max(errors.values()) > .1:
        raise ValueError("Equipment bone transform disagrees across actual clips: "+str(errors))
    if max(fitted["scale"])-min(fitted["scale"]) > .0001:
        raise ValueError("Runtime equipment attachment requires uniform scale")
    rotation = u.Quat(*fitted["rotation_xyzw"]).rotator()
    u.EditorAssetLibrary.save_loaded_asset(prop, only_if_is_dirty=False)
    attachment = {"id": row["asset_id"], "parent_part": "body", "static_mesh": prop.get_path_name(),
                  "socket": bone, "translation_cm": fitted["translation_cm"],
                  "rotation_degrees": [rotation.pitch, rotation.yaw, rotation.roll],
                  "uniform_scale": sum(fitted["scale"])/3, "team_materials": teams}
    return {"runtime": attachment, "geometry": geometry, "pose_errors_cm": errors, "materials": materials}


def run(u, manifest_path, report_path):
    manifest = read(manifest_path)
    if not manifest["centimetre_normalization_passed"] or not manifest["mechanism_runtime_ready"]:
        raise ValueError("Scale or flexible mechanism delivery incomplete")
    if {c["clip"] for c in manifest["clips"]} != {"Idle", "Move", "Attack", "Hit", "Death"}:
        raise ValueError("Five actual clips required")
    for record in [manifest["body"], manifest["plan"], *manifest["clips"], *manifest["textures"].values()]:
        checked(record)
    destination = "/Game/ArtPilot/EraCharacters/"+manifest["asset_id"]+"/h"+hashlib.sha256((digest(manifest_path)+VERSION).encode()).hexdigest()[:16]
    mesh = base.task(u, manifest["body"]["path"], destination, "SK_"+manifest["asset_id"], options(u), u.FbxFactory())
    skeleton = mesh.get_editor_property("skeleton")
    settings = u.SkeletalMeshEditorSubsystem.get_lod_build_settings(mesh, 0)
    settings.set_editor_property("use_high_precision_skin_weights", True)
    u.SkeletalMeshEditorSubsystem.set_lod_build_settings(mesh, 0, settings)
    reference = u.AnimPoseExtensions.get_reference_pose(skeleton)
    bones = [str(x) for x in u.AnimPoseExtensions.get_bone_names(reference)]
    material_report = body_material(u, manifest, destination, mesh)
    clips, clip_report = {}, {}
    for row in manifest["clips"]:
        clip = base.task(u, checked(row), destination+"/Animations", "A_"+row["clip"], options(u, skeleton), u.FbxFactory())
        clip.set_editor_property("enable_root_motion", False)
        clip.set_editor_property("rate_scale", 1.)
        duration = float(u.AnimationLibrary.get_sequence_length(clip))
        if abs(duration-row["duration"]) > .005 or clip.get_editor_property("skeleton") != skeleton:
            raise ValueError("Actual animation duration/skeleton mismatch: "+json.dumps({
                "clip": row["clip"], "actual_seconds": duration, "expected_seconds": row["duration"],
                "actual_skeleton": clip.get_editor_property("skeleton").get_path_name(),
                "expected_skeleton": skeleton.get_path_name()}))
        clips[row["clip"]] = clip
        references = manifest["physical_pose_reference"][row["clip"]]
        error, count, scale_error = 0., 0, 0.
        for sample in references:
            evaluated = evaluate_pose(u, mesh, {row["clip"]: clip}, {"clip": row["clip"], "time_seconds": sample["time"]})
            for bone, source in sample["bones"].items():
                if bone not in bones:
                    raise ValueError("Physical source bone absent: "+bone)
                actual = u.AnimPoseExtensions.get_bone_pose(evaluated, bone, u.AnimPoseSpaces.WORLD)
                expected = [source["head_cm"][0], -source["head_cm"][1], source["head_cm"][2]]
                error = max(error, fit.distance(fit.ue_vector(actual.translation), expected))
                scale_error = max(scale_error, max(abs(a-b) for a, b in zip(fit.ue_vector(actual.scale3d), source["scale"])))
                count += 1
        if error > .1 or scale_error > .005:
            raise ValueError("Actual "+row["clip"]+" bones differ: "+str(error)+"cm scale="+str(scale_error))
        clip_report[row["clip"]] = {"asset": clip.get_path_name(), "duration": duration,
                                   "physical_max_bone_error_cm": error, "physical_max_scale_error": scale_error,
                                   "physical_bone_samples": count}
        u.EditorAssetLibrary.save_loaded_asset(clip, only_if_is_dirty=False)
    attachment_report = [import_attachment(u, row, destination, mesh, clips, bones) for row in manifest["attachments"]]
    muzzle = manifest.get("muzzle_bone")
    if muzzle and muzzle not in bones:
        raise ValueError("Actual muzzle bone missing")
    muzzle_samples = {}
    if muzzle:
        for name, clip, time in (("ready", "Idle", 0.), ("release", "Attack", manifest["attack_contact_seconds"])):
            evaluated = evaluate_pose(u, mesh, clips, {"clip": clip, "time_seconds": time})
            actual = u.AnimPoseExtensions.get_bone_pose(evaluated, muzzle, u.AnimPoseSpaces.WORLD)
            muzzle_samples[name] = {"clip": clip, "time": time, "transform": fit.ue_transform(actual)}
    for obj in (mesh, skeleton):
        u.EditorAssetLibrary.save_loaded_asset(obj, only_if_is_dirty=False)
    u.EditorAssetLibrary.save_directory(destination, only_if_is_dirty=False, recursive=True)
    packages = []
    for asset_path in u.EditorAssetLibrary.list_assets(destination, recursive=True, include_folder=False):
        file = ROOT/"Content"/(asset_path.split(".")[0][6:]+".uasset")
        if not file.is_file() or u.EditorAssetLibrary.load_asset(asset_path) is None:
            raise ValueError("Missing actual saved package: "+asset_path)
        packages.append({"asset": asset_path, "file": str(file), "sha256": digest(file)})
    result = {"status": "imported_preview_pending_gameplay", "asset_id": manifest["asset_id"],
              "destination": destination, "process_id": os.getpid(), "source_manifest": str(manifest_path),
              "source_manifest_sha256": digest(manifest_path), "mesh": mesh.get_path_name(),
              "skeleton": skeleton.get_path_name(), "bone_names": bones, "clips": clip_report,
              "materials": material_report, "attachments": attachment_report,
              "muzzle_bone": muzzle, "muzzle_samples": muzzle_samples, "packages": packages,
              "failures": [], "production_approved": False}
    Path(report_path).write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return result


def execute(manifest_path, report_path, prior_path=None):
    import unreal
    if prior_path:
        raise ValueError("Use saved-package readback; this importer does not repeat a fresh import")
    try:
        return run(unreal, Path(manifest_path), Path(report_path))
    except Exception as error:
        Path(report_path).write_text(json.dumps({"status": "failed", "process_id": os.getpid(),
            "error": str(error), "traceback": traceback.format_exc()}, indent=2), encoding="utf-8")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    execute(args.manifest.resolve(), args.output.resolve())
