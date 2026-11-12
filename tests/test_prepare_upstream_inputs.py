"""Synthetic staging/provenance tests; no executable inputs are run."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/prepare-upstream-inputs.py'
spec = importlib.util.spec_from_file_location('prepare_upstream', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PrepareUpstreamTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.records = self.root / 'records'
        self.records.mkdir()
        self.archive = self.root / 'emulator.zip'
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('emulator/source.properties', 'Pkg.Revision=35.3.8\n')
        self.archive_hash = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.revision = '1' * 40
        manifest = b'synthetic manifest'
        (self.records / 'resolved-manifest.xml').write_bytes(manifest)
        (self.records / 'upstream-source.lock.json').write_text(json.dumps({
            'qemu_revision': self.revision,
            'manifest_sha256': hashlib.sha256(manifest).hexdigest(),
            'manifest_repository': 'https://android.googlesource.com/platform/manifest',
            'manifest_revision': '2' * 40,
        }))
        (self.records / 'fetched-projects.json').write_text('[]')
        (self.records / 'builder-packages.txt').write_text('synthetic packages')
        self.patch_record('local-ipa-pci')

    def patch_record(self, name, revision=None, digest=None):
        patch = b'synthetic source patch'
        (self.records / (name + '.patch')).write_bytes(patch)
        (self.records / (name + '.json')).write_text(json.dumps({
            'source_revision': revision or self.revision,
            'patch_sha256': digest or hashlib.sha256(patch).hexdigest(),
            'description': name,
        }))

    def prepare(self):
        destination = self.root / 'staged'
        module.prepare(self.archive, self.archive_hash, self.records, destination)
        return json.loads((destination / 'provenance.json').read_text())

    def test_legacy_record_remains_stageable(self):
        self.assertEqual(len(self.prepare()['patches']), 1)

    def test_actual_resume_command_is_preserved(self):
        command = 'verified incremental resume; compile jobs=1; link pool=1'
        (self.records / 'upstream-build-command.txt').write_text(command + '\n')
        self.assertEqual(self.prepare()['build_command'], command)

    def test_uuid_patch_is_preserved(self):
        self.patch_record('local-uuid-pic')
        metadata = self.prepare()
        self.assertEqual(len(metadata['patches']), 2)
        self.assertEqual(metadata['patches'][1]['description'], 'local-uuid-pic')

    def gfx_record(self):
        self.patch_record('local-gfxstream-process-gl', revision='5' * 40)
        path = self.records / 'local-gfxstream-process-gl.json'
        record = json.loads(path.read_text())
        record['source_repository'] = 'https://android.googlesource.com/platform/hardware/google/gfxstream'
        path.write_text(json.dumps(record))
        (self.records / 'fetched-projects.json').write_text(json.dumps([
            {'path': 'hardware/google/gfxstream', 'revision': '5' * 40}]))
        return path

    def test_gfxstream_patch_is_preserved(self):
        self.gfx_record()
        self.assertEqual(self.prepare()['patches'][-1]['description'], 'local-gfxstream-process-gl')

    def test_gfxstream_pin_must_match(self):
        self.gfx_record()
        (self.records / 'fetched-projects.json').write_text('[]')
        with self.assertRaisesRegex(ValueError, 'Gfxstream source and patch'):
            self.prepare()

    def test_gfxstream_patch_hash_must_match(self):
        self.gfx_record()
        (self.records / 'local-gfxstream-process-gl.patch').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Gfxstream source patch hash'):
            self.prepare()

    def test_uuid_revision_must_match(self):
        self.patch_record('local-uuid-pic', revision='3' * 40)
        with self.assertRaisesRegex(ValueError, 'UUID source and patch'):
            self.prepare()

    def test_uuid_patch_hash_must_match(self):
        self.patch_record('local-uuid-pic', digest='4' * 64)
        with self.assertRaisesRegex(ValueError, 'UUID source patch hash'):
            self.prepare()
