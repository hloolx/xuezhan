"""Runtime evidence must distinguish an actual playable preview from fallback."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("art_preview", Path(__file__).resolve().parents[2] / "Tools/play_art_preview.py")
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)


class PreviewEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.json"
        self.path.write_text("{}")
        self.state = {"included": ["Unit_StoneAxe"], "protected_files": {str(self.path): preview.sha(self.path)}}
        self.log = "CIVWAR_ART_PREVIEW environment_meshes=6 camera=player\nCIVWAR_STONEAXE_PILOT mesh=/Game/ArtPilot/test\n"

    def result(self, log=None, shots=None, code=0, timeout=False):
        return preview.summarize(self.log if log is None else log, self.state,
                                 [{"path": "actual.png"}] if shots is None else shots, code, timeout)

    def test_smoke_does_not_claim_full_match_input_network_or_production(self):
        result = self.result()
        self.assertTrue(result["runtime_smoke_passed"])
        for field in ("manual_input_tested", "network_tested", "full_match_verified", "production_approved"):
            self.assertFalse(result[field])

    def test_silent_fallback_is_failure(self):
        self.assertFalse(self.result(log="")['runtime_smoke_passed'])

    def test_review_camera_is_not_playable_preview(self):
        self.assertFalse(self.result(log=self.log + "CIVWAR_ART_REVIEW shot=locked.png")['runtime_smoke_passed'])

    def test_config_changes_are_detected(self):
        self.path.write_text('{"changed": true}')
        self.assertFalse(self.result()['runtime_smoke_passed'])

    def test_missing_image_timeout_and_crash_are_failures(self):
        self.assertFalse(self.result(shots=[])['runtime_smoke_passed'])
        self.assertFalse(self.result(timeout=True)['runtime_smoke_passed'])
        self.assertFalse(self.result(code=1)['runtime_smoke_passed'])

    def test_optional_base_must_appear_on_both_teams(self):
        self.state['included'].append('Base_Stone')
        self.assertFalse(self.result(log=self.log + 'CIVWAR_BASE_STONE_PILOT team=0')['runtime_smoke_passed'])
        self.assertTrue(self.result(log=self.log + 'CIVWAR_BASE_STONE_PILOT team=0\nCIVWAR_BASE_STONE_PILOT team=1')['runtime_smoke_passed'])


class EnvironmentLineageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        data = self.root / "Content/Data"
        data.mkdir(parents=True)
        self.legacy = data / "EnvironmentArtLegacy.json"
        self.permanent = data / "EnvironmentArt.json"
        self.grass = {"object_path": "legacy_grass", "source_sha256": "old_grass"}
        self.legacy.write_text(json.dumps({"assets": {"Env_GrassClump": self.grass}}))
        self.mapping = {"permanent_runtime_mapping_sha256": preview.sha(self.legacy),
                        "assets": {name: {"object_path": name, "source_sha256": name} for name in preview.ENV_IDS}}
        self.current = {"default_runtime_enabled": True,
                        "assets": {**self.mapping["assets"], "Env_GrassClump": self.grass}}
        self.save()

    def save(self):
        self.permanent.write_text(json.dumps(self.current))

    def test_exact_archived_map_and_reviewed_default_assets_are_accepted(self):
        self.assertEqual([self.legacy], preview.environment_lineage(self.root, self.mapping, self.permanent))

    def test_old_unchanged_permanent_map_still_works(self):
        self.permanent.write_bytes(self.legacy.read_bytes())
        self.assertEqual([], preview.environment_lineage(self.root, self.mapping, self.permanent))

    def test_changed_reviewed_source_is_rejected(self):
        self.current["assets"]["Env_Pine"] = {"object_path": "unreviewed"}
        self.save()
        with self.assertRaisesRegex(ValueError, "differs from reviewed"):
            preview.environment_lineage(self.root, self.mapping, self.permanent)

    def test_changed_legacy_map_is_rejected(self):
        self.legacy.write_text("{}")
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            preview.environment_lineage(self.root, self.mapping, self.permanent)

    def test_unreviewed_grass_is_rejected(self):
        self.current["assets"]["Env_GrassClump"] = {"object_path": "new_grass"}
        self.save()
        with self.assertRaisesRegex(ValueError, "grass cannot replace"):
            preview.environment_lineage(self.root, self.mapping, self.permanent)


if __name__ == '__main__':
    unittest.main()
