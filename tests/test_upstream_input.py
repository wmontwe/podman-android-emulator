"""Exercise input validation with synthetic fixtures; never execute binaries."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/verify-upstream-input.py'
spec = importlib.util.spec_from_file_location('verify_upstream', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class UpstreamInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'emulator'
        self.provenance = Path(self.temp.name) / 'provenance.json'
        elf = bytearray(64)
        elf[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', elf, 18, 183)
        for name in ('emulator', 'qemu/linux-aarch64/qemu-system-aarch64-headless'):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(elf)
            p.chmod(0o755)
        (self.root / 'package.xml').write_text('<repository><localPackage><revision><major>35</major><minor>3</minor><micro>8</micro></revision></localPackage></repository>')
        (self.root / 'source.properties').write_text('Pkg.Revision=35.3.8\n')
        self.metadata = {
            'source_repository': 'https://android.googlesource.com/platform/external/qemu',
            'manifest_repository': 'https://android.googlesource.com/platform/manifest',
            'source_revision': '1' * 40,
            'distribution_revision': '35.3.8',
            'manifest_revision': '2' * 40,
            'build_command': 'test fixture, not a real build',
            'toolchain_inputs': ['test fixture'],
            'patches': ['test fixture'],
        }
        self.save()

    def save(self):
        self.metadata['files_sha256'] = {
            p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.root.rglob('*') if p.is_file() and not p.is_symlink()
        }
        self.provenance.write_text(json.dumps(self.metadata))

    def verify(self):
        module.verify(self.root, self.provenance)

    def test_valid_inventory(self):
        self.verify()

    def test_reject_changed_file(self):
        (self.root / 'emulator').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            self.verify()

    def test_reject_extra_file(self):
        (self.root / 'extra').write_text('unrecorded')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            self.verify()

    def test_reject_symlink(self):
        (self.root / 'link').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            self.verify()

    def test_reject_other_publisher(self):
        self.metadata['source_repository'] = 'https://example.org/emulator'
        self.save()
        with self.assertRaisesRegex(ValueError, 'Google upstream'):
            self.verify()

    def test_reject_wrong_architecture(self):
        p = self.root / 'emulator'
        data = bytearray(p.read_bytes())
        struct.pack_into('<H', data, 18, 62)
        p.write_bytes(data)
        self.save()
        with self.assertRaisesRegex(ValueError, 'ARM64 ELF'):
            self.verify()

    def test_reject_foreign_elf_in_optional_backend(self):
        path = self.root / 'lib64/gles_optional/libEGL.so'
        path.parent.mkdir(parents=True)
        data = bytearray((self.root / 'emulator').read_bytes())
        struct.pack_into('<H', data, 18, 62)
        path.write_bytes(data)
        self.save()
        with self.assertRaisesRegex(ValueError, 'native ARM64 ELF'):
            self.verify()

    def test_reject_relabelled_provenance(self):
        self.metadata['distribution_revision'] = '99.0.0'
        self.save()
        with self.assertRaisesRegex(ValueError, 'unchanged source.properties'):
            self.verify()

    def test_reject_relabelled_sdk_registration(self):
        (self.root / 'package.xml').write_text('<repository><localPackage><revision><major>99</major><minor>0</minor><micro>0</micro></revision></localPackage></repository>')
        self.save()
        with self.assertRaisesRegex(ValueError, 'SDK registration revision'):
            self.verify()

    def test_reject_missing_provenance(self):
        self.metadata.pop('toolchain_inputs')
        self.save()
        with self.assertRaisesRegex(ValueError, 'toolchain_inputs'):
            self.verify()
