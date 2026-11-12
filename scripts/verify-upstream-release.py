#!/usr/bin/env python3
"""Enforce the selected stable-source pins; this is not provenance authentication."""
import argparse
import json
from pathlib import Path
import re


def verify(target, provenance):
    if (target.get('release_policy') != 'latest-published-stable-source'
            or target.get('sdk_channel') != 'channel-0'
            or target.get('allow_beta_or_rc') is not False
            or target.get('allow_version_relabeling') is not False):
        raise ValueError('Production builds require the stable-only release policy')
    if target.get('published_source_verified') is not True:
        raise ValueError('Published stable source is not verified; refusing production build')
    branch = target.get('source_release_branch')
    kind = target.get('source_ref_type', 'release-branch')
    if kind == 'published-stable-commit':
        if target.get('source_designation') != 'stable':
            raise ValueError('An explicitly published Stable commit is required')
    elif kind == 'release-branch':
        if not isinstance(branch, str) or not re.fullmatch(r'emu-\d+(?:-\d+)?(?:-stable)?-release', branch):
            raise ValueError('A published emulator release branch is required')
    else:
        raise ValueError('Unsupported source reference type')
    for field in ('source_revision', 'resolved_manifest_revision'):
        value = target.get(field)
        if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}', value):
            raise ValueError('Stable source pins are incomplete: ' + field)
    digest = target.get('manifest_sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('Stable manifest SHA-256 is incomplete')
    version = target.get('source_version')
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid selected stable version')
    expected = {
        'distribution_revision': version,
        'release_branch': branch,
        'source_ref_type': kind,
        'manifest_sha256': target.get('manifest_sha256'),
        'source_repository': 'https://android.googlesource.com/platform/external/qemu',
        'manifest_repository': 'https://android.googlesource.com/platform/manifest',
        'source_revision': target['source_revision'],
        'manifest_revision': target['resolved_manifest_revision'],
    }
    for field, value in expected.items():
        if provenance.get(field) != value:
            raise ValueError('Distribution does not match selected stable release: ' + field)
    print('Published release-source version and pins match; SDK binary equivalence is not claimed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', type=Path)
    parser.add_argument('provenance', type=Path)
    args = parser.parse_args()
    try:
        verify(json.loads(args.target.read_text()), json.loads(args.provenance.read_text()))
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')
