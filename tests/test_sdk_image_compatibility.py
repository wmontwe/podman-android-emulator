import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/check-sdk-image-compatibility.py'
spec = importlib.util.spec_from_file_location('sdk_compatibility', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SdkCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.repo = root / 'repository.xml'
        self.meta = root / 'provenance.json'
        self.repo.write_text('''<repository><remotePackage path="system-images;android-36;google_apis;arm64-v8a">
<dependencies><dependency path="emulator"><min-revision><major>35</major><minor>4</minor><micro>9</micro></min-revision></dependency></dependencies>
<channelRef ref="channel-0"/></remotePackage>
<remotePackage path="system-images;android-36;google_apis;arm64-v8a">
<dependencies><dependency path="emulator"><min-revision><major>99</major><minor>0</minor><micro>0</micro></min-revision></dependency></dependencies>
<channelRef ref="channel-1"/></remotePackage></repository>''')

    def test_refuses_older_source_build(self):
        self.meta.write_text(json.dumps({'distribution_revision': '35.3.8'}))
        with self.assertRaisesRegex(ValueError, 'Refusing SDK replacement'):
            module.check(self.repo, self.meta, 36)

    def test_accepts_equal_or_newer(self):
        for version in ('35.4.9', '35.6.2', '36.1.0'):
            with self.subTest(version=version):
                self.meta.write_text(json.dumps({'distribution_revision': version}))
                module.check(self.repo, self.meta, 36)

    def test_ignores_non_stable_channels(self):
        self.meta.write_text(json.dumps({'distribution_revision': '37.2.12'}))
        module.check(self.repo, self.meta, 36)

    def test_checks_installed_package(self):
        installed = Path(self.temp.name) / 'package.xml'
        installed.write_text('''<repository><localPackage path="system-images;android-36;google_apis;arm64-v8a">
<dependencies><dependency path="emulator"><min-revision><major>38</major><minor>0</minor><micro>0</micro></min-revision></dependency></dependencies>
</localPackage></repository>''')
        self.meta.write_text(json.dumps({'distribution_revision': '37.2.12'}))
        with self.assertRaisesRegex(ValueError, 'requires emulator >= 38.0.0'):
            module.check(installed, self.meta, 36)

    def test_refuses_missing_image(self):
        self.meta.write_text(json.dumps({'distribution_revision': '35.6.2'}))
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            module.check(self.repo, self.meta, 99)
