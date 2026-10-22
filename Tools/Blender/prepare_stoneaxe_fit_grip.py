import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/stoneaxe_rig_pilot/grip_draft_v01"
report = json.loads((DIRECTORY / "grip_draft.json").read_text(encoding="utf-8"))
clearance = report["clearance"]
center = clearance["center_world"]
best = []
for radius in (.014, .016, .018, .020, .0225):
    for offset_x in range(-55, 31, 2):
        for offset_y in range(-30, 51, 2):
            position = (center[0] + offset_x / 1000, center[1] + offset_y / 1000)
            groups = {}
            for sample in clearance["samples"]:
                world = sample["world"]
                distance = math.hypot(world[0] - position[0], world[1] - position[1]) - radius
                groups.setdefault(sample["group"], []).append(distance)
            penetration = sum(min(0, distance + .001) ** 2 for values in groups.values() for distance in values)
            contacts = {group: min(values) for group, values in groups.items()}
            contact_loss = sum(max(0, distance - .002) ** 2 for group, distance in contacts.items())
            score = penetration * 50 + contact_loss
            best.append({"score": score, "radius": radius, "offset_mm": [offset_x, offset_y],
                         "center_world": list(position) + [center[2]], "contacts_mm": {group: value * 1000 for group, value in contacts.items()},
                         "penetrating_over_2mm": sum(distance < -.002 for values in groups.values() for distance in values)})
best.sort(key=lambda row: row["score"])
(DIRECTORY / "handle_fit_candidates.json").write_text(json.dumps(best[:20], indent=2), encoding="utf-8")
print(json.dumps(best[:5], indent=2))
