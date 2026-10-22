"""Original stylized game satchel; no functional explosive detail."""
import sys
from pathlib import Path
import bpy

sys.path.insert(0, str(Path(__file__).parent))
import build_weapons as kit


def pack():
    root = kit.current_root
    kit.COLORS["charge_red"] = (.42, .065, .045)
    kit.cube("canvas_satchel", (-.09, 0, 0), (.18, .40, .46), "olive", root, .035)
    kit.cube("leather_top_flap", (-.12, 0, .21), (.19, .42, .07), "leather", root, .02)
    for y in (-.14, .14):
        kit.cube("broad_harness", (.012, y, 0), (.035, .045, .47), "leather", root, .008)
        kit.cube("rear_retaining_band", (-.19, y, 0), (.025, .055, .40), "leather", root, .006)
    for y in (-.12, 0, .12):
        kit.rod("wrapped_game_charge", (-.22, y, -.15), (-.22, y, .15), .046, "charge_red", root, vertices=10)
    for z in (-.09, .09):
        kit.cube("broad_charge_strap", (-.268, 0, z), (.018, .37, .035), "leather", root, .004)
    kit.anchor("back_mount", parent=root, role="front plane +X faces actual back; root at pack centre")
    return "body_backpack", ["Purely stylized satchel and three broad red wrapped game props; no wires, fuses, labels or functional internals.",
                             "Keep pack attached in every clip; authority enhanced-hit presentation does not delete it."]


if __name__ == "__main__":
    asset = "Prop_DemolitionPack"
    if (kit.OUT/asset/"interface.json").exists():
        raise ValueError("Preserve existing pack source")
    kit.BUILDERS[asset] = pack
    kit.build(asset, render=False)
    bpy.context.scene.render.threads_mode = "FIXED"
    bpy.context.scene.render.threads = 2
    bpy.ops.wm.save_as_mainfile(filepath=str(kit.OUT/asset/(asset+".blend")))
