"""Check manifest normalization without network, Git fetches, or source execution."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('resolve_sources', Path(__file__).resolve().parents[1] / 'scripts/resolve-upstream-sources.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SourceResolutionTests(unittest.TestCase):
    def parse(self, body):
        return module.selected_projects(('<manifest><default revision="emu-main-dev"/>' + body + '</manifest>').encode())

    def test_default_branch_is_preserved_for_resolution(self):
        result = self.parse('<project name="platform/external/qemu" path="external/qemu"/>')
        self.assertEqual(result[0].get('revision'), 'emu-main-dev')

    def test_equivalent_duplicate_project_merges_operations(self):
        result = self.parse('<project name="platform/external/qemu" path="external/qemu"/>'
                            '<project name="platform/external/qemu" path="external/qemu"><linkfile src="MODULE" dest="MODULE"/></project>')
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]), 1)

    def test_conflicting_duplicate_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Conflicting duplicate'):
            self.parse('<project name="platform/a" path="external/a" revision="main"/>'
                       '<project name="platform/a" path="external/a" revision="different"/>')

    def test_platform_groups_and_forbidden_binary_projects(self):
        result = self.parse('<project name="platform/a" path="a" groups="notdefault,platform-linux"/>'
                            '<project name="platform/b" path="b" groups="notdefault,platform-windows"/>'
                            '<project name="platform/prebuilts/android-emulator" path="emulator"/>')
        self.assertEqual([p.get('path') for p in result], ['a'])

    def test_copy_destination_escape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unsafe manifest'):
            self.parse('<project name="platform/a" path="a"><copyfile src="file" dest="../escape"/></project>')

    def test_included_manifests_are_not_silently_ignored(self):
        with self.assertRaisesRegex(ValueError, 'explicit resolution'):
            self.parse('<include name="more.xml"/>')
