#!/usr/bin/env python3
"""Report upstream updates that Dependabot cannot track.

Compares upstream-watch.json with Google's SDK repository (stable emulator,
SDK command-line tools, the Android system image) and Docker Hub (Ubuntu base
image digest). Prints one JSON object per available update; prints nothing when
everything is current. It never changes the repository.
"""
import argparse
import json
from pathlib import Path
import re
import urllib.request
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
SDK_REPOSITORY = 'https://dl.google.com/android/repository/repository2-3.xml'
SYSTEM_IMAGES = 'https://dl.google.com/android/repository/sys-img/google_apis/sys-img2-4.xml'
STABLE = 'channel-0'


def fetch(url, headers=None):
    request = urllib.request.Request(url, headers={'User-Agent': 'upstream-update-check', **(headers or {})})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(), response.headers


def _stable(root, path):
    return [p for p in root.iter('remotePackage')
            if p.get('path') == path and p.find('channelRef') is not None
            and p.find('channelRef').get('ref') == STABLE]


def _version(package):
    revision = package.find('revision')
    return tuple(int(revision.findtext(k) or 0) for k in ('major', 'minor', 'micro'))


def latest_emulator(repository):
    packages = _stable(ET.fromstring(repository), 'emulator')
    if not packages:
        raise ValueError('No stable emulator package in SDK repository')
    return '.'.join(map(str, max(_version(p) for p in packages)))


def latest_cmdline_tools(repository):
    builds = []
    for package in _stable(ET.fromstring(repository), 'cmdline-tools;latest'):
        for url in package.iterfind('archives/archive/complete/url'):
            match = re.fullmatch(r'commandlinetools-linux-(\d+)_latest\.zip', url.text or '')
            if match:
                builds.append(int(match[1]))
    if not builds:
        raise ValueError('No stable Linux SDK command-line tools in SDK repository')
    return str(max(builds))


def system_image_revision(images, path):
    packages = _stable(ET.fromstring(images), path)
    if len(packages) != 1:
        raise ValueError(f'Expected one stable {path} package, found {len(packages)}')
    return _version(packages[0])[0]


def base_image_digest(reference):
    match = re.fullmatch(r'docker\.io/library/([a-z0-9._-]+):([A-Za-z0-9._-]+)', reference)
    if not match:
        raise ValueError(f'Unsupported base image reference: {reference}')
    name, tag = match.groups()
    token, _ = fetch(f'https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/{name}:pull')
    accept = 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json'
    request = urllib.request.Request(
        f'https://registry-1.docker.io/v2/library/{name}/manifests/{tag}', method='HEAD',
        headers={'Authorization': 'Bearer ' + json.loads(token)['token'], 'Accept': accept,
                 'User-Agent': 'upstream-update-check'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.headers['Docker-Content-Digest']


def _newer(a, b):
    return tuple(map(int, a.split('.'))) > tuple(map(int, b.split('.')))


def updates(watch, repository, images, digest):
    found = []
    emulator = latest_emulator(repository)
    # Compare with the source version actually built, not the SDK binary seen when it was chosen.
    if _newer(emulator, watch['emulator_source']):
        found.append({'component': 'emulator', 'current': watch['emulator_source'], 'available': emulator,
                      'action': 'Build the newest published stable emulator source locally and publish a new release'})
    tools = latest_cmdline_tools(repository)
    if int(tools) > int(watch['cmdline_tools_build']):
        found.append({'component': 'cmdline-tools', 'current': watch['cmdline_tools_build'], 'available': tools,
                      'action': 'Update CMDLINE_TOOLS_VERSION in Containerfile.local'})
    image = watch['system_image']
    revision = system_image_revision(images, image['path'])
    if revision > image['revision']:
        found.append({'component': 'system-image', 'current': image['revision'], 'available': revision,
                      'action': f'Rebuild Containerfile.local to get {image["path"]} revision {revision}'})
    base = watch['base_image']
    if digest != base['digest']:
        found.append({'component': 'base-image', 'current': base['digest'], 'available': digest,
                      'action': f'Update the {base["reference"]} digest in the Containerfiles and publish a new release revision'})
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--watch', type=Path, default=REPO / 'upstream-watch.json')
    args = parser.parse_args()
    watch = json.loads(args.watch.read_text())
    repository, _ = fetch(SDK_REPOSITORY)
    images, _ = fetch(SYSTEM_IMAGES)
    digest = base_image_digest(watch['base_image']['reference'])
    for update in updates(watch, repository, images, digest):
        print(json.dumps(update))


if __name__ == '__main__':
    main()
