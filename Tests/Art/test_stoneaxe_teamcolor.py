import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stoneaxe_teamcolor", ROOT / "Tools/Unreal/import_stoneaxe_teamcolor.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TeamColorTests(unittest.TestCase):
    def test_noncloth_pixels_remain_exactly_original(self):
        original = [.51, .23, .11]
        for team in MODULE.TEAM_COLORS.values():
            self.assertEqual(original, MODULE.shade_reference(original, team, 0, 1))

    def test_strength_zero_preserves_original_blue(self):
        original = [.031, .12, .38]
        self.assertEqual(original, MODULE.shade_reference(original, MODULE.TEAM_COLORS["Red"], 1, 0))

    def test_both_team_colors_preserve_linear_cloth_luminance(self):
        for original in ([.01, .05, .2], [.04, .13, .4], [.1, .3, .6]):
            expected = sum(value * weight for value, weight in zip(original, MODULE.LUMINANCE))
            for team in MODULE.TEAM_COLORS.values():
                actual = MODULE.shade_reference(original, team, 1, 1)
                self.assertAlmostEqual(expected, sum(value * weight for value, weight in zip(actual, MODULE.LUMINANCE)), places=12)
                self.assertAlmostEqual(actual[0] / team[0], actual[1] / team[1], places=12)
                self.assertAlmostEqual(actual[1] / team[1], actual[2] / team[2], places=12)

    def test_strength_is_clamped(self):
        original = [.03, .12, .38]
        team = MODULE.TEAM_COLORS["Red"]
        self.assertEqual(original, MODULE.shade_reference(original, team, 1, -1))
        self.assertEqual(MODULE.shade_reference(original, team, 1, 1), MODULE.shade_reference(original, team, 1, 2))

    def test_zero_team_color_is_finite(self):
        self.assertEqual([0.0, 0.0, 0.0], MODULE.shade_reference([.1, .2, .3], [0, 0, 0], 1, 1))

    def test_graph_connections_have_unique_destination_pins(self):
        pins = [(target, pin) for source, output, target, pin in MODULE.LINKS]
        self.assertEqual(len(pins), len(set(pins)))
        for source, output, target, pin in MODULE.LINKS:
            self.assertIn(source, MODULE.NODE_CLASSES)
            self.assertIn(target, MODULE.NODE_CLASSES)
        self.assertIn(("base_color", "RGB", "cloth_blend", "A"), MODULE.LINKS)
        self.assertIn(("masked_strength", "", "cloth_blend", "Alpha"), MODULE.LINKS)
        self.assertIn(("team_strength", "", "clamped_strength", ""), MODULE.LINKS)

    def test_changed_source_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.bin"
            path.write_bytes(b"approved")
            record = MODULE.file_record(path)
            MODULE.check_record(record)
            path.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "frozen source changed"):
                MODULE.check_record(record)

    def test_ue58_false_setter_return_requires_actual_readback(self):
        instance = {}

        def set_vector(target, name, value):
            target[name] = value
            return False

        def set_scalar(target, name, value):
            target[name] = value
            return False

        editing = SimpleNamespace(set_material_instance_vector_parameter_value=set_vector,
                                  set_material_instance_scalar_parameter_value=set_scalar,
                                  update_material_instance=lambda target: None,
                                  get_material_instance_vector_parameter_value=lambda target, name: target[name],
                                  get_material_instance_scalar_parameter_value=lambda target, name: target[name])
        unreal = SimpleNamespace(MaterialEditingLibrary=editing, LinearColor=lambda **kwargs: SimpleNamespace(**kwargs))
        MODULE.set_instance_parameters(unreal, instance, MODULE.TEAM_COLORS["Red"])
        editing.get_material_instance_scalar_parameter_value = lambda target, name: 0.0
        with self.assertRaisesRegex(ValueError, "readback differs"):
            MODULE.set_instance_parameters(unreal, instance, MODULE.TEAM_COLORS["Red"])


if __name__ == "__main__":
    unittest.main()
