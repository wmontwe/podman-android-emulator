import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_source', REPO / 'scripts/package-source.py')
package_source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package_source)


def git(directory, *args):
    # Ignore the developer's global config (commit signing, hooks).
    env = {'PATH': os.environ['PATH'], 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}
    return subprocess.run(['git', '-C', str(directory), '-c', 'user.name=t', '-c', 'user.email=t@t',
                           *args], check=True, capture_output=True, text=True, env=env).stdout.strip()


@unittest.skipUnless(shutil.which('git'), 'git is required')
class PackageSourceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project_dir = self.root / 'external/qemu'
        self.project_dir.mkdir(parents=True)
        git(self.project_dir, 'init', '-q')
        (self.project_dir / 'kvm.c').write_text('original\n')
        (self.project_dir / 'other.c').write_text('other\n')
        git(self.project_dir, 'add', '.')
        git(self.project_dir, 'commit', '-qm', 'base')
        self.project = {'name': 'platform/external/qemu', 'path': 'external/qemu',
                        'revision': git(self.project_dir, 'rev-parse', 'HEAD')}
        (self.project_dir / 'kvm.c').write_text('patched\n')
        self.expected = {'platform/external/qemu': {'kvm.c': hashlib.sha256(b'patched\n').hexdigest()}}

    def tearDown(self):
        self.temp.cleanup()

    def test_selection_excludes_toolchains_and_tests(self):
        self.assertTrue(package_source.included('external/qemu'))
        self.assertTrue(package_source.included('prebuilts/android-emulator-build/archive'))
        for path in ('prebuilts/clang/host/linux-x86', 'prebuilts/android-emulator-build/qt', 'external/deqp'):
            self.assertFalse(package_source.included(path))

    def test_expected_modifications_maps_patch_projects(self):
        provenance = {'patches': [
            {'files': {'a.c': {'before': '0', 'after': '1'}}},
            {'source_repository': 'https://android.googlesource.com/platform/hardware/google/gfxstream',
             'files': {'b.cpp': {'before': '2', 'after': '3'}}}]}
        self.assertEqual(package_source.expected_modifications(provenance), {
            'platform/external/qemu': {'a.c': '1'},
            'platform/hardware/google/gfxstream': {'b.cpp': '3'}})

    def test_recorded_patch_passes_and_lists_tracked_files(self):
        (self.project_dir / 'untracked.o').write_text('build output')
        files = package_source.verify_project(self.root, self.project, self.expected)
        self.assertEqual(sorted(files), ['external/qemu/kvm.c', 'external/qemu/other.c'])

    def test_unrecorded_change_fails(self):
        (self.project_dir / 'other.c').write_text('experimental change\n')
        with self.assertRaisesRegex(ValueError, 'unrecorded changes'):
            package_source.verify_project(self.root, self.project, self.expected)

    def test_patch_content_mismatch_fails(self):
        (self.project_dir / 'kvm.c').write_text('different patch\n')
        with self.assertRaisesRegex(ValueError, 'recorded patch result'):
            package_source.verify_project(self.root, self.project, self.expected)

    def test_wrong_revision_fails(self):
        with self.assertRaisesRegex(ValueError, 'provenance pins'):
            package_source.verify_project(self.root, dict(self.project, revision='0' * 40), self.expected)


if __name__ == '__main__':
    unittest.main()
