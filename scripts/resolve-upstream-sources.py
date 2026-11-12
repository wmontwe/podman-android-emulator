#!/usr/bin/env python3
"""Resolve an independently pinned Google dependency candidate for a stable commit.

Metadata only: no source checkout, Repo hooks, compilers, or emulator execution.
Historical branch resolution is a compatibility hypothesis, not Google's release
manifest. The resulting pins must be built and runtime-tested.
"""
import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import urllib.request
import xml.etree.ElementTree as ET

ORIGIN = 'https://android.googlesource.com/'
EXCLUDED = {'platform/prebuilts/android-emulator',
            'platform/prebuilts/android-emulator-build/system-images'}


def command(directory, *args):
    if shutil.disk_usage(directory).free < 8 * 1024**3:
        raise RuntimeError('Less than 8 GiB free; metadata resolution stopped')
    env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1',
               GIT_TERMINAL_PROMPT='0')
    return subprocess.check_output(
        ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'credential.helper=',
         '-c', 'protocol.file.allow=never', '-C', str(directory), *args], env=env)


def metadata(repository, revision, path=None):
    suffix = '?format=JSON' if path is None else '/' + path + '?format=TEXT'
    url = ORIGIN + repository + '/+/' + revision + suffix
    with urllib.request.urlopen(url, timeout=60) as response:
        if not response.geturl().startswith(ORIGIN):
            raise ValueError('Unexpected metadata redirect')
        data = response.read(8 * 1024**2)
    return (json.loads(data.decode().split('\n', 1)[1]) if path is None
            else base64.b64decode(data, validate=True))


def selected_projects(data):
    root = ET.fromstring(data)
    if root.findall('include') or root.findall('extend-project'):
        raise ValueError('Included/extended manifests require explicit resolution')
    default = root.find('default')
    default_revision = default.get('revision') if default is not None else None
    projects = {}
    for item in root.findall('project'):
        attrs = dict(item.attrib)
        for field in ('name', 'path'):
            value = attrs[field]
            path = PurePosixPath(value)
            if not value or path.is_absolute() or '..' in path.parts or value.startswith('-'):
                raise ValueError('Unsafe project ' + field)
        if attrs.get('remote', 'aosp') != 'aosp':
            raise ValueError('Unexpected source remote')
        groups = set(attrs.get('groups', '').split(','))
        if attrs['name'] in EXCLUDED or ('notdefault' in groups and 'platform-linux' not in groups):
            continue
        attrs['revision'] = attrs.get('revision', default_revision)
        if not attrs['revision']:
            raise ValueError('Project lacks a revision')
        key = attrs['path']
        if key in projects:
            existing = projects[key]
            if existing.attrib != attrs:
                raise ValueError('Conflicting duplicate project: ' + key)
        else:
            existing = ET.Element('project', attrs)
            projects[key] = existing
        for child in item:
            if child.tag not in ('copyfile', 'linkfile'):
                raise ValueError('Unreviewed manifest operation')
            for field in ('src', 'dest'):
                value = child.get(field, '')
                if not value or PurePosixPath(value).is_absolute() or '..' in PurePosixPath(value).parts or value.startswith('-'):
                    raise ValueError('Unsafe manifest copy/link path')
            encoded = ET.tostring(child)
            if not any(ET.tostring(c) == encoded for c in existing):
                existing.append(ET.fromstring(encoded))
    return list(projects.values())


def resolve_project(project, workspace, cutoff, qemu_revision):
    name = project.get('name')
    revision = project.get('revision')
    if name == 'platform/external/qemu':
        return qemu_revision, {'method': 'explicit-published-stable-commit'}
    if re.fullmatch('[0-9a-f]{40}', revision):
        return revision, {'method': 'immutable-upstream-manifest-pin'}
    if revision.startswith('-') or '..' in revision or any(c.isspace() for c in revision):
        raise ValueError('Unsafe branch revision')
    ref = revision if revision.startswith('refs/') else 'refs/heads/' + revision
    directory = workspace / 'metadata' / (name.replace('/', '__') + '.git')
    directory.mkdir(parents=True, exist_ok=True)
    if not (directory / 'HEAD').exists():
        command(directory, 'init', '--bare')
        command(directory, 'remote', 'add', 'origin', ORIGIN + name)
    origin = command(directory, 'remote', 'get-url', 'origin').decode().strip()
    if origin != ORIGIN + name:
        raise ValueError('Unexpected cached origin')
    # Record the observed ref tip before fetching. Subsequent updates cannot
    # silently change this resolution run.
    observed = command(directory, 'ls-remote', '--exit-code', 'origin', ref).decode().split()
    if len(observed) != 2 or not re.fullmatch('[0-9a-f]{40}', observed[0]):
        raise ValueError('Could not resolve unique upstream ref: ' + name)
    anchor = observed[0]
    command(directory, 'fetch', '--depth=256', '--filter=tree:0', '--no-tags',
            'origin', anchor + ':refs/review/resolution-anchor')
    selected = command(directory, 'rev-list', '--first-parent', '-1',
                       '--before=' + cutoff, anchor).decode().strip()
    if not selected:
        command(directory, 'fetch', '--deepen=1024', '--filter=tree:0', '--no-tags', 'origin', anchor)
        selected = command(directory, 'rev-list', '--first-parent', '-1',
                           '--before=' + cutoff, anchor).decode().strip()
    if not re.fullmatch('[0-9a-f]{40}', selected):
        raise ValueError('History does not reach cutoff: ' + name)
    date = command(directory, 'show', '-s', '--format=%cI', selected).decode().strip()
    print(name + ' -> ' + selected + ' (' + date + ')', flush=True)
    return selected, {'method': 'first-parent-at-or-before-stable-commit-date',
                      'upstream_ref': ref, 'observed_tip': anchor, 'commit_date': date}


def resolve(workspace, manifest_revision, qemu_revision, expected_version, cutoff):
    workspace.mkdir(parents=True, exist_ok=True)
    evidence = metadata('platform/external/qemu', qemu_revision)
    properties = metadata('platform/external/qemu', qemu_revision, 'source.properties')
    if not re.search(r'^Pkg.Revision=' + re.escape(expected_version) + r'$', properties.decode(), re.M):
        raise ValueError('Stable source version mismatch')
    if 'Stable' not in evidence['message']:
        raise ValueError('Selected commit does not explicitly designate Stable')
    raw = metadata('platform/manifest', manifest_revision, 'default.xml')
    (workspace / 'upstream-manifest.xml').write_bytes(raw)
    (workspace / 'stable-commit.json').write_text(json.dumps(evidence, indent=2) + '\n')
    (workspace / 'source.properties').write_bytes(properties)
    projects = selected_projects(raw)
    resolved = ET.Element('manifest')
    ET.SubElement(resolved, 'remote', {'name': 'aosp', 'fetch': '..'})
    ET.SubElement(resolved, 'default', {'remote': 'aosp'})
    records = []
    # Only independent metadata repositories are written concurrently.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(resolve_project, p, workspace, cutoff, qemu_revision) for p in projects]
        for project, future in zip(projects, futures):
            selected, record = future.result()
            record.update(name=project.get('name'), path=project.get('path'), revision=selected)
            records.append(record)
            project.set('revision', selected)
            resolved.append(project)
    data = ET.tostring(resolved, encoding='utf-8', xml_declaration=True)
    (workspace / 'resolved-manifest.xml').write_bytes(data)
    lock = {
        'status': 'independently-resolved-candidate-build-and-runtime-validation-required',
        'manifest_repository': ORIGIN + 'platform/manifest',
        'manifest_revision': manifest_revision,
        'manifest_file': 'default.xml',
        'upstream_manifest_sha256': hashlib.sha256(raw).hexdigest(),
        'manifest_sha256': hashlib.sha256(data).hexdigest(),
        'manifest_resolution': 'independent-historical-candidate-not-official-release-manifest',
        'dependency_cutoff': cutoff,
        'resolver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_ref_type': 'published-stable-commit',
        'release_branch': None,
        'source_version': expected_version,
        'selected_project_count': len(projects),
        'qemu_revision': qemu_revision,
        'source_origin': ORIGIN,
        'excluded_projects': sorted(EXCLUDED),
        'target': 'linux_aarch64', 'build_host': 'linux/amd64', 'runtime_guest_api': 36,
    }
    evidence_records = json.dumps(records, indent=2) + '\n'
    lock['resolution_records_sha256'] = hashlib.sha256(evidence_records.encode()).hexdigest()
    (workspace / 'resolution-records.json').write_text(evidence_records)
    (workspace / 'upstream-source.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    print('Resolved candidate:', len(projects), 'projects; compatibility is not established yet', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--manifest-revision', required=True)
    parser.add_argument('--qemu-revision', required=True)
    parser.add_argument('--source-version', required=True)
    parser.add_argument('--cutoff', required=True)
    args = parser.parse_args()
    for value in (args.manifest_revision, args.qemu_revision):
        if not re.fullmatch('[0-9a-f]{40}', value):
            parser.error('Immutable input revisions are required')
    resolve(args.workspace, args.manifest_revision, args.qemu_revision, args.source_version, args.cutoff)
