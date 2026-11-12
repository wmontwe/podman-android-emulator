import hashlib
import importlib.util
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_release', REPO / 'scripts/package-release.py')
package_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package_release)

PROVENANCE = {'distribution_revision': '37.2.12', 'source_revision': 'a' * 40, 'manifest_revision': 'b' * 40}
TARGET = {'source_version': '37.2.12', 'guest_api': 36}
SOURCE = {'name': 'source-v37.2.12-r1.tar.xz', 'sha256': 'c' * 64, 'files': 1,
          'parts': [{'name': 'source-v37.2.12-r1.tar.xz.part00', 'sha256': 'c' * 64, 'size': 1}]}


def make_inputs(root):
    (root / 'emulator/lib64').mkdir(parents=True)
    (root / 'provenance.json').write_text('{}')
    (root / 'emulator/emulator').write_bytes(b'\x7fELF launcher')
    os.chmod(root / 'emulator/emulator', 0o700)
    (root / 'emulator/lib64/libx.so').write_bytes(b'library')
    os.chmod(root / 'emulator/lib64/libx.so', 0o600)


class PackageReleaseTest(unittest.TestCase):
    def test_tag_format(self):
        self.assertEqual(package_release.parse_tag('v37.2.12-r1'), ('37.2.12', 1))
        for tag in ('37.2.12-r1', 'v37.2.12', 'v37.2.12-r0', 'v37.2-r1', 'v37.2.12-r1 '):
            with self.assertRaises(ValueError):
                package_release.parse_tag(tag)

    def test_archive_is_reproducible_and_normalized(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            make_inputs(temp / 'inputs')
            first, second = temp / 'a.tar.gz', temp / 'b.tar.gz'
            package_release.write_archive(temp / 'inputs', first)
            os.utime(temp / 'inputs/emulator/emulator', (1, 1))
            package_release.write_archive(temp / 'inputs', second)
            self.assertEqual(hashlib.sha256(first.read_bytes()).hexdigest(),
                             hashlib.sha256(second.read_bytes()).hexdigest())
            with tarfile.open(first) as archive:
                members = {m.name: m for m in archive.getmembers()}
            self.assertEqual(list(members), ['provenance.json', 'emulator', 'emulator/emulator',
                                             'emulator/lib64', 'emulator/lib64/libx.so'])
            self.assertTrue(all(m.uid == 0 and m.gid == 0 and m.mtime == 0 for m in members.values()))
            self.assertEqual(members['emulator/emulator'].mode, 0o755)
            self.assertEqual(members['emulator/lib64/libx.so'].mode, 0o644)

    def test_archive_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            make_inputs(temp / 'inputs')
            (temp / 'inputs/emulator/link').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                package_release.write_archive(temp / 'inputs', temp / 'out.tar.gz')

    def test_record_pins_archive_and_requires_source(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'emulator-v37.2.12-r1-linux-aarch64.tar.gz'
            archive.write_bytes(b'archive')
            record = package_release.release_record('v37.2.12-r1', PROVENANCE, TARGET, archive, SOURCE, 'ghcr.io/x/y')
            self.assertEqual(record['archive']['sha256'], hashlib.sha256(b'archive').hexdigest())
            self.assertEqual(record['image_tag'], '37.2.12-r1')
            self.assertEqual(record['build'], 'local')
            with self.assertRaises(ValueError):
                package_release.release_record('v37.2.12-r1', PROVENANCE, TARGET, archive, None, 'ghcr.io/x/y')

    def test_source_parts_must_match_record(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            with self.assertRaisesRegex(ValueError, 'Missing source part'):
                package_release.check_source_parts(SOURCE, directory)
            part = directory / 'source-v37.2.12-r1.tar.xz.part00'
            part.write_bytes(b'x')
            with self.assertRaisesRegex(ValueError, 'does not match'):
                package_release.check_source_parts(SOURCE, directory)
            good = {'parts': [{'name': part.name, 'size': 1, 'sha256': hashlib.sha256(b'x').hexdigest()}]}
            package_release.check_source_parts(good, directory)
            with self.assertRaisesRegex(ValueError, 'Missing source part'):
                package_release.check_source_parts({'parts': [{'name': '../escape', 'size': 1, 'sha256': ''}]}, directory)

    def test_record_rejects_version_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'a.tar.gz'
            archive.write_bytes(b'archive')
            with self.assertRaises(ValueError):
                package_release.release_record('v37.2.13-r1', PROVENANCE, TARGET, archive, SOURCE, 'ghcr.io/x/y')
            with self.assertRaises(ValueError):
                package_release.release_record('v37.2.12-r1', PROVENANCE, {'source_version': '37.2.13'},
                                               archive, SOURCE, 'ghcr.io/x/y')


if __name__ == '__main__':
    unittest.main()
