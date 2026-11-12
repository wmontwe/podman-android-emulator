"""Check host launcher policy with a fake Podman; no container is created."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/run-android'


class RuntimeLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / 'calls.jsonl'
        podman = self.root / 'podman'
        podman.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['PODMAN_TEST_LOG'], 'a') as f:
    f.write(json.dumps(args) + '\\n')
if args[0] == 'info': print(os.environ.get('PODMAN_TEST_ROOTLESS', 'true'))
if args[:2] == ['image', 'exists']: sys.exit(int(os.environ.get('PODMAN_TEST_MISSING_IMAGE', '0')))
if args[:2] == ['volume', 'create'] and os.environ.get('PODMAN_TEST_EXISTING_VOLUME') == '1' and '--ignore' not in args: sys.exit(125)
''')
        podman.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ['PATH'],
                        PODMAN_TEST_LOG=str(self.log))
        for key in ('ANDROID_IMAGE', 'ANDROID_CONTAINER_NAME', 'ANDROID_DATA_VOLUME', 'ANDROID_ADB_PORT'):
            self.env.pop(key, None)

    def run_launcher(self):
        result = subprocess.run(['bash', str(SCRIPT)], env=self.env, capture_output=True, text=True)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return result, calls

    def test_resource_and_security_arguments(self):
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = calls[-1]
        for expected in ('--memory=8g', '--memory-swap=8g', '--cpus=4', '--device=/dev/kvm', '--pull=never'):
            self.assertIn(expected, args)
        self.assertEqual([a for a in args if a.startswith('--device')], ['--device=/dev/kvm'])
        self.assertFalse(any(a.startswith(('--privileged', '--cap-add', '--security-opt')) for a in args))
        self.assertIn('127.0.0.1:5555:15555', args)
        self.assertIn('ANDROID_MEMORY_MB=4096', args)
        self.assertIn('ANDROID_CORES=4', args)
        self.assertIn('android-api36-data:/root/.android', args)

    def test_reuses_existing_volume_without_recreating_data(self):
        self.env['PODMAN_TEST_EXISTING_VOLUME'] = '1'
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(['volume', 'create', '--ignore', 'android-api36-data'], calls)

    def test_refuses_rootful_before_creating_state(self):
        self.env['PODMAN_TEST_ROOTLESS'] = 'false'
        result, calls = self.run_launcher()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)

    def test_refuses_missing_image_without_pull_or_volume(self):
        self.env['PODMAN_TEST_MISSING_IMAGE'] = '1'
        result, calls = self.run_launcher()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c[0] in ('run', 'pull', 'volume') for c in calls))
