import importlib.util
import json
from pathlib import Path
import re
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_updates', REPO / 'scripts/check-upstream-updates.py')
check_updates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_updates)

WATCH = json.loads((REPO / 'upstream-watch.json').read_text())


def package(path, channel, major, minor=0, micro=0, url=None):
    archive = f'<archives><archive><complete><url>{url}</url></complete></archive></archives>' if url else ''
    return (f'<remotePackage path="{path}"><revision><major>{major}</major><minor>{minor}</minor>'
            f'<micro>{micro}</micro></revision><channelRef ref="{channel}"/>{archive}</remotePackage>')


def repository(*packages):
    return ('<repository>' + ''.join(packages) + '</repository>').encode()


SDK = repository(
    package('emulator', 'channel-0', 37, 3, 10),
    package('emulator', 'channel-2', 99, 0, 0),
    package('cmdline-tools;latest', 'channel-0', 23, url='commandlinetools-linux-11076708_latest.zip'),
    package('cmdline-tools;latest', 'channel-1', 24, url='commandlinetools-linux-99999999_latest.zip'))
IMAGES = repository(package(WATCH['system_image']['path'], 'channel-0', WATCH['system_image']['revision']))


class UpstreamUpdatesTest(unittest.TestCase):
    def test_current_versions_report_nothing(self):
        self.assertEqual(check_updates.updates(WATCH, SDK, IMAGES, WATCH['base_image']['digest']), [])

    def test_only_stable_channel_counts(self):
        self.assertEqual(check_updates.latest_emulator(SDK), '37.3.10')
        self.assertEqual(check_updates.latest_cmdline_tools(SDK), '11076708')

    def test_reports_each_newer_component(self):
        sdk = repository(package('emulator', 'channel-0', 37, 4, 1),
                         package('cmdline-tools;latest', 'channel-0', 24, url='commandlinetools-linux-16111833_latest.zip'))
        images = repository(package(WATCH['system_image']['path'], 'channel-0', 8))
        found = {u['component']: u['available'] for u in check_updates.updates(WATCH, sdk, images, 'sha256:' + 'f' * 64)}
        self.assertEqual(found, {'emulator': '37.4.1', 'cmdline-tools': '16111833',
                                 'system-image': 8, 'base-image': 'sha256:' + 'f' * 64})

    def test_sdk_binary_newer_than_built_source_is_reported(self):
        sdk = repository(package('emulator', 'channel-0', 37, 3, 11),
                         package('cmdline-tools;latest', 'channel-0', 23, url='commandlinetools-linux-11076708_latest.zip'))
        found = check_updates.updates(WATCH, sdk, IMAGES, WATCH['base_image']['digest'])
        self.assertEqual([(u['component'], u['current'], u['available']) for u in found],
                         [('emulator', '37.3.10', '37.3.11')])

    def test_watch_file_matches_repository_pins(self):
        reference = f'{WATCH["base_image"]["reference"]}@{WATCH["base_image"]["digest"]}'
        for name in ('Containerfile', 'Containerfile.builder', 'Containerfile.fetcher', 'Containerfile.graphics-builder'):
            self.assertIn(f'FROM {reference}\n', (REPO / name).read_text(), name)
        local = (REPO / 'Containerfile.local').read_text()
        self.assertEqual(re.search(r'ARG CMDLINE_TOOLS_VERSION=(\d+)', local)[1], WATCH['cmdline_tools_build'])
        target = json.loads((REPO / 'upstream-release-target.json').read_text())
        self.assertEqual(target['source_version'], WATCH['emulator_source'])


if __name__ == '__main__':
    unittest.main()
