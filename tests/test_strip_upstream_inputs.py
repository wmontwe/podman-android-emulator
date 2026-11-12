"""Exercise component removal with synthetic fixtures; never execute binaries."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


strip_module = load('strip_upstream', 'strip-upstream-inputs.py')
verify_module = load('verify_upstream_strip', 'verify-upstream-input.py')

FILES = (
    'emulator', 'qemu/linux-aarch64/qemu-system-aarch64-headless', 'lib64/libglib2_linux-aarch64.so',
    'lib64/qt/lib/libQt6CoreAndroidEmu.so.6', 'lib64/qt/plugins/platforms/libqxcbAndroidEmu.so',
    'qemu/linux-aarch64/qemu-system-aarch64', 'emulator-check',
    'qemu/linux-aarch64/qemu-system-armel', 'qemu/linux-aarch64/qemu-system-armel-headless',
    'lib64/glibc-2.29.tgz', 'patchelf.tgz', 'linux-aarch64-fixgcc.sh',
    'lib/pc-bios/bios.bin', 'lib/pc-bios/keymaps/en-us', 'lib/hardware-properties.ini',
    'lib64/gles_llvmpipe/libGLESv2.so', 'lib64/gles_llvmpipe/dri/swrast_dri.so',
)
SEP = '=' * 59
NOTICE_TXT = '\n'.join([
    SEP, 'Notices for file(s):', './emulator', './emulator-check', 'android-emu-shared.so',
    'The notices is included for the library: gfxstream', '', SEP, 'Apache text', '',
    SEP, 'Notices for file(s):', './emulator-check', './qemu/linux-aarch64/qemu-system-aarch64',
    'The notices is included for the library: Qt Widgets', '', SEP, 'LGPL text', '',
    SEP, 'Notices for file(s):', './emulator', 'lib64/qt/lib/libQt6CoreAndroidEmu.so.6',
    'The notices is included for the library: Qt 6', '', SEP, 'LGPL text', '',
    SEP, 'Notices for file(s):', './emulator',
    'The notices is included for the library: ffmpeg', '', SEP, 'GPL text', '',
])
NOTICE_CSV = '\n'.join([
    'External Library Name, Link to License, License Name, Binaries using the license, URL',
    'gfxstream, https://l, Apache-2.0, ./emulator ./emulator-check, https://u',
    'Qt Widgets, https://l, LGPL-3.0-only, ./emulator-check ./qemu/linux-aarch64/qemu-system-aarch64, https://u',
    'Qt 6, https://l, LGPL-3.0-only, ./emulator lib64/qt/lib/libQt6CoreAndroidEmu.so.6, https://u',
    'bios, https://l, LGPL-2.0-or-later, ./emulator, https://u',
    'ffmpeg, https://l, GPL-2.0-or-later, ./emulator, '
    'https://android.googlesource.com/platform/prebuilts/android-emulator-build/archive/+/refs/heads/emu-master-dev/ffmpeg-3.4.5.tar.xz',
    '',
])
CONTENT = {'NOTICE.txt': NOTICE_TXT, 'NOTICE.csv': NOTICE_CSV}


class StripTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.inputs = Path(self.temp.name)
        self.root = self.inputs / 'emulator'
        for name in FILES + tuple(CONTENT):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(CONTENT.get(name, name))
        self.meta = {'files_sha256': {name: hashlib.sha256(CONTENT.get(name, name).encode()).hexdigest()
                                      for name in FILES + tuple(CONTENT)},
                     'excluded_components': [{'component': 'earlier', 'reason': 'kept', 'files_sha256': {}}]}
        self.write_meta()

    def write_meta(self):
        (self.inputs / 'provenance.json').write_text(json.dumps(self.meta))

    def read_meta(self):
        return json.loads((self.inputs / 'provenance.json').read_text())

    def test_removes_and_records_components(self):
        strip_module.strip(self.inputs)
        meta = self.read_meta()
        remaining = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file())
        self.assertEqual(remaining, sorted(['emulator', 'qemu/linux-aarch64/qemu-system-aarch64-headless',
                                            'lib64/libglib2_linux-aarch64.so', 'lib/hardware-properties.ini',
                                            'NOTICE.txt', 'NOTICE.csv']))
        self.assertEqual(sorted(meta['files_sha256']), remaining)
        self.assertFalse((self.root / 'lib64/qt').exists())
        self.assertFalse((self.root / 'lib/pc-bios').exists())
        self.assertEqual(meta['excluded_components'][0]['component'], 'earlier')
        recorded = {name for entry in meta['excluded_components'][1:] for name in entry['files_sha256']}
        self.assertEqual(recorded, set(FILES) - set(remaining))

    def test_updates_notices(self):
        strip_module.strip(self.inputs)
        txt = (self.root / 'NOTICE.txt').read_text()
        self.assertNotIn('Qt Widgets', txt)
        self.assertNotIn('emulator-check', txt)
        self.assertNotIn('lib64/qt', txt)
        self.assertIn('library: gfxstream', txt)
        self.assertIn('library: ffmpeg', txt)
        self.assertNotIn('Qt 6', txt)
        self.assertNotIn('LGPL text', txt)
        csv = (self.root / 'NOTICE.csv').read_text().splitlines()
        self.assertEqual(csv[1:], [
            'gfxstream, https://l, Apache-2.0, ./emulator, https://u',
            'ffmpeg, https://l, GPL-2.0-or-later, ./emulator, '
            'https://android.googlesource.com/platform/prebuilts/android-emulator-build/archive/+/refs/heads/emu-master-dev/ffmpeg-4.4.2.tar.gz'])
        update = self.read_meta()['notice_update']['files']
        self.assertEqual(update['NOTICE.txt']['dropped_entries'], ['Qt Widgets', 'Qt 6'])
        self.assertEqual(update['NOTICE.csv']['dropped_entries'], ['Qt Widgets', 'Qt 6', 'bios'])
        self.assertEqual(update['NOTICE.txt']['before_sha256'], hashlib.sha256(NOTICE_TXT.encode()).hexdigest())

    def test_keeps_notice_when_shipped_file_contains_code(self):
        (self.root / 'emulator').write_bytes(b'\x7fELF ... _ZN7QObject ...')
        self.meta['files_sha256']['emulator'] = hashlib.sha256((self.root / 'emulator').read_bytes()).hexdigest()
        self.write_meta()
        with self.assertRaisesRegex(ValueError, 'emulator contains Qt 6 code'):
            strip_module.strip(self.inputs)
        self.assertTrue((self.root / 'patchelf.tgz').exists())

    def test_refuses_second_run(self):
        strip_module.strip(self.inputs)
        with self.assertRaisesRegex(ValueError, 'Already removed'):
            strip_module.strip(self.inputs)

    def test_refuses_changed_file_without_removing_anything(self):
        (self.root / 'patchelf.tgz').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'differs from provenance'):
            strip_module.strip(self.inputs)
        self.assertTrue((self.root / 'lib64/qt/lib/libQt6CoreAndroidEmu.so.6').exists())

    def test_refuses_missing_component(self):
        (self.root / 'lib/pc-bios/bios.bin').unlink()
        (self.root / 'lib/pc-bios/keymaps/en-us').unlink()
        for name in ('lib/pc-bios/bios.bin', 'lib/pc-bios/keymaps/en-us'):
            del self.meta['files_sha256'][name]
        self.write_meta()
        with self.assertRaisesRegex(ValueError, 'Nothing to remove for x86 firmware'):
            strip_module.strip(self.inputs)

    def test_verifier_rejects_exactly_the_stripped_paths(self):
        stripped = {path for spec in strip_module.COMPONENTS for path in spec['paths']}
        self.assertEqual(stripped, set(verify_module.UNSHIPPED))


if __name__ == '__main__':
    unittest.main()
