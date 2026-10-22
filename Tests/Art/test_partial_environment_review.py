import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Tools'))
from build_partial_environment_review import EXPECTED, build_review_map


class PartialEnvironmentReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source = self.root / 'RawAssets/Art/Tripo_v01/tripo_processed/model.glb'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'reviewed model')
        self.permanent = self.root / 'Content/Data/EnvironmentArt.json'
        self.permanent.parent.mkdir(parents=True)
        self.permanent.write_bytes(b'original prototype mapping')
        self.report = {'dry_run': False, 'failed': 0, 'results': []}
        for asset_id in sorted(EXPECTED):
            self.report['results'].append({
                'id': asset_id, 'status': 'imported', 'warnings': [],
                'source': source.relative_to(self.root).as_posix(),
                'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'destination': '/Game/ArtPilot/tripo_environment_v03/' + asset_id,
                'material_audit': {'status': 'structural_checks_passed'},
                'runtime_material_overrides': {'Metallic': 0},
                'assets': [{'type': 'static_mesh', 'path': '/Game/ArtPilot/tripo_environment_v03/' + asset_id + '/mesh.mesh',
                            'triangles_lod0': 3794, 'dimensions_cm': [406, 561, 650]}]})

    def test_six_review_never_changes_permanent_mapping(self):
        before = self.permanent.read_bytes()
        result = build_review_map(self.report, self.root)
        self.assertEqual(before, self.permanent.read_bytes())
        self.assertEqual(set(result['assets']), EXPECTED)
        self.assertEqual(result['deferred_assets'], ['Env_GrassClump'])
        self.assertFalse(result['production_approved'])
        self.assertTrue(result['hide_deferred_grass'])

    def test_missing_or_duplicate_mother_rejected(self):
        for replacement in (None, self.report['results'][1]):
            report = copy.deepcopy(self.report)
            report['results'].pop()
            if replacement:
                report['results'].append(replacement)
            with self.assertRaisesRegex(ValueError, 'exactly six'):
                build_review_map(report, self.root)

    def test_dry_run_warnings_and_hash_mismatch_rejected(self):
        for change in ('dry_run', 'warnings', 'hash'):
            report = copy.deepcopy(self.report)
            if change == 'dry_run':
                report['dry_run'] = True
            elif change == 'warnings':
                report['results'][0]['warnings'] = ['requires review']
            else:
                report['results'][0]['source_sha256'] = 'invalid'
            with self.assertRaises(ValueError):
                build_review_map(report, self.root)

    def test_prototype_source_cannot_enter_partial_review(self):
        source = self.root / 'prototype.glb'
        source.write_bytes(b'reviewed model')
        self.report['results'][0]['source'] = 'prototype.glb'
        with self.assertRaisesRegex(ValueError, 'prototype'):
            build_review_map(self.report, self.root)

    def test_unrelated_ue_package_rejected(self):
        self.report['results'][0]['assets'][0]['path'] = '/Game/Unrelated/mesh.mesh'
        with self.assertRaisesRegex(ValueError, 'isolated'):
            build_review_map(self.report, self.root)


class DefaultEnvironmentMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapping = json.loads((ROOT / 'Content/Data/EnvironmentArt.json').read_text(encoding='utf-8'))
        cls.legacy_path = ROOT / 'Content/Data/EnvironmentArtLegacy.json'
        cls.legacy = json.loads(cls.legacy_path.read_text(encoding='utf-8'))
        cls.review = json.loads((ROOT / 'RawAssets/Art/Tripo_v01/reviews/environment_inputs_20261020/six_asset_game_review.json').read_text(encoding='utf-8'))
        cls.battlefield = '\n'.join((ROOT / 'Source/CivWar/View' / name).read_text(encoding='utf-8')
                                    for name in ('CWBattlefield.cpp', 'CWBattlefieldEnvironment.cpp'))

    def test_six_reviewed_mothers_are_exact_default_entries(self):
        self.assertTrue(self.mapping['default_runtime_enabled'])
        self.assertEqual(set(self.mapping['assets']), EXPECTED | {'Env_GrassClump'})
        for asset_id in EXPECTED:
            self.assertEqual(self.review['assets'][asset_id], self.mapping['assets'][asset_id])
            self.assertEqual({'Metallic': 0}, self.mapping['assets'][asset_id]['runtime_material_overrides'])

    def test_enabling_defaults_does_not_claim_full_production(self):
        self.assertFalse(self.mapping['production_approved'])
        self.assertFalse(self.mapping['full_environment_complete'])
        self.assertEqual(self.mapping['formal_tripo_mother_count'], 6)
        self.assertEqual(self.mapping['deferred_assets'], ['Env_GrassClump'])
        self.assertEqual(self.mapping['user_enablement']['request'], '那你全面替换了啊')

    def test_old_permanent_mapping_remains_byte_exact_legacy(self):
        expected = '2de33e2ab4ba640d71efac243a78217d8b14e23bfbc4cce211240800d8430b54'
        self.assertEqual(hashlib.sha256(self.legacy_path.read_bytes()).hexdigest(), expected)
        self.assertEqual(self.legacy['batch_id'], 'environment_v02')
        self.assertEqual(self.mapping['legacy_fallback']['mapping'], 'Content/Data/EnvironmentArtLegacy.json')
        self.assertEqual(self.mapping['legacy_fallback']['mapping_sha256'], expected)
        self.assertEqual(self.review['permanent_runtime_mapping_sha256'], expected)

    def test_grass_is_visible_explicit_old_prototype_not_failed_tripo(self):
        grass = self.mapping['assets']['Env_GrassClump']
        self.assertTrue(grass['fallback'])
        self.assertFalse(grass['formal_tripo_approved'])
        self.assertEqual(grass['source_kind'], 'legacy_technical_prototype')
        self.assertFalse(self.mapping['hide_deferred_grass'])
        for field, value in self.legacy['assets']['Env_GrassClump'].items():
            self.assertEqual(grass[field], value)
        self.assertNotIn('tripo_processed', grass['source'])

    def test_default_source_and_actual_mesh_files_exist(self):
        for asset_id in EXPECTED:
            entry = self.mapping['assets'][asset_id]
            self.assertEqual(hashlib.sha256(Path(entry['source']).read_bytes()).hexdigest(), entry['source_sha256'])
            package = entry['object_path'].split('.')[0].removeprefix('/Game/')
            self.assertTrue((ROOT / 'Content' / (package + '.uasset')).is_file(), asset_id)

    def test_user_enablement_keeps_historical_review_hashes(self):
        evidence = [self.mapping['user_enablement']['reviewed_source_manifest'], *self.mapping['user_enablement']['prior_actual_camera_reviews']]
        for record in evidence:
            self.assertEqual(hashlib.sha256((ROOT / record['file']).read_bytes()).hexdigest(), record['sha256'])

    def test_cpp_default_and_explicit_legacy_manifest_selection(self):
        self.assertIn('const bool bLegacyArt = FParse::Param(FCommandLine::Get(), TEXT("cwlegacyart"));', self.battlefield)
        self.assertIn('bLegacyArt ? TEXT("Data/EnvironmentArtLegacy.json") : TEXT("Data/EnvironmentArt.json")', self.battlefield)
        self.assertIn('const bool bReviewOverride = !bLegacyArt && (bInteractivePreview || FParse::Param(FCommandLine::Get(), TEXT("cwartreview")))', self.battlefield)
        self.assertIn('TEXT("cwartenvironment=")', self.battlefield)
        self.assertIn('CIVWAR_ENVIRONMENT_ART mode=%s loaded=%d tripo=%d grass=%s', self.battlefield)

    def test_cpp_keeps_review_gate_uniform_placement_and_explicit_legacy_grass(self):
        self.assertIn('(*Assets)->Values.Num() != 6 || (*Assets)->HasField(TEXT("Env_GrassClump"))', self.battlefield)
        self.assertIn('if (bLegacyArt && !bPartialArtReview)', self.battlefield)
        self.assertIn('Tufts ? TEXT("explicit_legacy") : TEXT("hidden_deferred")', self.battlefield)
        self.assertIn('Source.Contains(TEXT("/tripo_processed/"))', self.battlefield)
        self.assertIn('bUniform ? FVector(RequestedScale.GetMin()) : RequestedScale', self.battlefield)
        self.assertIn('ZOffset * (Bounds.BoxExtent.Z * 2.0 * Scale.Z / Size.Z)', self.battlefield)


if __name__ == '__main__':
    unittest.main()
