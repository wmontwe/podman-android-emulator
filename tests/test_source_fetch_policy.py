"""Test source-fetch policy without contacting any remote repository."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/fetch-upstream-sources.py'
spec = importlib.util.spec_from_file_location('fetch_sources', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SourceFetchPolicyTests(unittest.TestCase):
    def test_rejects_path_traversal_and_absolute_paths(self):
        for value in ('../escape', '/host', '', '-option', 'a/../../host'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.relative_path(value)

    def test_accepts_relative_project_path(self):
        self.assertEqual(str(module.relative_path('external/qemu')), 'external/qemu')

    def test_resolved_manifest_preserves_project_layout(self):
        upstream = b'<manifest><project name="platform/a" path="a" revision="main"/></manifest>'
        resolved = b'<manifest><project name="platform/a" path="a" revision="1111111111111111111111111111111111111111"/></manifest>'
        module.validate_resolved_manifest(upstream, resolved, {'excluded_projects': []})

    def test_resolved_manifest_cannot_add_projects(self):
        upstream = b'<manifest><project name="platform/a" path="a"/></manifest>'
        resolved = b'<manifest><project name="platform/a" path="a"/><project name="platform/b" path="b"/></manifest>'
        with self.assertRaisesRegex(ValueError, 'project selection'):
            module.validate_resolved_manifest(upstream, resolved, {'excluded_projects': []})

    def test_resolved_manifest_cannot_replace_upstream_immutable_dependency(self):
        upstream = b'<manifest><project name="platform/a" path="a" revision="1111111111111111111111111111111111111111"/></manifest>'
        resolved = b'<manifest><project name="platform/a" path="a" revision="2222222222222222222222222222222222222222"/></manifest>'
        with self.assertRaisesRegex(ValueError, 'immutable upstream pin'):
            module.validate_resolved_manifest(upstream, resolved, {'excluded_projects': []})

    def test_rejects_other_origin_before_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lock = root / 'lock.json'
            lock.write_text(json.dumps({'source_origin': 'https://example.org/'}))
            with mock.patch.object(module.urllib.request, 'urlopen') as remote:
                with self.assertRaises(ValueError):
                    module.fetch(lock, root / 'source')
                remote.assert_not_called()

    def test_rejects_branch_instead_of_immutable_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lock = root / 'lock.json'
            lock.write_text(json.dumps({
                'source_origin': 'https://android.googlesource.com/',
                'manifest_repository': 'https://android.googlesource.com/platform/manifest',
                'manifest_revision': 'emu-master-dev',
            }))
            with mock.patch.object(module.urllib.request, 'urlopen') as remote:
                with self.assertRaises(ValueError):
                    module.fetch(lock, root / 'source')
                remote.assert_not_called()
