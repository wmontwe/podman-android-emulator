#!/usr/bin/env python3
"""Fetch immutable Google source projects without executing Repo hooks or source."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import urllib.request
import xml.etree.ElementTree as ET


def git(directory, *args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1',
               GIT_CONFIG_GLOBAL='/dev/null')
    command = ['git', '-c', 'core.hooksPath=/dev/null',
               '-c', 'protocol.file.allow=never', '-c', 'credential.helper=',
               '-C', str(directory), *args]
    process = subprocess.Popen(command, env=env, start_new_session=True)
    while True:
        try:
            status = process.wait(timeout=5)
            if status:
                raise subprocess.CalledProcessError(status, command)
            return
        except subprocess.TimeoutExpired:
            if shutil.disk_usage(directory).free < 6 * 1024**3:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise RuntimeError('Git stopped: less than 6 GiB free; partial checkout preserved')


def relative_path(value):
    p = PurePosixPath(value)
    if not value or p.is_absolute() or '..' in p.parts or value.startswith('-'):
        raise ValueError(f'Unsafe manifest path: {value}')
    return p


def manifest_layout(data, excluded):
    """Normalize selected project structure, not floating revision values."""
    document = ET.fromstring(data)
    if document.findall('include') or document.findall('extend-project'):
        raise ValueError('Included/extended manifests require separate review')
    result = {}
    for project in document.findall('project'):
        groups = set(project.get('groups', '').split(','))
        if ('notdefault' in groups and 'platform-linux' not in groups) or project.get('name') in excluded:
            continue
        for key in ('name', 'path'):
            relative_path(project.get(key, ''))
        attrs = tuple(sorted((k, v) for k, v in project.attrib.items() if k != 'revision'))
        path = project.get('path')
        if path in result and result[path]['attributes'] != attrs:
            raise ValueError('Conflicting duplicate project')
        record = result.setdefault(path, {'attributes': attrs, 'operations': set()})
        for child in project:
            if child.tag not in ('copyfile', 'linkfile'):
                raise ValueError('Unreviewed manifest operation')
            relative_path(child.get('src', ''))
            relative_path(child.get('dest', ''))
            record['operations'].add((child.tag, tuple(sorted(child.attrib.items()))))
    return result


def validate_resolved_manifest(upstream, resolved, lock):
    if manifest_layout(upstream, lock['excluded_projects']) != manifest_layout(resolved, lock['excluded_projects']):
        raise ValueError('Resolved manifest changes the upstream project selection or operations')
    actual = {p.get('path'): p for p in ET.fromstring(resolved).findall('project')}
    if len(actual) != len(ET.fromstring(resolved).findall('project')):
        raise ValueError('Resolved manifest contains duplicate paths')
    for project in ET.fromstring(upstream).findall('project'):
        original = project.get('revision', '')
        if project.get('path') not in actual or project.get('name') == 'platform/external/qemu':
            continue
        if re.fullmatch('[0-9a-f]{40}', original) and actual[project.get('path')].get('revision') != original:
            raise ValueError('Resolved manifest changes an immutable upstream pin')


def fetch(lock_path, destination, resolved_manifest=None):
    lock = json.loads(lock_path.read_text())
    origin = 'https://android.googlesource.com/'
    if lock['source_origin'] != origin or lock['manifest_repository'] != origin + 'platform/manifest':
        raise ValueError('Only the reviewed Google source origin is permitted')
    revision = lock['manifest_revision']
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Manifest revision must be immutable')
    url = f"{lock['manifest_repository']}/+/{revision}/default.xml?format=TEXT"
    response = urllib.request.urlopen(url, timeout=60)
    if not response.geturl().startswith(origin):
        raise ValueError('Unexpected manifest redirect')
    data = base64.b64decode(response.read(), validate=True)
    expected_upstream = lock.get('upstream_manifest_sha256', lock['manifest_sha256'])
    if hashlib.sha256(data).hexdigest() != expected_upstream:
        raise ValueError('Pinned upstream manifest SHA-256 mismatch')
    upstream = data
    if 'upstream_manifest_sha256' in lock:
        if resolved_manifest is None:
            raise ValueError('Independently resolved manifest must be supplied explicitly')
        data = resolved_manifest.read_bytes()
        if hashlib.sha256(data).hexdigest() != lock['manifest_sha256']:
            raise ValueError('Resolved manifest SHA-256 mismatch')
        validate_resolved_manifest(upstream, data, lock)
    elif resolved_manifest is not None:
        raise ValueError('Unexpected resolved manifest for direct upstream lock')
    manifest = ET.fromstring(data)
    if manifest.findall('include') or manifest.findall('extend-project'):
        raise ValueError('Included/extended manifests require separate review')
    projects = []
    for project in manifest.findall('project'):
        name = project.attrib['name']
        path = project.attrib['path']
        relative_path(name)
        relative_path(path)
        commit = project.attrib.get('revision', '')
        if not re.fullmatch('[0-9a-f]{40}', commit):
            raise ValueError(f'Unpinned project: {name}')
        if project.attrib.get('remote', 'aosp') != 'aosp':
            raise ValueError(f'Unexpected source remote: {name}')
        groups = set(project.attrib.get('groups', '').split(','))
        if ('notdefault' in groups and 'platform-linux' not in groups) or name in lock['excluded_projects']:
            continue
        projects.append((project, name, path, commit))
    qemu = next(c for _, n, _, c in projects if n == 'platform/external/qemu')
    if qemu != lock['qemu_revision']:
        raise ValueError('QEMU revision does not match lock')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'resolved-manifest.xml').write_bytes(data)
    if 'upstream_manifest_sha256' in lock:
        (destination / 'upstream-manifest.xml').write_bytes(upstream)
        records = resolved_manifest.parent / 'resolution-records.json'
        if not records.is_file():
            raise ValueError('Dependency resolution evidence is missing')
        if hashlib.sha256(records.read_bytes()).hexdigest() != lock.get('resolution_records_sha256'):
            raise ValueError('Dependency resolution evidence SHA-256 mismatch')
        shutil.copyfile(records, destination / 'resolution-records.json')
    (destination / 'upstream-source.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    completed = []
    for index, (project, name, path, commit) in enumerate(projects, 1):
        if shutil.disk_usage(destination).free < 6 * 1024**3:
            raise RuntimeError('Less than 6 GiB free; source fetch stopped without deleting state')
        target = destination / path
        # The workspace is dedicated to source checkout. Never follow a path
        # planted by a previous project outside that workspace.
        if not target.resolve().is_relative_to(destination.resolve()):
            raise ValueError(f'Checkout escapes source workspace: {path}')
        target.mkdir(parents=True, exist_ok=True)
        print(f'[{index}/{len(projects)}] {name} @ {commit}', flush=True)
        if not (target / '.git').exists():
            git(target, 'init')
            git(target, 'remote', 'add', 'origin', origin + name)
        else:
            actual_origin = subprocess.check_output(['git', '-C', str(target), 'remote', 'get-url', 'origin'], text=True).strip()
            if actual_origin != origin + name:
                raise ValueError(f'Unexpected existing Git remote: {path}')
        existing = subprocess.run(['git', '-C', str(target), 'rev-parse', '--verify', 'HEAD'],
                                  capture_output=True, text=True)
        if existing.returncode == 0 and existing.stdout.strip() == commit:
            git(target, 'diff', '--exit-code', 'HEAD', '--')
            print('  Reusing verified clean pinned checkout', flush=True)
        else:
            git(target, 'fetch', '--depth=1', '--no-tags', 'origin', commit)
            git(target, 'checkout', '--detach', commit)
        actual = subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != commit:
            raise ValueError(f'Revision mismatch: {path}')
        for child in project:
            if child.tag not in ('copyfile', 'linkfile'):
                raise ValueError(f'Unreviewed manifest operation: {child.tag}')
            src = target / str(relative_path(child.attrib['src']))
            dest = destination / str(relative_path(child.attrib['dest']))
            if not src.resolve().is_relative_to(target.resolve()) or not dest.resolve().is_relative_to(destination.resolve()):
                raise ValueError('Manifest copy/link escapes workspace')
            dest.parent.mkdir(parents=True, exist_ok=True)
            if child.tag == 'copyfile':
                shutil.copyfile(src, dest)
            else:
                if dest.is_symlink():
                    dest.unlink()
                dest.symlink_to(os.path.relpath(src, dest.parent))
        completed.append({'name': name, 'path': path, 'revision': actual})
        (destination / 'fetched-projects.json').write_text(json.dumps(completed, indent=2) + '\n')
    print(f'Fetched {len(completed)} pinned projects. No source build or Repo hooks executed.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--resolved-manifest', type=Path)
    args = parser.parse_args()
    fetch(args.lock, args.destination, args.resolved_manifest)
