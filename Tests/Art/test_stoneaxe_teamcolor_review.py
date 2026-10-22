import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stoneaxe_teamcolor_review", ROOT / "Tools/Unreal/render_stoneaxe_teamcolor.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TeamColorReviewTests(unittest.TestCase):
    def setUp(self):
        self.path = "/Game/ArtPilot/StoneAxeRig/test/T_base.T_base"
        self.line = f"[2026.10.19-20.00.12:761][2]LogConsoleResponse: 2048,2048,2731,0,2048,2048,2731,PF_DXT5,TEXTUREGROUP_World,{self.path},YES,NO,NO,1,12,NO\n"

    def test_native_resident_dimensions_are_parsed(self):
        records = MODULE.parse_texture_dump("BEGIN\n" + self.line + "END", "BEGIN", "END", {self.path})
        self.assertTrue(MODULE.textures_resident(records, {self.path}))

    def test_missing_current_dump_cannot_reuse_previous_lines(self):
        self.assertIsNone(MODULE.parse_texture_dump(self.line, "BEGIN", "END", {self.path}))
        self.assertIsNone(MODULE.parse_texture_dump("BEGIN\n" + self.line, "BEGIN", "END", {self.path}))

    def test_low_resident_mips_block_capture(self):
        line = self.line.replace(",2048,2048,2731,PF_DXT5", ",64,64,3,PF_DXT5")
        records = MODULE.parse_texture_dump("BEGIN\n" + line + "END", "BEGIN", "END", {self.path})
        self.assertEqual([64, 64], records[self.path]["actual_resident_size"])
        self.assertFalse(MODULE.textures_resident(records, {self.path}))

    def test_missing_texture_blocks_capture(self):
        records = MODULE.parse_texture_dump("BEGIN\n" + self.line + "END", "BEGIN", "END", {self.path})
        self.assertFalse(MODULE.textures_resident(records, {self.path, "/Game/other"}))

    def test_control_is_original_disabled_original(self):
        names = [shot[0] for shot in MODULE.SHOTS]
        self.assertEqual(["original_front", "original_face", "disabled_front", "disabled_face", "original_repeat_front", "original_repeat_face"], names[:6])
        self.assertEqual(14, len(set(names)))


if __name__ == "__main__":
    unittest.main()
