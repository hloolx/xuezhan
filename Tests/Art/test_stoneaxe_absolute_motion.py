import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stoneaxe_import", ROOT / "Tools/Unreal/import_stoneaxe_pilot.py")
IMPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORTER)


def vector(values):
    return SimpleNamespace(x=values[0], y=values[1], z=values[2])


class Options:
    def set_editor_property(self, name, value):
        setattr(self, name, value)


class Sequence:
    def get_editor_property(self, name):
        return {"skeleton": "skeleton", "enable_root_motion": False, "rate_scale": 1.0}[name]

    def get_path_name(self):
        return "/Game/ArtPilot/StoneAxeRig/test/Animation"


def run_audit(position_factor=1, scale=1, reflect_y=True):
    frames = [{"frame": index + 1, "time_seconds": index / 60,
               "bones": {"root": {"head_m": [0, 0, 0], "scale": [1, 1, 1]},
                         "hand_r": {"head_m": [.2 + index * .001, -.36, .9], "scale": [1, 1, 1]}}} for index in range(3)]

    def evaluate(sequence, time, options):
        return frames[round(time * 60)]

    def bone_pose(pose, name, space):
        source = pose["bones"][name]["head_m"]
        coordinates = [source[0] * 100, source[1] * (-100 if reflect_y else 100), source[2] * 100]
        return SimpleNamespace(translation=vector([value * position_factor for value in coordinates]),
                               rotation=SimpleNamespace(x=0, y=0, z=0, w=1), scale3d=vector([scale] * 3))

    unreal = SimpleNamespace(
        AnimPoseEvaluationOptions=Options,
        AnimDataEvalType=SimpleNamespace(RAW="raw"),
        AnimPoseSpaces=SimpleNamespace(WORLD="world"),
        AnimationLibrary=SimpleNamespace(get_sequence_length=lambda sequence: 2 / 60,
                                         get_num_frames=lambda sequence: 2, get_num_keys=lambda sequence: 3),
        AnimPoseExtensions=SimpleNamespace(get_anim_pose_at_time=evaluate, is_valid=lambda pose: True, get_bone_pose=bone_pose),
    )
    return IMPORTER.animation_audit(unreal, Sequence(), {"clip": "Idle", "duration_seconds": 2 / 60}, "skeleton", "mesh", frames, read_only=True)


class AbsoluteMotionTests(unittest.TestCase):
    def test_physical_centimetres_and_y_reflection_pass(self):
        result = run_audit()
        self.assertEqual("passed", result["absolute_motion_validation"]["status"])
        self.assertEqual(3, result["absolute_motion_validation"]["frames"])
        self.assertEqual(2, result["absolute_motion_validation"]["bones_per_frame"])

    def test_skipped_armature_150_scale_regression_fails(self):
        result = run_audit(position_factor=1 / 150)
        self.assertEqual("failed", result["absolute_motion_validation"]["status"])
        self.assertGreater(result["absolute_motion_validation"]["maximum_absolute_bone_position_error_cm"], 90)

    def test_inherited_root_scale_without_position_change_fails(self):
        result = run_audit(scale=150)
        self.assertEqual("failed", result["absolute_motion_validation"]["status"])
        self.assertEqual(149, result["absolute_motion_validation"]["maximum_absolute_bone_scale_error"])

    def test_missing_handedness_conversion_fails(self):
        result = run_audit(reflect_y=False)
        self.assertEqual("failed", result["absolute_motion_validation"]["status"])
        self.assertEqual(72, result["absolute_motion_validation"]["maximum_absolute_bone_position_error_cm"])

    def test_review_rotators_cannot_use_ambiguous_positional_arguments(self):
        script = ROOT / "Tools/Unreal/render_stoneaxe_review.py"
        calls = [node for node in ast.walk(ast.parse(script.read_text(encoding="utf-8")))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "Rotator"]
        self.assertGreaterEqual(len(calls), 4)
        for call in calls:
            self.assertEqual([], call.args)
            self.assertEqual({"pitch", "yaw", "roll"}, {keyword.arg for keyword in call.keywords})


if __name__ == "__main__":
    unittest.main()
