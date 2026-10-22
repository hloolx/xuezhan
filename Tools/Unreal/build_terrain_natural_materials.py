"""Create isolated runtime terrain materials from the existing Tripo 4K textures.

Run with the project Unreal Python commandlet. No source material, texture, mesh,
runtime config or gameplay package is edited. A report is always written to
RawAssets/Art/Tripo_v01/reviews/VisualPolish_20261021/terrain_materials.json.
Set CIVWAR_TERRAIN_MATERIAL_STAGE=fresh for a read-only package/graph audit.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import traceback

import unreal as u

ROOT = Path(u.Paths.convert_relative_path_to_full(u.Paths.project_dir()))
REPORT = ROOT / "RawAssets/Art/Tripo_v01/reviews/VisualPolish_20261021/terrain_materials.json"
FOLDER = "/Game/Art/TerrainNatural_v01"
SOURCE_FOLDER = "/Game/ArtPilot/EraAssets/Env_BattlefieldTile/h71618334c75e6209/Materials"
SOURCE = SOURCE_FOLDER + "/M_Source_000_Blue"
TEXTURES = {name: SOURCE_FOLDER + "/Textures/T_M_Source_000_" + name
            for name in ("base_color", "metallic_roughness", "normal")}
ATLAS_SELECTION = {
    "evidence": "Visually inspected the actual 4096x4096 source base_color.jpg; rectangles are inside the upper grass island and the left upper road-sand island",
    "source_file": "RawAssets/Art/Tripo_v01/tripo_processed/era_assets_v01/Env_BattlefieldTile/h3b78a0c04f3b4dbd/materials/m000/base_color.jpg",
    "source_sha256": "f664772406888e3ec805d559cd18cce4e0fc98baffde936d6bf72d2e2ae25ea5",
    "grass_uv_min": [.575, .012], "grass_uv_max": [.630, .072],
    "grass_pixels_4096": [2355, 49, 2580, 295],
    "sand_uv_min": [.278, .020], "sand_uv_max": [.313, .125],
    "sand_pixels_4096": [1139, 82, 1282, 512],
}
LIB = u.MaterialEditingLibrary
ASSETS = u.EditorAssetLibrary

# These small rectangles lie wholly inside existing grass and sand UV islands.
# Mirrored sampling keeps their borders continuous. Two world scales and a
# subdued irregular macro tint remove a visible grid without new image files.
MEADOW_CODE = r"""
float2 p = World.xy;
float2 a = 1.0 - abs(frac((p + float2(71, 139)) / 290.0) * 2.0 - 1.0);
float2 q = float2(p.x * 0.80 + p.y * 0.60, -p.x * 0.60 + p.y * 0.80);
float2 b = 1.0 - abs(frac((q + float2(413, 271)) / 470.0) * 2.0 - 1.0);
float3 g1 = Texture2DSample(Atlas, AtlasSampler, float2(0.575, 0.012) + a * float2(0.055, 0.060)).rgb;
float3 g2 = Texture2DSample(Atlas, AtlasSampler, float2(0.575, 0.012) + b * float2(0.055, 0.060)).rgb;
float3 s1 = Texture2DSample(Atlas, AtlasSampler, float2(0.278, 0.020) + a * float2(0.035, 0.105)).rgb;
float3 s2 = Texture2DSample(Atlas, AtlasSampler, float2(0.278, 0.020) + b * float2(0.035, 0.105)).rgb;
float macro = sin(p.x * 0.0011 + sin(p.y * 0.0018) * 1.7) * 0.035;
macro += sin(p.y * 0.0023 - p.x * 0.0007 + 2.4) * 0.025;
float3 grass = lerp(g1, g2, 0.42) * float3(0.94, 0.97, 0.88) * (0.97 + macro);
float3 sand = lerp(s1, s2, 0.42) * (0.97 + macro * 0.5);
float verge = smoothstep(360.0, 650.0, abs(p.y));
float farTint = lerp(1.0, 0.80, smoothstep(1500.0, 6500.0, abs(p.y)));
return lerp(sand, grass, verge) * farTint;
"""

# All endpoints agree exactly at |Y|=1200. The noise shifts only the inner
# boundary, so it cannot leave tiny pieces of the original rectangular rim.
# Raised Tripo rocks keep their own original surface and normals.
EDGE_CODE = r"""
float n = sin(World.x * 0.0061 + sin(World.x * 0.0017) * 2.1) * 45.0;
n += sin(World.x * 0.0137 + 1.9) * 16.0;
float edge = smoothstep(860.0 + n, 1195.0, abs(World.y));
float low = 1.0 - smoothstep(25.0, 70.0, World.z);
return edge * low;
"""

TILE_MACRO_CODE = r"""
float v = sin(World.x * 0.0011 + sin(World.y * 0.0018) * 1.7) * 0.025;
v += sin(World.y * 0.0023 - World.x * 0.0007 + 2.4) * 0.015;
return Original * (0.98 + v);
"""


def disk_record(asset_path):
    path = ROOT / "Content" / (asset_path.removeprefix("/Game/") + ".uasset")
    return {"asset": asset_path, "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size}


def node(material, cls, **props):
    result = LIB.create_material_expression(material, cls)
    if result is None:
        raise RuntimeError("Could not create " + str(cls))
    for key, value in props.items():
        result.set_editor_property(key, value)
    return result


def connect(source, target, name):
    if not LIB.connect_material_expressions(source[0], source[1], target, name):
        raise RuntimeError("Could not connect material input " + name)


def output(source, prop):
    if not LIB.connect_material_property(source[0], source[1], prop):
        raise RuntimeError("Could not connect material property " + str(prop))


def custom(material, code, inputs, output_type):
    custom_inputs = []
    for name, _ in inputs:
        custom_input = u.CustomInput()
        custom_input.set_editor_property("input_name", name)
        custom_inputs.append(custom_input)
    result = node(material, u.MaterialExpressionCustom, code=code, output_type=output_type,
                  inputs=custom_inputs)
    for name, source in inputs:
        connect(source, result, name)
    return result, ""


def constant(material, value):
    return node(material, u.MaterialExpressionConstant, r=float(value)), ""


def operation(material, cls, pairs):
    result = node(material, cls)
    for name, source in pairs:
        connect(source, result, name)
    return result, ""


def meadow(material, textures):
    world = node(material, u.MaterialExpressionWorldPosition), ""
    atlas = node(material, u.MaterialExpressionTextureObject, texture=textures["base_color"]), ""
    color = custom(material, MEADOW_CODE, [("World", world), ("Atlas", atlas)],
                   u.CustomMaterialOutputType.CMOT_FLOAT3)
    return world, color


def material(name, textures, tile):
    path = FOLDER + "/" + name
    existing = ASSETS.load_asset(path) if ASSETS.does_asset_exist(path) else None
    if existing is not None:
        # Re-running initial is deliberately idempotent. Iterations must use a
        # new version folder, rather than quietly replacing a reviewed asset.
        return existing
    result = u.AssetToolsHelpers.get_asset_tools().create_asset(name, FOLDER, u.Material, u.MaterialFactoryNew())
    if result is None:
        raise RuntimeError("Could not create " + path)
    # Preserve the accepted source tile's culling contract rather than forcing
    # a new default. Its profiled GLB contains 345 triangles whose winding is
    # opposed to authored normals, so disabling source two-sided visibility
    # without reworking the mesh can reveal holes. The generated landscape
    # uses exactly one triangle set per cell and is explicitly two-sided.
    source_two_sided = bool(ASSETS.load_asset(SOURCE).get_editor_property("two_sided"))
    result.set_editor_property("two_sided", source_two_sided if tile else True)
    world, grass = meadow(result, textures)
    if tile:
        sample_nodes = {}
        for channel, texture in textures.items():
            sampler = (u.MaterialSamplerType.SAMPLERTYPE_COLOR if channel == "base_color" else
                       u.MaterialSamplerType.SAMPLERTYPE_NORMAL if channel == "normal" else
                       u.MaterialSamplerType.SAMPLERTYPE_MASKS)
            sample_nodes[channel] = node(result, u.MaterialExpressionTextureSample,
                                         texture=texture, sampler_type=sampler)
        edge = custom(result, EDGE_CODE, [("World", world)], u.CustomMaterialOutputType.CMOT_FLOAT1)
        original = custom(result, TILE_MACRO_CODE,
                          [("World", world), ("Original", (sample_nodes["base_color"], "RGB"))],
                          u.CustomMaterialOutputType.CMOT_FLOAT3)
        base = operation(result, u.MaterialExpressionLinearInterpolate,
                         [("A", original), ("B", grass), ("Alpha", edge)])
        flat_normal = node(result, u.MaterialExpressionConstant3Vector, constant=u.LinearColor(0, 0, 1, 1)), ""
        normal = operation(result, u.MaterialExpressionLinearInterpolate,
                           [("A", (sample_nodes["normal"], "RGB")), ("B", flat_normal), ("Alpha", edge)])
        normalized = operation(result, u.MaterialExpressionNormalize, [("VectorInput", normal)])
        roughness = operation(result, u.MaterialExpressionLinearInterpolate,
                              [("A", (sample_nodes["metallic_roughness"], "G")),
                               ("B", constant(result, .94)), ("Alpha", edge)])
        metallic = operation(result, u.MaterialExpressionLinearInterpolate,
                             [("A", (sample_nodes["metallic_roughness"], "B")),
                              ("B", constant(result, 0)), ("Alpha", edge)])
        output(normalized, u.MaterialProperty.MP_NORMAL)
        output(metallic, u.MaterialProperty.MP_METALLIC)
    else:
        base = grass
        roughness = constant(result, .94)
        output(constant(result, 0), u.MaterialProperty.MP_METALLIC)
    output(base, u.MaterialProperty.MP_BASE_COLOR)
    output(roughness, u.MaterialProperty.MP_ROUGHNESS)
    LIB.layout_material_expressions(result)
    LIB.recompile_material(result)
    if not ASSETS.save_loaded_asset(result, only_if_is_dirty=False):
        raise RuntimeError("Could not save " + path)
    return result


def audit(material, tile):
    required = [u.MaterialProperty.MP_BASE_COLOR, u.MaterialProperty.MP_ROUGHNESS, u.MaterialProperty.MP_METALLIC]
    if tile:
        required.append(u.MaterialProperty.MP_NORMAL)
    for prop in required:
        if LIB.get_material_property_input_node(material, prop) is None:
            raise RuntimeError("Missing graph output: " + str(prop))
    source_two_sided = bool(ASSETS.load_asset(SOURCE).get_editor_property("two_sided"))
    if material.get_editor_property("two_sided") != (source_two_sided if tile else True):
        raise RuntimeError("Unexpected material culling: " + material.get_path_name())
    return {"path": material.get_path_name(), "required_outputs": [str(prop) for prop in required],
            "two_sided": material.get_editor_property("two_sided"),
            "note": "Graph/package audit; root must check actual game shader logs and screenshots"}


def main():
    stage = os.environ.get("CIVWAR_TERRAIN_MATERIAL_STAGE", "initial")
    if stage not in {"initial", "fresh"}:
        raise RuntimeError("Expected initial or fresh")
    # Hash the entire source mesh/material/texture folder, not just textures.
    protected_dir = ROOT / "Content/ArtPilot/EraAssets/Env_BattlefieldTile/h71618334c75e6209"
    protected_before = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in protected_dir.rglob("*.uasset")}
    atlas_path = ROOT / ATLAS_SELECTION["source_file"]
    if hashlib.sha256(atlas_path.read_bytes()).hexdigest() != ATLAS_SELECTION["source_sha256"]:
        raise RuntimeError("Visually inspected atlas source changed")
    textures = {key: ASSETS.load_asset(path) for key, path in TEXTURES.items()}
    if not ASSETS.does_asset_exist(SOURCE) or any(value is None for value in textures.values()):
        raise RuntimeError("Existing terrain PBR assets missing")
    materials = []
    for name, tile in (("M_TileNatural", True), ("M_LandscapeNatural", False)):
        if stage == "fresh":
            result = ASSETS.load_asset(FOLDER + "/" + name)
            if result is None:
                raise RuntimeError("Missing generated material: " + name)
        else:
            result = material(name, textures, tile)
        materials.append(audit(result, tile))
    protected_after = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in protected_dir.rglob("*.uasset")}
    if protected_before != protected_after:
        raise RuntimeError("Protected terrain source packages changed")
    report = {"schema_version": 1, "stage": stage, "status": "materials_saved_pending_actual_game",
              "source_material": SOURCE, "source_textures": TEXTURES, "materials": materials,
              "atlas_uv_selection": ATLAS_SELECTION,
              "tile_culling": "Preserves the original tile material flag; generated landscape has one triangle set and two-sided visibility",
              "packages": [disk_record(FOLDER + "/" + name)
                           for name in ("M_TileNatural", "M_LandscapeNatural")],
              "protected_source_packages": protected_before,
              "protected_source_unchanged": True, "new_textures": 0, "mesh_edits": 0,
              "failures": [], "remaining": ["actual_shader_compile_log", "actual_game_both_sides"]}
    path = REPORT.with_name("terrain_materials_fresh.json") if stage == "fresh" else REPORT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    u.log("CIVWAR_NATURAL_TERRAIN_MATERIALS report=" + str(path))


try:
    main()
except Exception:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    failure = REPORT.with_name("terrain_materials_failed.json")
    if failure.exists():
        index = 2
        while REPORT.with_name("terrain_materials_failed_%02d.json" % index).exists():
            index += 1
        failure = REPORT.with_name("terrain_materials_failed_%02d.json" % index)
    failure.write_text(json.dumps({"status": "failed", "traceback": traceback.format_exc(),
                                    "partial_assets_are_not_approved": True}, indent=2), encoding="utf-8")
    raise
