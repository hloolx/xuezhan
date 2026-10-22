"""Batch-import prepared static era assets; no C++/runtime/config writes.

In a root-leased NullRHI Unreal Python commandlet, set CIVWAR_ERA_IMPORT_PLAN
to a JSON {entries:[{manifest, report}]} and optional CIVWAR_ERA_IMPORT_STAGE
to initial (default) or fresh. Initial writes isolated source-fingerprinted
packages. Fresh reads and checks those same packages without saving them.
run(unreal, manifest_path, report_path) is also reusable by a larger batch.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import traceback

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve(path):
    path = Path(path)
    return path.resolve() if path.is_absolute() else (ROOT/path).resolve()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def properties(obj, values):
    for key, value in values.items():
        obj.set_editor_property(key, value)


def import_asset(u, path, destination, name, options=None, factory=None):
    target = destination + "/" + name
    existing = u.EditorAssetLibrary.load_asset(target) if u.EditorAssetLibrary.does_asset_exist(target) else None
    if existing is not None:
        return existing
    task = u.AssetImportTask()
    properties(task, {"filename": str(path), "destination_path": destination,
                      "destination_name": name, "automated": True,
                      "save": True, "replace_existing": False, "async_": False})
    if options is not None:
        task.set_editor_property("options", options)
    if factory is not None:
        task.set_editor_property("factory", factory)
    u.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    result = u.EditorAssetLibrary.load_asset(target)
    if result is None:
        raise RuntimeError("Import did not create " + target)
    return result


def static_options(u):
    options = u.FbxImportUI()
    properties(options, {"automated_import_should_detect_type": False,
                         "import_mesh": True, "import_as_skeletal": False,
                         "import_animations": False, "import_materials": False,
                         "import_textures": False, "mesh_type_to_import": u.FBXImportType.FBXIT_STATIC_MESH})
    properties(options.get_editor_property("static_mesh_import_data"), {
        "import_uniform_scale": 1., "convert_scene": True, "convert_scene_unit": True,
        "force_front_x_axis": False, "combine_meshes": True,
        "auto_generate_collision": False, "generate_lightmap_u_vs": False,
        "transform_vertex_to_absolute": True, "bake_pivot_in_vertex": False,
        "normal_import_method": u.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS})
    return options


def material(u, row, destination, red=False):
    lib = u.MaterialEditingLibrary
    name = row["slot_name"] + ("_Red" if red else "_Blue")
    target = destination + "/" + name
    existing = u.EditorAssetLibrary.load_asset(target) if u.EditorAssetLibrary.does_asset_exist(target) else None
    if existing is not None:
        usage = u.MaterialUsage.MATUSAGE_INSTANCED_STATIC_MESHES
        if not lib.has_material_usage(existing, usage):
            lib.set_base_material_usage(existing, usage, True)
            lib.recompile_material(existing)
            if not u.EditorAssetLibrary.save_loaded_asset(existing, only_if_is_dirty=False):
                raise RuntimeError("Could not save instancing support: " + target)
        return existing
    result = u.AssetToolsHelpers.get_asset_tools().create_asset(name, destination, u.Material, u.MaterialFactoryNew())
    result.set_editor_property("two_sided", row["double_sided"])
    lib.set_base_material_usage(result, u.MaterialUsage.MATUSAGE_INSTANCED_STATIC_MESHES, True)

    def scalar(value):
        node = lib.create_material_expression(result, u.MaterialExpressionConstant)
        node.set_editor_property("r", float(value))
        return node, ""

    def vector(values):
        node = lib.create_material_expression(result, u.MaterialExpressionConstant3Vector)
        node.set_editor_property("constant", u.LinearColor(*values[:3], 1))
        return node, ""

    def operation(cls, a, b, a_pin="A", b_pin="B"):
        node = lib.create_material_expression(result, cls)
        if not lib.connect_material_expressions(a[0], a[1], node, a_pin):
            raise RuntimeError("Material input A failed")
        if not lib.connect_material_expressions(b[0], b[1], node, b_pin):
            raise RuntimeError("Material input B failed")
        return node, ""

    samples = {}
    for channel, rec in row["textures"].items():
        if red and channel == "base_color" and row.get("team_cloth"):
            rec = row["team_cloth"]["red_base_color"]
        texture_name = "T_" + row["slot_name"] + "_" + channel + ("_Red" if red and channel == "base_color" else "")
        texture = import_asset(u, rec["path"], destination + "/Textures", texture_name, factory=u.TextureFactory())
        texture.set_editor_property("srgb", channel in {"base_color", "emissive"})
        if channel == "normal":
            properties(texture, {"compression_settings": u.TextureCompressionSettings.TC_NORMALMAP,
                                 "flip_green_channel": True})
        elif channel not in {"base_color", "emissive"}:
            texture.set_editor_property("compression_settings", u.TextureCompressionSettings.TC_MASKS)
        u.EditorAssetLibrary.save_loaded_asset(texture, only_if_is_dirty=False)
        node = lib.create_material_expression(result, u.MaterialExpressionTextureSample)
        properties(node, {"texture": texture, "sampler_type":
                          u.MaterialSamplerType.SAMPLERTYPE_NORMAL if channel == "normal" else
                          u.MaterialSamplerType.SAMPLERTYPE_COLOR if channel in {"base_color", "emissive"} else
                          u.MaterialSamplerType.SAMPLERTYPE_MASKS})
        samples[channel] = node
    values = {
        u.MaterialProperty.MP_BASE_COLOR: operation(u.MaterialExpressionMultiply, (samples["base_color"], "RGB"), vector(row["base_color_factor"])),
        u.MaterialProperty.MP_ROUGHNESS: scalar(row["roughness_factor"]),
        u.MaterialProperty.MP_METALLIC: scalar(row["metallic_factor"]),
    }
    if "metallic_roughness" in samples:
        for prop, pin, factor in ((u.MaterialProperty.MP_ROUGHNESS, "G", row["roughness_factor"]),
                                  (u.MaterialProperty.MP_METALLIC, "B", row["metallic_factor"])):
            values[prop] = operation(u.MaterialExpressionMultiply, (samples["metallic_roughness"], pin), scalar(factor))
    if "normal" in samples:
        # glTF scales tangent X/Y only, before normalizing.
        scaled = operation(u.MaterialExpressionMultiply, (samples["normal"], "RGB"),
                           vector([row["normal_scale"], row["normal_scale"], 1]))
        normal = lib.create_material_expression(result, u.MaterialExpressionNormalize)
        if not lib.connect_material_expressions(scaled[0], scaled[1], normal, "VectorInput"):
            raise RuntimeError("Normal normalization input failed")
        values[u.MaterialProperty.MP_NORMAL] = normal, ""
    if "occlusion" in samples:
        ao = operation(u.MaterialExpressionMultiply, (samples["occlusion"], "R"), scalar(row["occlusion_strength"]))
        values[u.MaterialProperty.MP_AMBIENT_OCCLUSION] = operation(
            u.MaterialExpressionAdd, ao, scalar(1-row["occlusion_strength"]))
    if "emissive" in samples:
        values[u.MaterialProperty.MP_EMISSIVE_COLOR] = operation(
            u.MaterialExpressionMultiply, (samples["emissive"], "RGB"), vector(row["emissive_factor"]))
    for prop, (node, pin) in values.items():
        if not lib.connect_material_property(node, pin, prop):
            raise RuntimeError("Material property connection failed: " + str(prop))
    lib.layout_material_expressions(result)
    lib.recompile_material(result)
    u.EditorAssetLibrary.save_loaded_asset(result, only_if_is_dirty=False)
    return result


def records(manifest):
    yield manifest["exports"]["fbx"]
    for row in manifest["materials"]:
        yield from row["textures"].values()
        if row.get("team_cloth"):
            yield row["team_cloth"]["mask"]
            yield row["team_cloth"]["red_base_color"]


def snapshot(u, destination):
    result = []
    for asset in u.EditorAssetLibrary.list_assets(destination, recursive=True, include_folder=False):
        package = ROOT/"Content"/(asset.split(".")[0][len("/Game/"):]+".uasset")
        if not package.is_file():
            raise RuntimeError("Missing saved package " + str(package))
        result.append({"asset": asset, "path": str(package), "sha256": sha(package)})
    return result


def mesh_measurements(u, mesh, manifest):
    bounds = mesh.get_bounds()
    low = [bounds.origin.x-bounds.box_extent.x, bounds.origin.y-bounds.box_extent.y, bounds.origin.z-bounds.box_extent.z]
    high = [bounds.origin.x+bounds.box_extent.x, bounds.origin.y+bounds.box_extent.y, bounds.origin.z+bounds.box_extent.z]
    error = max(abs(a-b) for a, b in zip(low+high, manifest["bounds_cm"]["minimum"]+manifest["bounds_cm"]["maximum"]))
    if error > .1:
        raise ValueError("Imported bounds differ by %.5fcm" % error)
    actual_triangles = int(mesh.get_num_triangles(0))
    removed_degenerate = 0
    if actual_triangles != manifest["triangles"] and manifest.get("terrain_profile"):
        # Flattening a generated road can collapse vertical micro-faces. UE
        # may remove these zero-area faces; bound the import delta by their
        # independently measured count rather than allowing arbitrary loss.
        rec = manifest["exports"]["glb"]
        if sha(rec["path"]) != rec["sha256"]:
            raise ValueError("Prepared terrain GLB changed")
        blob = Path(rec["path"]).read_bytes()
        size = struct.unpack_from("<I", blob, 12)[0]
        document = json.loads(blob[20:20+size])
        binary = blob[28+size:]
        def accessor(index):
            acc = document["accessors"][index]
            view = document["bufferViews"][acc["bufferView"]]
            component, stride = {5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}[acc["componentType"]]
            width = {"SCALAR": 1, "VEC3": 3}[acc["type"]]
            offset = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            step = view.get("byteStride", stride * width)
            return [struct.unpack_from("<" + component * width, binary, offset+i*step) for i in range(acc["count"])]
        for source_mesh in document["meshes"]:
            for primitive in source_mesh["primitives"]:
                positions = accessor(primitive["attributes"]["POSITION"])
                indices = [row[0] for row in accessor(primitive["indices"])]
                for i in range(0, len(indices), 3):
                    a, b, c = [positions[j] for j in indices[i:i+3]]
                    ab = [b[j]-a[j] for j in range(3)]
                    ac = [c[j]-a[j] for j in range(3)]
                    cross = (ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0])
                    if sum(v*v for v in cross) < 4e-20:
                        removed_degenerate += 1
    if not manifest["triangles"] - removed_degenerate <= actual_triangles <= manifest["triangles"]:
        raise ValueError("Static mesh triangle count changed: source=%d imported=%d zero_area=%d" %
                         (manifest["triangles"], actual_triangles, removed_degenerate))
    return {"minimum": low, "maximum": high, "max_error_cm": error, "triangles": actual_triangles,
            "zero_area_triangles_in_source": removed_degenerate,
            "triangles_removed_by_import": manifest["triangles"] - actual_triangles}


def run(u, manifest_path, report_path):
    manifest_path, report_path = resolve(manifest_path), resolve(report_path)
    manifest = read(manifest_path)
    if manifest["status"] != "static_prepared_pending_unreal" or manifest["animations"]:
        raise ValueError("Expected this pipeline's static manifest")
    for rec in records(manifest):
        if sha(rec["path"]) != rec["sha256"]:
            raise ValueError("Frozen input changed: " + rec["path"])
    fingerprint = hashlib.sha256((sha(manifest_path) + ":static_cm_absolute_v2").encode()).hexdigest()[:16]
    destination = "/Game/ArtPilot/EraAssets/" + manifest["asset_id"] + "/h" + fingerprint
    mesh = import_asset(u, manifest["exports"]["fbx"]["path"], destination,
                        "SM_" + manifest["asset_id"], static_options(u), u.FbxFactory())
    rows = {row["slot_name"]: row for row in manifest["materials"]}
    slots = list(mesh.get_editor_property("static_materials"))
    teams = []
    for i, slot in enumerate(slots):
        slot_name = str(slot.get_editor_property("material_slot_name"))
        if slot_name not in rows:
            imported_name = str(slot.get_editor_property("imported_material_slot_name"))
            if imported_name in rows:
                slot_name = imported_name
            else:
                raise ValueError("Unmapped material slot: " + slot_name)
        row = rows[slot_name]
        blue = material(u, row, destination + "/Materials")
        red = material(u, row, destination + "/Materials", True) if row.get("team_cloth") else blue
        mesh.set_material(i, blue)
        teams.append({"slot": i, "path": blue.get_path_name(), "red_path": red.get_path_name()})
    measurements = mesh_measurements(u, mesh, manifest)
    u.EditorAssetLibrary.save_loaded_asset(mesh, only_if_is_dirty=False)
    u.EditorAssetLibrary.save_directory(destination, only_if_is_dirty=False, recursive=True)
    result = {"schema_version": 1, "asset_id": manifest["asset_id"], "kind": manifest["kind"],
              "status": "imported_static_pending_gameplay", "process_id": os.getpid(),
              "source_manifest": str(manifest_path), "source_manifest_sha256": sha(manifest_path),
              "destination": destination, "static_mesh": mesh.get_path_name(),
              "team_materials": teams, "bounds_cm": measurements,
              "dimensions_cm": [b-a for a, b in zip(measurements["minimum"], measurements["maximum"])],
              "anchors_cm": manifest["anchors_cm"], "mechanism": manifest["mechanism"],
              "animations": {}, "full_pbr": manifest["full_pbr"], "remaining": manifest["remaining"],
              "packages": snapshot(u, destination), "failures": [], "production_approved": False}
    write(report_path, result)
    return result


def fresh(u, report_path):
    previous = read(report_path)
    for rec in previous["packages"]:
        if sha(rec["path"]) != rec["sha256"]:
            raise ValueError("Saved package changed")
        if u.EditorAssetLibrary.load_asset(rec["asset"]) is None:
            raise ValueError("Fresh load failed: " + rec["asset"])
    manifest = read(previous["source_manifest"])
    if sha(previous["source_manifest"]) != previous["source_manifest_sha256"]:
        raise ValueError("Prepared manifest changed")
    mesh = u.EditorAssetLibrary.load_asset(previous["static_mesh"])
    measurements = mesh_measurements(u, mesh, manifest)
    for rec in previous["packages"]:
        if sha(rec["path"]) != rec["sha256"]:
            raise ValueError("Read-only load changed a package")
    return {"asset_id": previous["asset_id"], "status": "fresh_passed",
            "packages": len(previous["packages"]), "bounds_cm": measurements}


def main():
    import unreal
    plan_path = resolve(os.environ["CIVWAR_ERA_IMPORT_PLAN"])
    stage = os.environ.get("CIVWAR_ERA_IMPORT_STAGE", "initial")
    if stage not in {"initial", "fresh"}:
        raise ValueError("Invalid stage")
    results = []
    for entry in read(plan_path)["entries"]:
        try:
            result = run(unreal, entry["manifest"], entry["report"]) if stage == "initial" else fresh(unreal, resolve(entry["report"]))
            results.append(result)
        except Exception as error:
            results.append({"manifest": entry["manifest"], "status": "failed",
                            "error": str(error), "traceback": traceback.format_exc()})
        write(plan_path.with_name(stage+"_era_import.json"),
              {"stage": stage, "process_id": os.getpid(), "results": results, "production_approved": False})
    if any(r["status"] == "failed" for r in results):
        raise RuntimeError("Era import failed; see batch report")


if __name__ == "__main__":
    main()
