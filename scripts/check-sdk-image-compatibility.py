#!/usr/bin/env python3
"""Fail if a system image requires a newer emulator than the one built.

Accepts the SDK repository listing (before install; stable channel only) or the
installed image's package.xml (after install; exactly what sdkmanager installed).
"""
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


def check(repository, provenance, api):
    metadata = json.loads(provenance.read_text())
    version = metadata['distribution_revision']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid recorded emulator revision')
    actual = tuple(map(int, version.split('.')))
    package = f'system-images;android-{api};google_apis;arm64-v8a'
    root = ET.fromstring(repository.read_bytes())
    matches = [p for p in root.iter('localPackage') if p.get('path') == package]
    if not matches:
        # sdkmanager installs from the stable channel by default; ignore beta/canary entries.
        matches = [p for p in root.iter('remotePackage')
                   if p.get('path') == package and p.find('channelRef') is not None
                   and p.find('channelRef').get('ref') == 'channel-0']
    if len(matches) != 1:
        raise ValueError('Expected exactly one stable official system-image package')
    for dependency in matches[0].findall('./dependencies/dependency'):
        if dependency.get('path') != 'emulator':
            continue
        revision = dependency.find('min-revision')
        if revision is None:
            continue
        minimum = tuple(int(revision.findtext(k, '0')) for k in ('major', 'minor', 'micro'))
        if actual < minimum:
            required = '.'.join(map(str, minimum))
            raise ValueError(f'API {api} requires emulator >= {required}; source build is {version}. Refusing SDK replacement or version spoofing.')
    print(f'API {api} declared emulator dependency satisfied by source build {version}')


if __name__ == '__main__':
    try:
        check(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]))
    except (ValueError, KeyError, OSError, ET.ParseError) as error:
        sys.exit(str(error))
