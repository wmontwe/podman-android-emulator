"""Synthetic policy tests, not evidence of real release/source correspondence."""
import importlib.util
import json
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/verify-upstream-release.py'
spec = importlib.util.spec_from_file_location('verify_release', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StableReleaseTests(unittest.TestCase):
    def setUp(self):
        self.target = {
            'release_policy': 'latest-published-stable-source', 'sdk_channel': 'channel-0',
            'allow_beta_or_rc': False, 'allow_version_relabeling': False,
            'published_source_verified': True, 'source_release_branch': 'emu-35-6-release',
            'source_version': '35.6.2', 'sdk_version': '37.2.13',
            'source_revision': '1' * 40, 'resolved_manifest_revision': '2' * 40,
            'manifest_sha256': '5' * 64,
        }
        self.provenance = {
            'distribution_revision': '35.6.2', 'source_revision': '1' * 40,
            'manifest_revision': '2' * 40, 'manifest_sha256': '5' * 64,
            'release_branch': 'emu-35-6-release', 'source_ref_type': 'release-branch',
            'source_repository': 'https://android.googlesource.com/platform/external/qemu',
            'manifest_repository': 'https://android.googlesource.com/platform/manifest',
        }

    def verify(self):
        module.verify(self.target, self.provenance)

    def test_selected_release_and_build_lock_agree(self):
        root = SCRIPT.parents[1]
        target = json.loads((root / 'upstream-release-target.json').read_text())
        lock = json.loads((root / 'upstream-source.lock.json').read_text())
        for selected, pinned in [('source_revision', 'qemu_revision'),
                                 ('resolved_manifest_revision', 'manifest_revision'),
                                 ('manifest_sha256', 'manifest_sha256'),
                                 ('source_version', 'source_version'),
                                 ('source_release_branch', 'release_branch')]:
            self.assertEqual(target[selected], lock[pinned])

    def test_matching_synthetic_pins(self):
        self.verify()

    def test_unverified_published_source_is_rejected(self):
        self.target['published_source_verified'] = False
        with self.assertRaisesRegex(ValueError, 'not verified'):
            self.verify()

    def test_missing_source_pin_is_rejected(self):
        self.target['source_revision'] = None
        with self.assertRaisesRegex(ValueError, 'pins are incomplete'):
            self.verify()

    def test_rc_is_not_a_stable_substitute(self):
        self.provenance['distribution_revision'] = '37.3.9'
        with self.assertRaisesRegex(ValueError, 'distribution_revision'):
            self.verify()

    def test_same_version_with_wrong_source_is_rejected(self):
        self.provenance['source_revision'] = '3' * 40
        with self.assertRaisesRegex(ValueError, 'source_revision'):
            self.verify()

    def test_same_version_with_wrong_manifest_is_rejected(self):
        self.provenance['manifest_revision'] = '4' * 40
        with self.assertRaisesRegex(ValueError, 'manifest_revision'):
            self.verify()

    def test_beta_channel_policy_is_rejected(self):
        self.target['sdk_channel'] = 'channel-1'
        with self.assertRaisesRegex(ValueError, 'stable-only'):
            self.verify()

    def test_sdk_reference_does_not_relabel_source(self):
        self.target['sdk_version'] = '99.0.0'
        self.verify()
        self.provenance['distribution_revision'] = '99.0.0'
        with self.assertRaisesRegex(ValueError, 'distribution_revision'):
            self.verify()

    def test_development_branch_is_rejected(self):
        self.target['source_release_branch'] = 'emu-main-dev'
        with self.assertRaisesRegex(ValueError, 'release branch'):
            self.verify()

    def test_explicit_published_stable_commit_does_not_need_release_branch(self):
        self.target.update(source_ref_type='published-stable-commit', source_designation='stable', source_release_branch=None)
        self.provenance.update(source_ref_type='published-stable-commit', release_branch=None)
        self.verify()

    def test_stable_commit_requires_stable_designation(self):
        self.target.update(source_ref_type='published-stable-commit', source_designation='rc')
        with self.assertRaisesRegex(ValueError, 'Stable commit'):
            self.verify()

    def test_manifest_hash_mismatch_is_rejected(self):
        self.provenance['manifest_sha256'] = '6' * 64
        with self.assertRaisesRegex(ValueError, 'manifest_sha256'):
            self.verify()

    def test_relabeling_policy_is_rejected(self):
        self.target['allow_version_relabeling'] = True
        with self.assertRaisesRegex(ValueError, 'stable-only'):
            self.verify()
