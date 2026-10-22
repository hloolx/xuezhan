"""One frozen wood-factor pilot; offline preparation never starts Unreal."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
import time
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools"))
sys.path.insert(0, str(ROOT / "Tools/Unreal"))
import rock_tower_render as renderer
import base_stone_ink_contribution_render as ink

rock = renderer.rock
FOLDER = rock.BASE / "style_pilot_v01"
DEFAULT_SPEC = FOLDER / "spec_03.json"
VERSION = "rock_tower_single_bounded_wood_factor_v1"
BASE_GLB = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/base_stone_v01/pbr_v01/hf150ba0cde05/Base_Stone_PBR.glb"
JOINT = ROOT / "RawAssets/Art/Tripo_v01/reviews/BaseStoneInkTower_01"
REFERENCE_IMAGE = ROOT / "Saved/Screenshots/WindowsEditor/BaseStoneInkTower_01_team0_distance1300.png"
LUMINANCE = (.2126, .7152, .0722)
ORIGINAL = {"Dark": (.24, .105, .045), "Light": (.40, .235, .10)}
REGIONS = {"palisade_front_left": (690, 761), "palisade_front_center": (813, 764),
           "palisade_front_right": (1076, 754), "front_platform_post": (1144, 622)}
SLOTS = {"Frame": {0: ("CW_wood", "Dark"), 1: ("CW_wood_light", "Light")},
         "Arm": {0: ("CW_wood", "Dark"), 1: ("CW_wood_light", "Light")},
         "Adapter_front_negative_y": {0: ("CW_wood.005", "Dark")},
         "Adapter_front_positive_y": {0: ("CW_wood.008", "Dark")},
         "Adapter_rear": {0: ("CW_wood.011", "Dark")}}
SHOTS = [
    {"label": "01_old_blue_wide", "team": 0, "crop": "wide", "new": False},
    {"label": "02_new_blue_wide", "team": 0, "crop": "wide", "new": True},
    {"label": "03_old_red_wide", "team": 1, "crop": "wide", "new": False},
    {"label": "04_new_red_wide", "team": 1, "crop": "wide", "new": True},
    {"label": "05_old_wood_close", "team": 0, "crop": "fit", "new": False},
    {"label": "06_new_wood_close", "team": 0, "crop": "fit", "new": True},
]
for shot in SHOTS:
    shot.update(slot=0, pitch=35, stone=True)
SESSION = None


def digest(value):
    def normalized(item):
        if isinstance(item, bool) or item is None:
            return item
        if isinstance(item, (int, float)):
            if not math.isfinite(item):
                raise ValueError("Fingerprint contains nonfinite numeric value")
            return {"number": format(item, ".17g")}
        if isinstance(item, dict):
            return {key: normalized(part) for key, part in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalized(part) for part in item]
        return item
    return hashlib.sha256(json.dumps(normalized(value), sort_keys=True, ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def source_record(path):
    return rock.file_record(Path(path))


def srgb_linear(value):
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("sRGB sample must be finite and normalized")
    return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4


def bounded_proposal(reference, roughness):
    if len(reference) != 3 or any(not math.isfinite(value) or not 0 < value <= 1 for value in reference):
        raise ValueError("Positive finite semantic wood reference required")
    if not math.isfinite(roughness) or not 0 <= roughness <= 1:
        raise ValueError("Finite linear roughness required")
    reference_luma = sum(value * weight for value, weight in zip(reference, LUMINANCE))
    families = {}
    for name, original in ORIGINAL.items():
        original_luma = sum(value * weight for value, weight in zip(original, LUMINANCE))
        candidate = [.85 * original_luma * (.5 * value / original_luma + .5 * target / reference_luma)
                     for value, target in zip(original, reference)]
        bounded = [min(value * 1.35, max(value * .70, trial)) for value, trial in zip(original, candidate)]
        families[name] = {"base_color_linear": bounded, "roughness": min(.78, max(.66, roughness)), "metallic": 0.0,
                          "original_base_color_linear": list(original), "original_roughness": .66}
    return families


def sample_reference():
    import numpy as np
    from PIL import Image
    from base_stone_validate_ue import read_glb_geometry

    payload = BASE_GLB.read_bytes()
    length = struct.unpack_from("<I", payload, 12)[0]
    document = json.loads(payload[20:20 + length])
    binary = payload[28 + length:]
    material = document["materials"][0]["pbrMetallicRoughness"]
    arrays, embedded = {}, {}
    for key, index_key in (("albedo", "baseColorTexture"), ("roughness", "metallicRoughnessTexture")):
        image_index = document["textures"][material[index_key]["index"]]["source"]
        image = document["images"][image_index]
        view = document["bufferViews"][image["bufferView"]]
        data = binary[view.get("byteOffset", 0):view.get("byteOffset", 0) + view["byteLength"]]
        arrays[key] = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=float) / 255
        if arrays[key].shape != (2048, 2048, 3):
            raise ValueError("Actual Base2048 embedded textures required")
        embedded[key] = {"image_index": image_index, "sha256": hashlib.sha256(data).hexdigest(), "dimensions": [2048, 2048]}
    albedo = np.where(arrays["albedo"] <= .04045, arrays["albedo"] / 12.92, ((arrays["albedo"] + .055) / 1.055) ** 2.4)
    roughness = arrays["roughness"][:, :, 1]
    raw_corners, raw_indices = read_glb_geometry(BASE_GLB)
    corners, indices = np.asarray(raw_corners), np.asarray(raw_indices)
    vertices = corners[indices, :3]
    first_edge, second_edge = vertices[:, 1] - vertices[:, 0], vertices[:, 2] - vertices[:, 0]
    origin, angle = np.asarray((0, 1221.600, 554.626)), math.radians(20)
    forward = np.asarray((0, -math.cos(angle), -math.sin(angle)))
    right, up = np.asarray((1, 0, 0)), np.asarray((0, -math.sin(angle), math.cos(angle)))
    focal, rows = 800 / math.tan(math.radians(22.5)), []
    for semantic, center in REGIONS.items():
        for horizontal in (-4, -2, 0, 2, 4):
            for vertical in (-4, -2, 0, 2, 4):
                pixel = np.asarray(center) + (horizontal, vertical)
                direction = forward + right * ((pixel[0] + .5 - 800) / focal) + up * ((450 - pixel[1] - .5) / focal)
                direction /= np.linalg.norm(direction)
                cross = np.cross(direction, second_edge)
                determinant = np.einsum("ij,ij->i", first_edge, cross)
                valid = np.abs(determinant) > 1e-10
                inverse = np.divide(1, determinant, out=np.zeros_like(determinant), where=valid)
                relative = origin - vertices[:, 0]
                bary_first = np.einsum("ij,ij->i", relative, cross) * inverse
                another = np.cross(relative, first_edge)
                bary_second = (another @ direction) * inverse
                distance = np.einsum("ij,ij->i", second_edge, another) * inverse
                valid &= (bary_first >= 0) & (bary_second >= 0) & (bary_first + bary_second <= 1) & (distance > 0)
                choices = np.flatnonzero(valid)
                if not len(choices):
                    raise ValueError("Semantic wood reference ray missed")
                face = int(choices[np.argmin(distance[choices])])
                bary = np.asarray((1 - bary_first[face] - bary_second[face], bary_first[face], bary_second[face]))
                uv = bary @ corners[indices[face], 3:]
                texel = np.clip(np.floor(uv * 2048).astype(int), 0, 2047)
                column, row = texel.tolist()
                rows.append({"semantic": semantic, "screen_pixel": pixel.tolist(), "source_triangle": face,
                             "barycentric": bary.tolist(), "hit_ue_cm": (origin + distance[face] * direction).tolist(),
                             "source_uv": uv.tolist(), "source_texel": texel.tolist(),
                             "source_srgb": arrays["albedo"][row, column].tolist(), "source_linear": albedo[row, column].tolist(),
                             "source_linear_roughness_G": float(roughness[row, column])})
    reference = np.median([row["source_linear"] for row in rows], axis=0).tolist()
    roughness_reference = float(np.median([row["source_linear_roughness_G"] for row in rows]))
    return {"source": source_record(BASE_GLB), "semantic_image": source_record(REFERENCE_IMAGE), "embedded": embedded,
            "regions": {name: list(center) for name, center in REGIONS.items()}, "samples": rows,
            "median_linear_rgb": reference, "median_linear_roughness": roughness_reference,
            "families": bounded_proposal(reference, roughness_reference),
            "method": "100 finite actual-camera rays into original Tripo mesh, then source UV texels. Screenshot is semantic selection only, never a color sample. Albedo sRGB is decoded to linear; metallic-roughness G is already linear.",
            "limits": "Four reviewed wood-interior patches, not the whole base. Source albedo may include baked shading; therefore only a bounded chromaticity blend and15percent luminance reduction, not absolute matching to dark texel medians. Rounded camera/TAA uncertainty remains.",
            "recipe": {"chroma_reference_weight": .5, "original_luminance_scale": .85, "per_channel_original_ratio_bounds": [.70, 1.35], "roughness_bounds": [.66, .78]}}


def slot_contract():
    return {name: {str(index): list(value) for index, value in mapping.items()} for name, mapping in SLOTS.items()}


def plan():
    context = renderer.input_context(rock.DELIVERY / "ue_fresh_01.json")
    base = ink.check_team_report(ink.adapter.FOLDER / "ue_fresh_01.json")
    joint = rock.read_json(JOINT / "agent_visual_review.json")
    protected = []
    for row in joint["integrity"]["base_packages"] + joint["integrity"]["tower_packages"]:
        path = ROOT / row["file"]
        if rock.sha256(path) != row["expected_sha256"]:
            raise ValueError("One of69 protected packages changed")
        protected.append(source_record(path))
    if len({row["file"] for row in protected}) != 69:
        raise ValueError("Exactly69 unique protected packages required")
    reference = sample_reference()
    paths = [Path(row["file"]) for row in context["dependencies"]] + [Path(row["file"]) for row in protected]
    paths.extend([BASE_GLB, REFERENCE_IMAGE, JOINT / "capture_report.json", JOINT / "agent_visual_review.json",
                  rock.BASE / "style_audit_v01/report.json", ink.adapter.FOLDER / "ue_fresh_01.json", Path(__file__),
                  ROOT / "Tests/Art/test_rock_tower_wood_style.py", ROOT / "Tools/base_stone_validate_ue.py"])
    paths.extend(rock.DELIVERY.glob("*.glb"))
    sources = [source_record(path) for path in sorted(set(path.resolve() for path in paths))]
    result = {"version": VERSION, "status": "frozen_single_candidate_prepared_not_executed", "reference": reference,
              "slot_overrides": slot_contract(), "shots": SHOTS, "source_files": sources, "protected_packages": protected,
              "base_team_material": base["result"]["material"],
              "base_team_result": {key: base["result"][key] for key in ("mask", "contribution", "material")},
              "new_package_count": 3, "new_texture_count": 0, "protected_package_count": 69,
              "changed_fields": ["wood base-color constant", "wood roughness constant"],
              "unchanged": ["mesh", "UV", "pivot", "normal", "nonwood", "CW_hide", "stone", "cloth", "FireSeq", "Content config"],
              "runtime_approved": False, "production_approved": False, "texture_finish_approved": False,
              "scope": "One bounded factor-only tone pilot. No grain, weathered texture or final style claim."}
    result["fingerprint"] = digest(result)
    result["destination"] = "/Game/ArtPilot/RockTowerWood/h" + result["fingerprint"][:16]
    return result


def validate_spec(spec):
    unsigned = {key: value for key, value in spec.items() if key not in {"fingerprint", "destination"}}
    if digest(unsigned) != spec["fingerprint"] or spec["destination"] != "/Game/ArtPilot/RockTowerWood/h" + spec["fingerprint"][:16]:
        raise ValueError("Spec fingerprint/destination mismatch")
    if spec["version"] != VERSION or spec["shots"] != SHOTS or spec["slot_overrides"] != slot_contract():
        raise ValueError("Frozen shot/slot/version contract differs")
    if (spec["new_package_count"], spec["new_texture_count"], spec["protected_package_count"]) != (3, 0, 69):
        raise ValueError("Three new material-only packages and69 protected required")
    protected = spec["protected_packages"]
    if len(protected) != 69 or len({row["file"] for row in protected}) != 69 or any(Path(row["file"]).suffix.lower() != ".uasset" for row in protected):
        raise ValueError("Exact69 unique protected uasset records required")
    if not {row["file"] for row in protected} <= {row["file"] for row in spec["source_files"]}:
        raise ValueError("Protected packages must be bound into frozen sources")
    expected = bounded_proposal(spec["reference"]["median_linear_rgb"], spec["reference"]["median_linear_roughness"])
    if spec["reference"]["families"] != expected:
        raise ValueError("Only the bounded single proposal is permitted")
    rock.check_records(spec["source_files"] + spec["protected_packages"])


def asset_names():
    return {"Master": "M_RT_WoodTone", "Dark": "MI_RT_WoodDark", "Light": "MI_RT_WoodLight"}


def write_report(path, value):
    path = Path(path).resolve()
    if not path.is_relative_to(FOLDER.resolve()):
        raise ValueError("Report must stay inside owned style pilot")
    rock.write_new(path, value)


def create_materials(unreal, spec):
    library, editing = unreal.EditorAssetLibrary, unreal.MaterialEditingLibrary
    destination = spec["destination"]
    if library.does_directory_exist(destination):
        raise FileExistsError("Immutable trial branch already exists; inspect prior receipt, do not recreate")
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset(asset_names()["Master"], destination, unreal.Material, unreal.MaterialFactoryNew())
    if not isinstance(material, unreal.Material):
        raise TypeError("New material creation failed")
    material.set_editor_property("two_sided", True)
    material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_OPAQUE)
    defaults = spec["reference"]["families"]["Dark"]
    for name, node_class, prop in (("WoodColor", unreal.MaterialExpressionVectorParameter, unreal.MaterialProperty.MP_BASE_COLOR),
                                   ("WoodRoughness", unreal.MaterialExpressionScalarParameter, unreal.MaterialProperty.MP_ROUGHNESS),
                                   ("WoodMetallic", unreal.MaterialExpressionConstant, unreal.MaterialProperty.MP_METALLIC)):
        node = editing.create_material_expression(material, node_class, -300, 0)
        node.set_editor_property("desc", name)
        if name == "WoodColor":
            node.set_editor_property("parameter_name", name)
            node.set_editor_property("default_value", unreal.LinearColor(*defaults["base_color_linear"], 1))
        elif name == "WoodRoughness":
            node.set_editor_property("parameter_name", name)
            node.set_editor_property("default_value", defaults["roughness"])
        else:
            node.set_editor_property("r", 0.0)
        if not editing.connect_material_property(node, "RGB" if name == "WoodColor" else "", prop):
            raise ValueError("Failed exact material property connection")
    errors = list(editing.recompile_material(material))
    if errors:
        raise ValueError("Wood material compile failed: " + str(errors))
    assets = {"Master": material}
    for family in ("Dark", "Light"):
        instance = tools.create_asset(asset_names()[family], destination, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        if not isinstance(instance, unreal.MaterialInstanceConstant):
            raise TypeError("New material instance creation failed")
        editing.set_material_instance_parent(instance, material)
        settings = spec["reference"]["families"][family]
        editing.set_material_instance_vector_parameter_value(instance, "WoodColor", unreal.LinearColor(*settings["base_color_linear"], 1))
        editing.set_material_instance_scalar_parameter_value(instance, "WoodRoughness", settings["roughness"])
        editing.update_material_instance(instance)
        assets[family] = instance
    return assets


def audit_materials(unreal, spec, assets):
    editing, material = unreal.MaterialEditingLibrary, assets["Master"]
    if not isinstance(material, unreal.Material) or not material.get_editor_property("two_sided") or material.get_editor_property("blend_mode") != unreal.BlendMode.BLEND_OPAQUE:
        raise ValueError("Opaque two-sided wood material required")
    expressions = list(editing.get_material_expressions(material))
    nodes = {str(node.get_editor_property("desc")): node for node in expressions}
    classes = {"WoodColor": unreal.MaterialExpressionVectorParameter, "WoodRoughness": unreal.MaterialExpressionScalarParameter,
               "WoodMetallic": unreal.MaterialExpressionConstant}
    if len(expressions) != 3 or set(nodes) != set(classes) or any(not isinstance(nodes[name], kind) for name, kind in classes.items()):
        raise ValueError("Exact three-node graph required; no textures or hidden vertex displacement")
    if set(map(str, editing.get_vector_parameter_names(material))) != {"WoodColor"} or set(map(str, editing.get_scalar_parameter_names(material))) != {"WoodRoughness"}:
        raise ValueError("Actual parameter names differ from instance overrides")
    for name in ("WoodColor", "WoodRoughness"):
        if str(nodes[name].get_editor_property("parameter_name")) != name:
            raise ValueError("Graph parameter identity differs")
    defaults = spec["reference"]["families"]["Dark"]
    color_default = nodes["WoodColor"].get_editor_property("default_value")
    if max(abs(actual - expected) for actual, expected in zip((color_default.r, color_default.g, color_default.b), defaults["base_color_linear"])) > 1e-6 or abs(nodes["WoodRoughness"].get_editor_property("default_value") - defaults["roughness"]) > 1e-6:
        raise ValueError("Master defaults differ from frozen Dark candidate")
    outputs = {}
    for name, property_name in (("WoodColor", "MP_BASE_COLOR"), ("WoodRoughness", "MP_ROUGHNESS"), ("WoodMetallic", "MP_METALLIC")):
        prop = getattr(unreal.MaterialProperty, property_name)
        if editing.get_material_property_input_node(material, prop) != nodes[name]:
            raise ValueError("Material property uses wrong node: " + name)
        outputs[name] = str(editing.get_material_property_input_node_output_name(material, prop))
        if name == "WoodColor" and outputs[name] != "RGB":
            raise ValueError("WoodColor must use all RGB, not one vector component")
        if any(editing.get_inputs_for_material_expression(material, nodes[name])):
            raise ValueError("Constant-factor graph cannot have hidden upstream inputs")
    for property_name in ("MP_WORLD_POSITION_OFFSET", "MP_OPACITY", "MP_OPACITY_MASK", "MP_NORMAL", "MP_EMISSIVE_COLOR"):
        if editing.get_material_property_input_node(material, getattr(unreal.MaterialProperty, property_name)):
            raise ValueError("Unexpected noncolor override: " + property_name)
    if abs(nodes["WoodMetallic"].get_editor_property("r")) > 1e-8:
        raise ValueError("Wood must remain nonmetallic")
    values = {}
    for family in ("Dark", "Light"):
        instance = assets[family]
        if not isinstance(instance, unreal.MaterialInstanceConstant) or instance.get_editor_property("parent") != material:
            raise ValueError("Material instance parent/class differs")
        color = editing.get_material_instance_vector_parameter_value(instance, "WoodColor")
        actual = [float(color.r), float(color.g), float(color.b)]
        roughness = float(editing.get_material_instance_scalar_parameter_value(instance, "WoodRoughness"))
        expected = spec["reference"]["families"][family]
        if max(abs(left - right) for left, right in zip(actual, expected["base_color_linear"])) > 1e-6 or abs(roughness - expected["roughness"]) > 1e-6:
            raise ValueError("Frozen actual linear factor mismatch")
        values[family] = {"color_linear": actual, "roughness": roughness, "metallic": 0}
    return {"status": "passed", "actual_values": values, "actual_output_names": outputs, "nodes": 3, "textures": 0,
            "world_position_offset": False, "nonwood_changed": False, "production_approved": False}


def execute_materials(unreal, spec, prior=None):
    library = unreal.EditorAssetLibrary
    if prior:
        if prior.get("status") != "wood_style_saved_requires_independent_fresh" or prior["execution_process_id"] == os.getpid() or prior["spec_fingerprint"] != spec["fingerprint"]:
            raise ValueError("Successful matching initial in another process required")
        rock.check_records(prior["package_files"])
        assets = {name: library.load_asset(spec["destination"] + "/" + value) for name, value in asset_names().items()}
    else:
        assets = create_materials(unreal, spec)
    audit = audit_materials(unreal, spec, assets)
    files = []
    for asset in assets.values():
        asset_path = asset.get_path_name()
        if not asset_path.startswith(spec["destination"] + "/"):
            raise ValueError("Save outside new branch prohibited")
        path = Path(unreal.Paths.project_content_dir()).resolve() / (asset_path.removeprefix("/Game/").split(".")[0] + ".uasset")
        if not prior and not library.save_loaded_asset(asset, only_if_is_dirty=False):
            raise ValueError("Could not save new material-only package")
        files.append({**source_record(path), "asset_path": asset_path, "class_name": asset.get_class().get_name()})
    listed = set(map(str, library.list_assets(spec["destination"], recursive=True, include_folder=False)))
    if listed != {row["asset_path"] for row in files} or len(files) != 3:
        raise ValueError("Branch must contain exactly one master and two instances")
    if prior and {row["asset_path"]: row["sha256"] for row in files} != {row["asset_path"]: row["sha256"] for row in prior["package_files"]}:
        raise ValueError("New packages changed during fresh reopen")
    validate_spec(spec)
    return {"version": VERSION, "status": "wood_style_fresh_passed_pending_actual6" if prior else "wood_style_saved_requires_independent_fresh",
            "execution_process_id": os.getpid(), "initial_process_id": prior["execution_process_id"] if prior else os.getpid(),
            "spec_fingerprint": spec["fingerprint"], "destination": spec["destination"], "package_files": files, "audit": audit,
            "validated_in_fresh_process": prior is not None, "all69_old_packages_unchanged": True,
            "runtime_approved": False, "production_approved": False, "created_at": datetime.now(timezone.utc).isoformat()}


def check_fresh(spec, report):
    if report.get("status") != "wood_style_fresh_passed_pending_actual6" or not report.get("validated_in_fresh_process") or report["initial_process_id"] == report["execution_process_id"]:
        raise ValueError("Independent actual fresh material validation required")
    if report["spec_fingerprint"] != spec["fingerprint"] or report["destination"] != spec["destination"] or len(report["package_files"]) != 3 or report["audit"]["status"] != "passed":
        raise ValueError("Fresh material result differs from frozen candidate")
    rock.check_records(report["package_files"])


class WoodReview(renderer.RockReview):
    def __init__(self, unreal, args, context, spec, fresh):
        self.spec, self.fresh = spec, fresh
        super().__init__(unreal, args, context)
        self.report.update(version=VERSION, spec_fingerprint=spec["fingerprint"], expected_actual_images=6,
                           protected_packages=69, new_material_packages=3, new_texture_count=0)
        self.report["limits"] = ["Factor-only wood tone/roughness trial, not weathered wood texture or final style.",
                                 "Existing Base team shader is the same in old/new pairs; only seven turret wood slots change.",
                                 "No gameplay, timing, full-load or network approval."]

    def setup(self):
        super().setup()
        unreal, library = self.unreal, self.unreal.EditorAssetLibrary
        self.wood = {name: library.load_asset(self.spec["destination"] + "/" + value) for name, value in asset_names().items()}
        audit_materials(unreal, self.spec, self.wood)
        self.base_team = self.base_component.create_dynamic_material_instance(0, library.load_asset(self.spec["base_team_material"]), "BaseWoodReviewTeam")
        if not isinstance(self.base_team, unreal.MaterialInstanceDynamic):
            raise ValueError("Existing accepted Base team shader unavailable")
        self.base_team.set_scalar_parameter_value("TeamColorStrength", 1.0)
        self.required_paths.update((self.spec["base_team_result"]["mask"], self.spec["base_team_result"]["contribution"]))
        if len(self.required_paths) != 5:
            raise ValueError("Exactly existing Base3+guard+ink required; no wood textures")
        unreal.SystemLibrary.execute_console_command(self.world, "Editor.AsyncAssetCompilationFinishAll")
        for path in self.required_paths:
            library.load_asset(path).set_force_mip_levels_to_be_resident(self.args.timeout + 20, 0)
        self.dump = self.request_dump()
        self.report["resource_preparation"].update(required_texture_paths=sorted(self.required_paths), source="Existing accepted Base5 textures only; no new wood textures")

    def prepare(self):
        super().prepare()
        team_name = "Blue" if self.shot["team"] == 0 else "Red"
        team_color = ink.adapter.shared.TEAM_COLORS[team_name]
        self.base_team.set_vector_parameter_value("TeamColor", self.unreal.LinearColor(*team_color))
        for item in self.slots:
            for name, (_, component) in item["components"].items():
                for index, (_, family) in SLOTS.get(name, {}).items():
                    original = self.meshes[name].get_material(index)
                    component.set_material(index, self.wood[family] if self.shot["new"] else original)
        self.dump = self.request_dump()
        self.wood_resource_started = self.wood_last_request = time.monotonic()
        self.wood_requests = 1
        self.stage = "wood_resources"

    def advance(self, delta_seconds):
        if self.stage != "wood_resources":
            return super().advance(delta_seconds)
        try:
            now = time.monotonic()
            if now - self.started > self.args.timeout or now - self.wood_resource_started > 20:
                raise TimeoutError("Per-shot five-texture residency timed out")
            records = renderer.parse_texture_dump(self.args.log_file.read_text(encoding="utf-8-sig", errors="replace"), *self.dump, self.required_paths)
            if renderer.textures_resident(records, self.required_paths):
                self.residency = records
                self.phase_started, self.tick_count, self.stage = now, 0, "settle"
            elif records is not None and now - self.wood_last_request > .5:
                if self.wood_requests >= 4:
                    raise TimeoutError("Four per-shot native dumps did not prove all5x2048")
                self.dump = self.request_dump()
                self.wood_requests += 1
                self.wood_last_request = now
        except Exception as error:
            self.report["error"] = str(error)
            self.finish("failed")

    def audit_components(self):
        actual = super().audit_components()
        overrides = []
        for item in self.slots:
            for name, (_, component) in item["components"].items():
                mesh = self.meshes[name]
                materials = list(mesh.get_editor_property("static_materials"))
                for index, slot in enumerate(materials):
                    current = component.get_material(index)
                    if name == "Cloth":
                        if current != item["mid"]:
                            raise ValueError("Existing runtime-equivalent cloth override changed")
                        continue
                    mapping = SLOTS.get(name, {}).get(index)
                    if mapping:
                        expected_name, family = mapping
                        if str(slot.get_editor_property("material_slot_name")) != expected_name:
                            raise ValueError("Wood slot semantic name differs")
                        expected = self.wood[family] if self.shot["new"] else mesh.get_material(index)
                    else:
                        expected = mesh.get_material(index)
                    if current != expected:
                        raise ValueError("Component-only wood/nonwood preservation failed")
                    overrides.append({"component": name, "slot": index, "wood": bool(mapping), "actual": current.get_path_name()})
        actual["wood_slot_checks"] = overrides
        color = self.base_team.get_vector_parameter_value("TeamColor")
        observed = [float(color.r), float(color.g), float(color.b), float(color.a)]
        expected = ink.adapter.shared.TEAM_COLORS["Blue" if self.shot["team"] == 0 else "Red"]
        if self.base_component.get_material(0) != self.base_team or self.base_team.get_scalar_parameter_value("TeamColorStrength") != 1 or max(abs(left - right) for left, right in zip(observed, expected)) > 1e-6:
            raise ValueError("Existing accepted Base shader/team parameters changed")
        actual["existing_base_team_material"] = self.base_component.get_material(0).get_path_name()
        actual["residency_is_fresh_per_shot"] = True
        actual["ink_native_format"] = ink.validate_contribution_format(self.residency, self.spec["base_team_result"]["contribution"])
        return actual

    def position_camera(self, audit):
        fitted = super().position_camera(audit)
        pair = (self.shot["team"], self.shot["crop"])
        if not hasattr(self, "pair_cameras"):
            self.pair_cameras = {}
        if pair in self.pair_cameras and fitted != self.pair_cameras[pair]:
            raise ValueError("Old/new pair camera changed")
        self.pair_cameras[pair] = fitted
        return fitted

    def finish(self, status):
        global SESSION
        if self.finished:
            return
        if status == "actual12images_captured_pending_root_visual_review":
            status = "actual6images_captured_pending_visual_and_pixel_review" if len(self.report["images"]) == 6 else "failed"
        try:
            validate_spec(self.spec)
            rock.check_records(self.fresh["package_files"])
            self.report["all69_old_and3_new_packages_unchanged"] = True
        except Exception as error:
            self.report["preservation_error"], status = str(error), "failed"
        try:
            super().finish(status)
        finally:
            SESSION = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--phase", choices=("validate", "initial", "fresh", "render"), default=os.environ.get("CIVWAR_ROCK_WOOD_PHASE", "validate"))
    parser.add_argument("--spec", type=Path, default=os.environ.get("CIVWAR_ROCK_WOOD_SPEC", str(DEFAULT_SPEC)))
    parser.add_argument("--log-file", type=Path, default=os.environ.get("CIVWAR_ROCK_WOOD_LOG"))
    args, _ = parser.parse_known_args()
    if args.plan:
        print(json.dumps(plan(), ensure_ascii=True))
        return
    spec = rock.read_json(args.spec)
    validate_spec(spec)
    if args.phase == "validate":
        print(json.dumps({"status": "validated_without_unreal", "fingerprint": spec["fingerprint"], "new_packages": 3, "new_textures": 0}))
        return
    if os.environ.get("CIVWAR_ROCK_WOOD_TOKEN") != spec["destination"].split("/")[-1]:
        raise ValueError("Root authorization token for this exact branch required")
    import unreal
    output = FOLDER / ("render_01" if args.phase == "render" else args.phase + "_01.json")
    if output.exists():
        raise FileExistsError("Never overwrite a previous execution or partial branch")
    if args.phase != "render":
        try:
            prior = rock.read_json(FOLDER / "initial_01.json") if args.phase == "fresh" else None
            report = execute_materials(unreal, spec, prior)
        except Exception as error:
            write_report(output, {"status": "failed", "error": str(error), "phase": args.phase, "execution_process_id": os.getpid(), "production_approved": False})
            raise
        write_report(output, report)
        return
    fresh = rock.read_json(FOLDER / "fresh_01.json")
    check_fresh(spec, fresh)
    context = renderer.input_context(rock.DELIVERY / "ue_fresh_01.json")
    context["dependencies"].extend(spec["source_files"] + fresh["package_files"])
    output.mkdir()
    renderer.SHOTS = SHOTS
    render_args = SimpleNamespace(fresh_report=rock.DELIVERY / "ue_fresh_01.json", output=output,
                                  log_file=args.log_file, size=512, timeout=160)
    global SESSION
    SESSION = WoodReview(unreal, render_args, context, spec, fresh)
    try:
        SESSION.setup()
    except Exception as error:
        SESSION.report["error"] = str(error)
        SESSION.finish("failed_before_capture")
        raise


if __name__ == "__main__":
    main()
