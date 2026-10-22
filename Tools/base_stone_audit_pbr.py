"""Read-only GLB texture payload and channel statistics for the frozen Base PBR."""
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import struct

from PIL import Image, ImageStat


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/base_stone_v01/pbr_v01/hf150ba0cde05"
RAW = ROOT / "RawAssets/Art/Tripo_v01/tripo_raw/Base_Stone/textured_v01_canonical/model.glb"
MODEL = OUTPUT / "Base_Stone_PBR.glb"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inspect(path):
    data = path.read_bytes()
    if data[:4] != b"glTF":
        raise ValueError("Expected GLB")
    cursor = 12
    document, payload = None, None
    while cursor < len(data):
        length, kind = struct.unpack_from("<II", data, cursor)
        chunk = data[cursor + 8:cursor + 8 + length]
        cursor += length + 8
        if kind == 0x4e4f534a:
            document = json.loads(chunk.rstrip(b" \x00"))
        elif kind == 0x004e4942:
            payload = chunk
    images = []
    for image_index, image in enumerate(document.get("images", [])):
        buffer = document["bufferViews"][image["bufferView"]]
        start = buffer.get("byteOffset", 0)
        encoded = payload[start:start + buffer["byteLength"]]
        decoded = Image.open(io.BytesIO(encoded)).convert("RGB")
        statistics = ImageStat.Stat(decoded)
        histogram = decoded.histogram()
        pixels = decoded.width * decoded.height
        images.append({"image_index": image_index, "name": image.get("name"), "mime_type": image.get("mimeType"),
                       "encoded_sha256": digest(encoded), "decoded_rgb_sha256": digest(decoded.tobytes()),
                       "size": list(decoded.size), "mean_rgb_0_255": statistics.mean, "extrema_rgb": statistics.extrema,
                       "blue_nonzero_fraction": 1 - histogram[512] / pixels,
                       "blue_at_least128_fraction": sum(histogram[640:768]) / pixels})
    return {"file": path.relative_to(ROOT).as_posix(), "sha256": digest(data), "images": images,
            "gltf_materials": document.get("materials", []), "gltf_textures": document.get("textures", [])}


raw = inspect(RAW)
processed = inspect(MODEL)
raw_hashes = Counter(image["encoded_sha256"] for image in raw["images"])
processed_hashes = Counter(image["encoded_sha256"] for image in processed["images"])
metallic = []
for material in raw["gltf_materials"]:
    settings = material.get("pbrMetallicRoughness", {})
    texture = settings.get("metallicRoughnessTexture")
    if texture:
        image_index = raw["gltf_textures"][texture["index"]]["source"]
        image = raw["images"][image_index]
        metallic.append({"material": material.get("name"), "image": image_index,
                         "metallic_blue_mean_0_1": image["mean_rgb_0_255"][2] / 255,
                         "roughness_green_mean_0_1": image["mean_rgb_0_255"][1] / 255,
                         "metallic_factor": settings.get("metallicFactor", 1),
                         "statistics_scope": "Entire stored atlas including padding; not UV-coverage weighted"})
result = {"asset_id": "Base_Stone", "raw": raw, "processed": processed,
          "all_original_embedded_image_bytes_preserved": raw_hashes == processed_hashes,
          "all_decoded_rgb_images_preserved": Counter(image["decoded_rgb_sha256"] for image in raw["images"]) == Counter(image["decoded_rgb_sha256"] for image in processed["images"]),
          "packed_channel_statistics": metallic, "derived_preview_metallic": 0,
          "derived_preview_reason": "Wood, stone, bone, thatch and cloth are dielectric. The original packed metallic map and factor are retained in frozen model; review scene uses explicitMetallic0 only.",
          "images_modified": False, "production_approved": False}
report = OUTPUT / "texture_payload_audit.json"
if report.exists():
    raise FileExistsError("Do not overwrite existing texture audit")
report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"report": str(report), "image_bytes_preserved": result["all_original_embedded_image_bytes_preserved"],
                  "decoded_rgb_preserved": result["all_decoded_rgb_images_preserved"], "channels": metallic}))
