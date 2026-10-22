"""Add four distinct champion modules using the established original DCC kit."""
import argparse
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
import build_weapons as kit
import bpy


def longsword():
    root = kit.current_root
    kit.rod("longsword_grip", (0, 0, -.14), (0, 0, .12), .026, "leather", root)
    kit.cube("broad_crossguard", (0, 0, .13), (.33, .075, .06), "iron", root, .012)
    kit.ico("steel_pommel", (0, 0, -.17), (.044, .033, .045), "steel", root, 1)
    kit.blade("long_steel_blade", (0, 0, .16), (0, 0, 1.02), .125, .039, "steel", root)
    kit.anchor("grip_r", parent=root)
    kit.anchor("blade_base", (0, 0, .16), root)
    kit.anchor("blade_tip", (0, 0, 1.02), root)
    return "one_hand_champion_longsword", ["Distinct 1.19m long sword; fit and clear shoulder on actual monarch."]


def kite_shield():
    root = kit.current_root
    outline = [(-.30, .30), (-.24, .42), (.24, .42), (.30, .30),
               (.26, -.03), (0, -.53), (-.26, -.03)]
    for name, scale, depth, x, material in (
            ("iron_kite_rim", 1., .055, .035, "iron"),
            ("wood_kite_core", .94, .058, .046, "wood_light"),
            ("cobalt_kite_face", .88, .012, .083, "cobalt")):
        obj = kit.poly_xz(name, [(a*scale, b*scale) for a, b in outline], depth, material, root)
        obj.rotation_euler.z = -math.pi/2
        obj.location.x = x
    kit.ico("low_kite_boss", (.11, 0, .13), (.038, .085, .085), "steel", root, 2)
    for z in (-.10, .10):
        kit.cube("grip_mount", (-.03, -.09, z), (.09, .04, .035), "iron", root, .006)
    kit.rod("rear_hand_grip", (-.08, -.09, -.10), (-.08, -.09, .10), .022, "leather", root)
    kit.tube("forearm_cuff", [(0, .06, -.13), (-.13, .09, -.13), (-.15, .09, 0),
                            (-.13, .09, .13), (0, .06, .13)], .024, "leather", root)
    kit.anchor("shield_l", (-.10, .08, 0), root)
    kit.anchor("shield_grip", (-.08, -.09, 0), root)
    kit.anchor("grip_l", (-.08, -.09, 0), root)
    return "left_arm_kite_shield", ["Pointed kite silhouette, real rear grip/cuff; separate from round infantry shield."]


def saber():
    root = kit.current_root
    kit.COLORS["brass"] = (.40, .29, .12)
    kit.METALLIC["brass"] = .5
    kit.rod("saber_grip", (0, 0, -.11), (0, 0, .10), .026, "leather", root)
    kit.tube("knuckle_guard", [(0, 0, -.13), (.12, 0, -.11), (.14, 0, .09),
                              (.09, 0, .14), (-.06, 0, .14)], .021, "brass", root)
    outline = [(-.045, .14), (-.04, .42), (.005, .69), (.10, .91),
               (.12, 1.00), (.15, .88), (.09, .65), (.055, .41), (.055, .14)]
    kit.poly_xz("curved_steel_saber", outline, .033, "steel", root, edge=.006)
    kit.anchor("grip_r", parent=root)
    kit.anchor("blade_base", (0, 0, .14), root)
    kit.anchor("blade_tip", (.12, 0, 1.00), root)
    return "one_hand_officer_saber", ["Broad curved blade and open knuckle guard; no static hand or scabbard."]


def hammer():
    root = kit.current_root
    kit.rod("hammer_shaft", (0, 0, -.20), (0, 0, .86), .029, "iron", root)
    for z in (0, .28):
        kit.rod("grip_zone", (0, 0, z-.095), (0, 0, z+.095), .035, "leather", root)
    kit.cube("graphite_head", (0, 0, .87), (.48, .23, .25), "graphite", root, .035)
    for x in (-.25, .25):
        kit.cube("steel_impact_face", (x, 0, .87), (.07, .26, .28), "steel", root, .016)
    kit.anchor("grip_r", parent=root)
    kit.anchor("grip_l", (0, 0, .28), root)
    kit.anchor("strike_base", (-.285, 0, .87), root)
    kit.anchor("strike_tip", (.285, 0, .87), root)
    return "two_hand_command_hammer", ["Independent head and separated two-hand grips; match actual exoskeleton reach."]


BUILDERS = {"Weapon_ChampionLongsword": longsword, "Weapon_KiteShield": kite_shield,
            "Weapon_OfficerSaber": saber, "Weapon_CommandHammer": hammer}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", action="append", choices=list(BUILDERS))
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else sys.argv[1:])
    kit.BUILDERS.update(BUILDERS)
    for asset in args.asset or BUILDERS:
        if (kit.OUT/asset/"interface.json").exists():
            raise ValueError("Preserve existing module: "+asset)
        kit.build(asset, render=False)
        bpy.context.scene.render.threads_mode = "FIXED"
        bpy.context.scene.render.threads = 2
        bpy.ops.wm.save_as_mainfile(filepath=str(kit.OUT/asset/(asset+".blend")))


if __name__ == "__main__":
    main()
