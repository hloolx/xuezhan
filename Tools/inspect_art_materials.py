"""UE 5.8 material graph/texture audit and narrowly scoped ISM usage repair.

Run in UE with CIVWAR_MATERIAL_IMPORT_REPORT=<import report>, or set
CIVWAR_MATERIAL_ASSETS to semicolon-separated mesh/material object paths.
Without either, inspect the seven registered environment mothers and M_CWStylized.
CIVWAR_MATERIAL_REPAIR=1 enables usage-flag repair (never replaces material graphs).
CIVWAR_MATERIAL_REPORT selects the output JSON. This script does not launch UE.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[1]
AUDIT_VERSION = "ue58_pbr_ism_v2"
CHANNELS = {
    "base_color": ("MP_BASE_COLOR", "BaseColor", "BaseColorTexture", "bHasBaseColorTexture"),
    "roughness": ("MP_ROUGHNESS", "Roughness", "MetallicRoughnessTexture", "bHasMetallicRoughnessTexture"),
    "metallic": ("MP_METALLIC", "Metallic", "MetallicRoughnessTexture", "bHasMetallicRoughnessTexture"),
    "normal": ("MP_NORMAL", "Normal", "NormalTexture", "bHasNormalTexture"),
}
# These are the actual UE 5.8 InterchangeGLTFMaterial.h contracts. Importing as
# Materials keeps the source bindings visible at the native function call.
NATIVE_GLTF_FUNCTIONS = {
    "/InterchangeAssets/gltf/MaterialBodies/MF_" + n + "_Body.MF_" + n + "_Body"
    for n in ("Default", "ClearCoat", "Sheen", "Transmission")
}


def source_materials(source):
    """Read only GLB JSON; do not decode, alter, or regenerate image payloads."""
    source = Path(source)
    if source.suffix.lower() not in {".glb", ".gltf"}:
        return {"available": False, "reason": "source_is_not_gltf", "materials": []}
    if source.suffix.lower() == ".glb":
        with source.open("rb") as stream:
            header = stream.read(12)
            if len(header) != 12:
                raise ValueError("Truncated GLB header")
            magic, version, size = struct.unpack("<III", header)
            if magic != 0x46546C67 or version != 2 or size != source.stat().st_size:
                raise ValueError("Invalid GLB 2.0 header or length")
            chunk = stream.read(8)
            if len(chunk) != 8:
                raise ValueError("Missing GLB JSON chunk")
            count, kind = struct.unpack("<II", chunk)
            if kind != 0x4E4F534A or count > size - 20:
                raise ValueError("Invalid GLB JSON chunk")
            document = json.loads(stream.read(count).rstrip(b" \x00"))
    else:
        document = json.loads(source.read_text(encoding="utf-8-sig"))
    if document.get("asset", {}).get("version") != "2.0":
        raise ValueError("Only glTF 2.0 material inspection is supported")
    textures, images = document.get("textures", []), document.get("images", [])

    def texture(info, components):
        if not info:
            return None
        index = info["index"]
        tex = textures[index]
        image_index = tex.get("source")
        if image_index is None:
            raise ValueError("Unsupported extension-only glTF texture source")
        image = images[image_index]
        return {"texture_index": index, "image_index": image_index,
                "image_name": image.get("name"), "image_uri": image.get("uri", "<embedded bufferView>"),
                "components": components, "texcoord": info.get("texCoord", 0),
                "extensions": info.get("extensions", {})}

    used = sorted({p["material"] for m in document.get("meshes", []) for p in m.get("primitives", []) if "material" in p})
    primitive_geometry = []
    for mesh_index, mesh in enumerate(document.get("meshes", [])):
        for primitive_index, primitive in enumerate(mesh.get("primitives", [])):
            attributes = primitive.get("attributes", {})
            index_count = document["accessors"][primitive["indices"]]["count"] if "indices" in primitive else document["accessors"][attributes["POSITION"]]["count"]
            primitive_geometry.append({"mesh_index": mesh_index, "primitive_index": primitive_index,
                                       "mode": primitive.get("mode", 4), "index_count": index_count,
                                       "triangles": index_count // 3 if primitive.get("mode", 4) == 4 else None,
                                       "has_normals": "NORMAL" in attributes, "has_tangents": "TANGENT" in attributes})
    materials = []
    for index in used:
        mat = document["materials"][index]
        pbr = mat.get("pbrMetallicRoughness", {})
        mr = pbr.get("metallicRoughnessTexture")
        materials.append({"index": index, "name": mat.get("name", ""),
                          "double_sided": mat.get("doubleSided", False), "alpha_mode": mat.get("alphaMode", "OPAQUE"),
                          "extensions": sorted(mat.get("extensions", {})),
                          "channels": {
                              "base_color": {"texture": texture(pbr.get("baseColorTexture"), "RGB"), "factor": pbr.get("baseColorFactor", [1, 1, 1, 1])},
                              "roughness": {"texture": texture(mr, "G"), "factor": pbr.get("roughnessFactor", 1)},
                              "metallic": {"texture": texture(mr, "B"), "factor": pbr.get("metallicFactor", 1)},
                              "normal": {"texture": texture(mat.get("normalTexture"), "RGB tangent-space"), "scale": mat.get("normalTexture", {}).get("scale", 1)},
                          }})
    return {"available": True, "source": str(source), "materials": materials,
            "image_count": len(images), "texture_count": len(textures),
            "geometry": {"primitives": primitive_geometry,
                         "mesh_count": len(document.get("meshes", [])),
                         "mesh_node_count": sum("mesh" in n for n in document.get("nodes", [])),
                         "unique_mesh_triangles": sum(p["triangles"] for p in primitive_geometry) if all(p["triangles"] is not None for p in primitive_geometry) else None},
            "extensions_required": document.get("extensionsRequired", [])}


def path(obj):
    return obj.get_path_name() if obj else None


def prop(obj, name, default=None):
    try:
        return obj.get_editor_property(name)
    except Exception:
        return default


def norm(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def value_json(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "r"):
        return [float(value.r), float(value.g), float(value.b), float(value.a)]
    if hasattr(value, "get_path_name"):
        return path(value)
    return str(value)


def material_chain(unreal, material):
    result, seen = [], set()
    while material and path(material) not in seen:
        seen.add(path(material))
        result.append(material)
        if isinstance(material, unreal.Material):
            return result
        material = prop(material, "parent")
    raise ValueError("Material parent chain has no base Material")


def ensure_ism(unreal, material, repair=False):
    """Repair base first, then only an explicit false MI override if still needed."""
    lib = unreal.MaterialEditingLibrary
    usage = unreal.MaterialUsage.MATUSAGE_INSTANCED_STATIC_MESHES
    rows = []
    for obj in reversed(material_chain(unreal, material)):
        before = bool(lib.has_material_usage(obj, usage))
        row = {"path": path(obj), "class": obj.get_class().get_name(), "before": before, "changed": False}
        if not before and repair:
            if not path(obj).startswith("/Game/"):
                row["repair_error"] = "external_parent_not_modified"
            else:
                if isinstance(obj, unreal.Material):
                    lib.set_base_material_usage(obj, usage, True)
                elif isinstance(obj, unreal.MaterialInstanceConstant):
                    lib.set_material_usage_override(obj, usage, True, True)
                else:
                    raise ValueError("Unsupported material instance class for usage repair")
                row["changed"] = True
                row["saved"] = bool(unreal.EditorAssetLibrary.save_loaded_asset(obj, only_if_is_dirty=False))
                if not row["saved"]:
                    row["repair_error"] = "material_save_failed"
        row["after"] = bool(lib.has_material_usage(obj, usage))
        rows.append(row)
    return rows


def parameters(unreal, material, base):
    lib = unreal.MaterialEditingLibrary
    instance = isinstance(material, unreal.MaterialInstanceConstant)
    result = {}
    for kind in ("texture", "scalar", "vector", "static_switch"):
        names = getattr(lib, "get_" + kind + "_parameter_names")(material)
        getter = getattr(lib, "get_material_" + ("instance_" if instance else "default_") + kind + "_parameter_value")
        result[kind] = {str(name): getter(material if instance else base, name) for name in names}
    return result


def texture_info(texture):
    result = {"path": path(texture), "class": texture.get_class().get_name(),
              "srgb": prop(texture, "srgb"), "compression_settings": str(prop(texture, "compression_settings")),
              "flip_green_channel": prop(texture, "flip_green_channel")}
    try:
        result["dimensions"] = [texture.blueprint_get_size_x(), texture.blueprint_get_size_y()]
    except Exception as exc:
        result["dimensions_unavailable"] = str(exc)
    return result


def inspect_material(unreal, material, expected=None, repair=False):
    lib = unreal.MaterialEditingLibrary
    chain = material_chain(unreal, material)
    base = chain[-1]
    usage = ensure_ism(unreal, material, repair)
    params = parameters(unreal, material, base)
    warnings = []
    if any(not r["after"] or r.get("repair_error") for r in usage):
        warnings.append("ism_usage_not_persisted_on_entire_parent_chain")
    used_textures = {path(t): t for t in lib.get_material_used_textures(material) if t}
    all_textures = dict(used_textures)

    def inputs(node):
        names = list(lib.get_material_expression_input_names(node))
        nodes = list(lib.get_inputs_for_material_expression(base, node))
        if len(names) != len(nodes):
            raise ValueError("Expression input names/nodes count mismatch")
        return list(zip(map(str, names), nodes))

    def describe(node):
        data = {"path": path(node), "class": node.get_class().get_name()}
        for key in ("parameter_name", "constant", "r", "g", "b", "a", "default_value", "value"):
            item = prop(node, key)
            if item is not None:
                data[key] = value_json(item)
        return data

    def constant_value(node):
        if not node:
            return None
        pname = str(prop(node, "parameter_name", ""))
        for kind in ("scalar", "vector", "static_switch"):
            if pname in params[kind]:
                return value_json(params[kind][pname])
        cls = node.get_class().get_name()
        if cls in {"MaterialExpressionConstant3Vector", "MaterialExpressionConstant4Vector"}:
            return value_json(prop(node, "constant"))
        if cls == "MaterialExpressionConstant":
            return prop(node, "r")
        if cls in {"MaterialExpressionStaticBool", "MaterialExpressionStaticBoolParameter"}:
            return prop(node, "value", prop(node, "default_value"))
        return None

    def trace(node, visited=None):
        visited = set() if visited is None else visited
        if not node or path(node) in visited:
            return {"textures": [], "nodes": [], "unresolved": []}
        visited.add(path(node))
        cls = node.get_class().get_name()
        out = {"textures": [], "nodes": [describe(node)], "unresolved": []}
        tex = prop(node, "texture")
        pname = str(prop(node, "parameter_name", ""))
        if pname in params["texture"]:
            tex = params["texture"][pname]
        if tex:
            all_textures[path(tex)] = tex
            out["textures"].append(path(tex))
        if "MaterialFunctionCall" in cls:
            # Never infer a particular output from every input of an opaque function.
            out["unresolved"].append("nested_function:" + str(path(prop(node, "material_function"))))
            return out
        edges = inputs(node)
        if "StaticSwitchParameter" in cls:
            selected = params["static_switch"].get(pname, prop(node, "default_value"))
            edges = [(name, child) for name, child in edges if norm(name) == ("a" if selected else "b")]
        for name, child in edges:
            if not child:
                continue
            part = trace(child, visited)
            out["nodes"].extend(part["nodes"])
            out["textures"].extend(part["textures"])
            out["unresolved"].extend(part["unresolved"])
        out["textures"] = sorted(set(out["textures"]))
        return out

    channels = {}
    for channel, (enum_name, output_name, texture_input, enable_input) in CHANNELS.items():
        enum_value = getattr(unreal.MaterialProperty, enum_name)
        node = lib.get_material_property_input_node(base, enum_value)
        entry = {"connected": bool(node), "root": describe(node) if node else None,
                 "source_expected": expected["channels"][channel] if expected else None,
                 "textures": [], "method": "direct_expression_graph", "issues": []}
        if node:
            output = lib.get_material_property_input_node_output_name(base, enum_value)
            entry["root_output"] = str(output)
            function = prop(node, "material_function")
            if function and path(function) in NATIVE_GLTF_FUNCTIONS:
                entry["method"] = "ue58_native_gltf_function_binding"
                entry["native_function"] = path(function)
                bindings = {norm(name): (name, child) for name, child in inputs(node)}
                entry["function_input_names"] = [name for name, _ in bindings.values()]
                entry["output_matches_channel"] = norm(output) == norm(output_name)
                if not entry["output_matches_channel"]:
                    entry["issues"].append("native_function_wrong_output")
                tex_node = bindings.get(norm(texture_input), (None, None))[1]
                traced = trace(tex_node)
                entry.update(textures=traced["textures"], texture_branch=traced)
                if traced["unresolved"]:
                    entry["issues"].append("texture_branch_unresolved")
                enabled = bindings.get(norm(enable_input), (None, None))[1]
                if enabled:
                    flag_name = str(prop(enabled, "parameter_name", ""))
                    flag = params["static_switch"].get(flag_name, prop(enabled, "value", prop(enabled, "default_value")))
                    entry["texture_enabled"] = value_json(flag)
                    if flag is False and expected and expected["channels"][channel]["texture"]:
                        entry["issues"].append("source_texture_disabled_by_switch")
                elif enable_input in params["static_switch"]:
                    entry["texture_enabled"] = params["static_switch"][enable_input]
                    if not entry["texture_enabled"] and expected and expected["channels"][channel]["texture"]:
                        entry["issues"].append("source_texture_disabled_by_switch")
                factor_name = {"base_color": "BaseColorFactor_RGB", "metallic": "MetallicFactor", "roughness": "RoughnessFactor", "normal": "NormalScale"}[channel]
                factor = bindings.get(norm(factor_name), (None, None))[1]
                entry["factor_branch"] = trace(factor) if factor else {"native_default": True}
                effective = constant_value(factor) if factor else ([1, 1, 1] if channel == "base_color" else 1)
                entry["effective_factor_or_scale"] = effective
                if expected:
                    source_value = expected["channels"][channel].get("factor", expected["channels"][channel].get("scale"))
                    observed = effective[:3] if isinstance(effective, list) and channel == "base_color" else [effective]
                    wanted = source_value[:3] if isinstance(source_value, list) and channel == "base_color" else [source_value]
                    if effective is None:
                        entry["issues"].append("source_factor_comparison_unavailable")
                    elif len(observed) != len(wanted) or any(abs(float(a) - float(b)) > 0.0001 for a, b in zip(observed, wanted)):
                        entry["issues"].append("source_factor_changed")
                entry["packed_component_contract"] = {"roughness": "G", "metallic": "B"}.get(channel, "RGB")
            else:
                traced = trace(node)
                entry.update(textures=traced["textures"], graph=traced)
                if traced["unresolved"]:
                    entry["issues"].append("function_graph_requires_manual_review")
            for tex_path in entry["textures"]:
                texture = all_textures[tex_path]
                srgb = prop(texture, "srgb")
                if srgb is None:
                    entry["issues"].append("texture_srgb_unavailable")
                elif channel == "base_color" and not srgb:
                    entry["issues"].append("base_color_texture_not_srgb")
                elif channel != "base_color" and srgb:
                    entry["issues"].append("data_texture_incorrectly_srgb")
                if channel == "normal" and "NORMALMAP" not in str(prop(texture, "compression_settings")).upper():
                    entry["issues"].append("normal_texture_not_normalmap_compression")
                if not tex_path.startswith("/Game/"):
                    entry["issues"].append("texture_is_engine_or_plugin_default")
            if expected and expected["channels"][channel]["texture"] and not entry["textures"]:
                entry["issues"].append("source_texture_missing_from_channel")
        elif expected and expected["channels"][channel]["texture"]:
            entry["issues"].append("source_textured_channel_disconnected")
        if entry["issues"]:
            warnings.extend(channel + ":" + issue for issue in sorted(set(entry["issues"])))
        channels[channel] = entry
    # Separate source images must not silently collapse to one texture binding.
    if expected:
        if bool(prop(base, "two_sided")) != expected["double_sided"]:
            warnings.append("source_double_sided_changed")
        if expected["alpha_mode"] != "OPAQUE":
            warnings.append("source_alpha_mode_requires_visual_review")
        for first, second in (("base_color", "roughness"), ("base_color", "normal"), ("roughness", "normal")):
            a, b = expected["channels"][first]["texture"], expected["channels"][second]["texture"]
            if a and b and a["image_index"] != b["image_index"] and set(channels[first]["textures"]) & set(channels[second]["textures"]):
                warnings.append(first + "_and_" + second + "_unexpectedly_share_texture")
        if expected["extensions"]:
            warnings.append("source_material_extensions_require_review")
    result = {"path": path(material), "base_material": path(base), "class": material.get_class().get_name(),
              "two_sided": prop(base, "two_sided"), "blend_mode": str(prop(base, "blend_mode")),
              "parent_chain_ism": usage, "channels": channels,
              "parameters": {k: {n: value_json(v) for n, v in values.items()} for k, values in params.items()},
              "textures": [texture_info(t) for _, t in sorted(all_textures.items())],
              "compiled_used_texture_paths": sorted(used_textures), "warnings": sorted(set(warnings)),
              "compiled_texture_evidence": "available" if used_textures else "not_available_in_this_execution",
              "source_material": expected,
              "status": "requires_review" if warnings else "structural_checks_passed",
              "limits": "Checks graph bindings, native GLTF channel contract, color space and ISM flags; not a rendered appearance, shader-error, or pixel-equivalence acceptance."}
    return result


def validate_material_overrides(overrides):
    if not isinstance(overrides, dict) or set(overrides) - {"Metallic"}:
        raise ValueError("Only explicit Metallic factor overrides are supported")
    for value in overrides.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Material factor must be finite and between zero and one")
    return dict(overrides)


def apply_material_overrides(unreal, meshes, overrides, destination):
    overrides = validate_material_overrides(overrides)
    if not overrides:
        return []
    lib = unreal.MaterialEditingLibrary
    materials = {}
    for mesh in meshes:
        field = "static_materials" if isinstance(mesh, unreal.StaticMesh) else "materials"
        for slot in mesh.get_editor_property(field):
            base = material_chain(unreal, slot.material_interface)[-1]
            materials[path(base)] = base
    rows = []
    for material_path, base in sorted(materials.items()):
        if not material_path.startswith(destination + "/"):
            raise ValueError("Material override may only edit this isolated import")
        node = lib.get_material_property_input_node(base, unreal.MaterialProperty.MP_METALLIC)
        function = prop(node, "material_function")
        if path(function) not in NATIVE_GLTF_FUNCTIONS:
            raise ValueError("Unexpected GLTF material graph; do not replace it")
        names = list(map(str, lib.get_material_expression_input_names(node)))
        children = list(lib.get_inputs_for_material_expression(base, node))
        if len(names) != len(children) or "MetallicFactor" not in names:
            raise ValueError("Missing native MetallicFactor binding")
        factor = children[names.index("MetallicFactor")]
        if factor and factor.get_class().get_name() != "MaterialExpressionConstant":
            raise ValueError("Existing nonconstant metallic factor requires review")
        before = prop(factor, "r", 1.0)
        if not factor:
            factor = lib.create_material_expression(base, unreal.MaterialExpressionConstant)
        factor.set_editor_property("r", float(overrides["Metallic"]))
        if not lib.connect_material_expressions(factor, "", node, "MetallicFactor"):
            raise ValueError("MetallicFactor connection failed")
        errors = list(lib.recompile_material(base))
        if errors:
            raise ValueError("Material compile errors: " + str(errors))
        if not unreal.EditorAssetLibrary.save_loaded_asset(base, only_if_is_dirty=False):
            raise ValueError("Could not save isolated material correction")
        rows.append({"material": material_path, "factor": "MetallicFactor", "before": before,
                     "after": prop(factor, "r"), "source_textures_preserved": True})
    if not rows:
        raise ValueError("No materials received the required override")
    return rows


def audit_meshes(unreal, meshes, source=None, repair=False, overrides=None):
    overrides = validate_material_overrides(overrides or {})
    source_info = source_materials(source) if source else {"available": False, "materials": [], "reason": "no_source_given"}
    assigned, slots, warnings = {}, [], []
    for mesh in meshes:
        field = "static_materials" if isinstance(mesh, unreal.StaticMesh) else "materials"
        for slot in mesh.get_editor_property(field):
            material = slot.material_interface
            slots.append({"mesh": path(mesh), "slot": str(slot.material_slot_name), "material": path(material)})
            if material:
                assigned[path(material)] = material
            else:
                warnings.append("missing_material_assignment")
    reports = []
    matched_indices = set()
    for mat_path, material in sorted(assigned.items()):
        candidates = [s for s in source_info["materials"] if norm(s["name"]) and norm(s["name"]) in {norm(material.get_name()), norm(material.get_name().removeprefix("M_").removeprefix("MI_"))}]
        if len(source_info["materials"]) == 1 and len(assigned) == 1:
            candidates = source_info["materials"]
        expected = candidates[0] if len(candidates) == 1 else None
        if expected:
            matched_indices.add(expected["index"])
            expected = json.loads(json.dumps(expected))
            if "Metallic" in overrides:
                expected["channels"]["metallic"]["original_source_factor"] = expected["channels"]["metallic"]["factor"]
                expected["channels"]["metallic"]["factor"] = overrides["Metallic"]
        elif source_info["available"]:
            warnings.append("source_to_ue_material_mapping_unverified:" + mat_path)
        try:
            row = inspect_material(unreal, material, expected, repair)
        except Exception as exc:
            row = {"path": mat_path, "status": "inspection_failed", "warnings": [str(exc)]}
        reports.append(row)
        warnings.extend(mat_path + ":" + w for w in row["warnings"])
    if source_info["available"] and matched_indices != {s["index"] for s in source_info["materials"]}:
        warnings.append("not_all_source_materials_matched")
    if not assigned:
        warnings.append("no_assigned_materials")
    return {"audit_version": AUDIT_VERSION, "source_materials": source_info, "declared_runtime_overrides": overrides, "slots": slots, "materials": reports,
            "warnings": sorted(set(warnings)), "status": "requires_review" if warnings else "structural_checks_passed",
            "production_approved": False, "visual_review_required": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-report", default=os.environ.get("CIVWAR_MATERIAL_IMPORT_REPORT"))
    parser.add_argument("--assets", default=os.environ.get("CIVWAR_MATERIAL_ASSETS"))
    parser.add_argument("--repair-ism", action="store_true", default=os.environ.get("CIVWAR_MATERIAL_REPAIR") == "1")
    parser.add_argument("--report", default=os.environ.get("CIVWAR_MATERIAL_REPORT", str(ROOT / "Saved/ArtMaterials/material_audit.json")))
    args, _ = parser.parse_known_args()
    import unreal
    records = []
    if args.import_report:
        imported = json.loads(Path(args.import_report).read_text(encoding="utf-8-sig"))
        for item in imported["results"]:
            mesh_paths = [a["path"] for a in item.get("assets", []) if a.get("type") in {"static_mesh", "skeletal_mesh"}]
            meshes = [unreal.EditorAssetLibrary.load_asset(p) for p in mesh_paths]
            if meshes and all(meshes):
                records.append({"id": item["id"], "audit": audit_meshes(unreal, meshes, item.get("source"), args.repair_ism, item.get("runtime_material_overrides"))})
            else:
                records.append({"id": item["id"], "error": "no_loadable_meshes"})
    else:
        if args.assets:
            asset_paths = [p.strip() for p in args.assets.split(";") if p.strip()]
        else:
            mapping = json.loads((ROOT / "Content/Data/EnvironmentArt.json").read_text(encoding="utf-8-sig"))
            asset_paths = [a["object_path"] for a in mapping["assets"].values()] + ["/Game/Art/M_CWStylized"]
        for asset_path in asset_paths:
            obj = unreal.EditorAssetLibrary.load_asset(asset_path)
            try:
                if isinstance(obj, (unreal.StaticMesh, unreal.SkeletalMesh)):
                    records.append({"path": asset_path, "audit": audit_meshes(unreal, [obj], repair=args.repair_ism)})
                elif obj:
                    records.append({"path": asset_path, "material": inspect_material(unreal, obj, repair=args.repair_ism)})
                else:
                    records.append({"path": asset_path, "error": "asset_not_found"})
            except Exception as exc:
                records.append({"path": asset_path, "error": str(exc)})
    report = {"schema_version": 1, "audit_version": AUDIT_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
              "repair_ism": args.repair_ism, "production_approved": False, "results": records}
    report["requires_review"] = sum(bool(r.get("error") or r.get("audit", r.get("material", {})).get("warnings")) for r in records)
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    unreal.log("[ArtMaterials] report=" + str(target) + " requires_review=" + str(report["requires_review"]))


if __name__ == "__main__":
    main()
