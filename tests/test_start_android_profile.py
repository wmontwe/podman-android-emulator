"""Exercise startup preflight/profile selection without launching an emulator."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/start-android'


class StartupProfileTests(unittest.TestCase):
    def run_profile(self, helper=False, platforms=True):
        with tempfile.TemporaryDirectory() as temporary:
            sdk = Path(temporary)
            for name in ('platform-tools', 'emulator', 'system-images/android-36/google_apis/arm64-v8a'):
                (sdk / name).mkdir(parents=True)
            if platforms:
                (sdk / 'platforms').mkdir()
            (sdk / 'system-images/android-36/google_apis/arm64-v8a/package.xml').write_text('<test/>')
            if helper:
                path = sdk / 'emulator/netsimd'
                path.write_text('#!/bin/sh\nexit 99\n')
                path.chmod(0o755)
            # Stop before AVD creation: this tests only SDK preflight and the
            # profile array. The fake helper must never be executed.
            text = SCRIPT.read_text()
            marker = 'config=/root/.android/avd/android.avd/config.ini'
            self.assertEqual(text.count(marker), 1)
            prefix = text.split(marker)[0]
            env = dict(os.environ, ANDROID_HOME=str(sdk), ANDROID_API='36')
            return subprocess.run(['bash', '-c', prefix + '\ndeclare -p feature_args\n'],
                                  env=env, capture_output=True, text=True)

    def test_missing_helper_uses_explicit_legacy_profile(self):
        result = self.run_profile()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('[1]="-Vulkan,-WiFiPacketStream,-BluetoothEmulation")', result.stdout)
        self.assertIn('netsimd unavailable', result.stderr)

    def test_present_helper_does_not_force_disable_features(self):
        result = self.run_profile(helper=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('WiFiPacketStream', result.stdout)
        self.assertIn('-Vulkan,-BluetoothEmulation', result.stdout)
        self.assertNotIn('netsimd unavailable', result.stderr)

    def test_incomplete_sdk_still_fails_closed(self):
        result = self.run_profile(platforms=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Incomplete SDK layout', result.stderr)
