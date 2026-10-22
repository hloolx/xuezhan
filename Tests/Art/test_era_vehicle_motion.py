"""Numerical kinematics checks; fixtures are synthetic, not asset approvals."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("vehicle_motion", ROOT/"Tools/Blender/era_vehicle_motion.py")
MOTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOTION)


def specimen(profile):
    row = {"profile": profile, "reference_move_speed_cm_s": 150,
           "contact_time": .4, "attack_interval": 2.2,
           "joint_origins_cm": {"root": [0, 0, 0], "hull": [0, 0, 100],
                                "gun": [40, 0, 130], "muzzle": [110, 0, 130]},
           "recoil": [{"bone": "gun", "dependent_bones": ["muzzle"], "distance_cm": 8}]}
    if profile == "wheeled_unit":
        row["wheels"] = []
        for i, (x, y) in enumerate(((70, 55), (70, -55), (-70, 55), (-70, -55))):
            bone = "wheel_"+str(i)
            row["joint_origins_cm"][bone] = [x, y, 35]
            row["wheels"].append({"bone": bone, "radius_cm": 35})
    elif profile == "tracked_unit":
        row["tracks"] = []
        for side in (-1, 1):
            track = {"half_straight_cm": 75, "radius_cm": 35, "lateral_cm": side*60,
                     "centre_height_cm": 35, "bones": []}
            length = MOTION.capsule_length(.75, .35)
            for i in range(24):
                bone = f"track_{side}_{i}"
                row["joint_origins_cm"][bone] = (MOTION.capsule_frame(i*length/24, .75, .35, side*.6, .35)[:3, 3]*100).tolist()
                track["bones"].append(bone)
            row["tracks"].append(track)
    else:
        row["legs"] = []
        for side in (-1, 1):
            leg = {key: key+str(side) for key in ("upper", "lower", "foot")}
            for key, x, z in (("upper", 0, 140), ("lower", 50, 85), ("foot", 0, 25)):
                row["joint_origins_cm"][leg[key]] = [x, side*40, z]
            row["legs"].append(leg)
    return row


class MechanicalMotionTests(unittest.TestCase):
    def test_move_and_idle_loops_close_for_all_profiles(self):
        for profile in ("wheeled_unit", "tracked_unit", "biped_mech"):
            motion = MOTION.Motion(specimen(profile))
            for clip in ("Idle", "Move"):
                first, last = motion.pose(clip, 0), motion.pose(clip, motion.durations[clip])
                for bone in first:
                    np.testing.assert_allclose(first[bone], last[bone], atol=1e-10, err_msg=profile+"/"+clip+"/"+bone)

    def test_wheel_bottom_cancels_actor_velocity(self):
        motion = MOTION.Motion(specimen("wheeled_unit"))
        name, step = "wheel_0", 1e-5
        point = np.r_[motion.origins[name]-[0, 0, .35], 1]
        before, after = [motion.pose("Move", time)[name] @ point for time in (0, step)]
        velocity = (after-before)[:3]/step + [motion.speed, 0, 0]
        self.assertLess(np.linalg.norm(velocity), .0001)

    def test_tread_bottom_cancels_velocity_and_idle_stays_grounded(self):
        motion = MOTION.Motion(specimen("tracked_unit"))
        name = motion.spec["tracks"][0]["bones"][3]
        point = np.r_[motion.origins[name], 1]
        t, step = .08, 1e-4
        before, after = [motion.pose("Move", time)[name] @ point for time in (t, t+step)]
        np.testing.assert_allclose((after-before)[:3]/step + [motion.speed, 0, 0], [0, 0, 0], atol=1e-8)
        np.testing.assert_allclose(motion.pose("Idle", .5)[name], np.eye(4), atol=1e-10)

    def test_mech_support_cancels_actor_and_ik_preserves_segment_lengths(self):
        motion = MOTION.Motion(specimen("biped_mech"))
        step = 1e-4
        first_leg = motion.spec["legs"][0]
        name = first_leg["foot"]
        point = np.r_[motion.origins[name], 1]
        before, after = [motion.pose("Move", time)[name] @ point for time in (.1, .1+step)]
        np.testing.assert_allclose((after-before)[:3]/step + [motion.speed, 0, 0], [0, 0, 0], atol=1e-8)
        for time in np.linspace(0, motion.cycle, 91):
            pose = motion.pose("Move", time)
            for leg in motion.spec["legs"]:
                for upper, lower in (("upper", "lower"), ("lower", "foot")):
                    a, b = [motion.origins[leg[key]] for key in (upper, lower)]
                    actual_end = (pose[leg[upper]] @ np.r_[b, 1])[:3]
                    next_origin = (pose[leg[lower]] @ np.r_[b, 1])[:3]
                    np.testing.assert_allclose(actual_end, next_origin, atol=1e-9)
                    actual_start = (pose[leg[upper]] @ np.r_[a, 1])[:3]
                    self.assertAlmostEqual(np.linalg.norm(actual_end-actual_start), np.linalg.norm(b-a), places=10)

    def test_attack_returns_and_death_holds_without_root_motion(self):
        for profile in ("wheeled_unit", "tracked_unit", "biped_mech"):
            motion = MOTION.Motion(specimen(profile))
            ready = motion.pose("Idle", 0)
            end = motion.pose("Attack", motion.attack)
            for bone in ready:
                np.testing.assert_allclose(end[bone], ready[bone], atol=1e-10)
            self.assertGreater(np.linalg.norm(motion.pose("Attack", motion.contact+.03)["gun"]-ready["gun"]), .01)
            death_a, death_b = [motion.pose("Death", t) for t in (1.45, 1.8)]
            for bone in death_a:
                np.testing.assert_allclose(death_a[bone], death_b[bone], atol=1e-10)
            for clip, duration in motion.durations.items():
                for time in np.linspace(0, duration, 30):
                    np.testing.assert_array_equal(motion.pose(clip, time)["root"], np.eye(4))

    def test_swing_join_has_no_velocity_or_position_jump(self):
        cycle, speed, stance = .9, 1.5, .6
        eps = 1e-5
        for junction in (0, cycle*stance, cycle):
            left, center, right = [MOTION.foot_path(t, cycle, speed, stance)[0]
                                  for t in (junction-eps, junction, junction+eps)]
            self.assertLess(np.linalg.norm(left-right), .00004)
            np.testing.assert_allclose((center-left)/eps, (right-center)/eps, atol=.001)


if __name__ == "__main__":
    unittest.main()
