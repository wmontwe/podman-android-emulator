#!/usr/bin/env python3
"""Package corresponding source for a release from the build's source tree.

Runs inside a network-less container with the source volume mounted read-only.
Before packaging it checks the tree against build provenance: every recorded
project is at its pinned revision and the only modified tracked files are the
recorded patches, with their recorded post-patch hashes. Only tracked files are
archived, with their (patched) working-tree content. Toolchain prebuilts and
test-only projects are excluded; dependency source tarballs are included.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

QEMU_PROJECT = 'platform/external/qemu'
INCLUDED_PREBUILTS = ('prebuilts/android-emulator-build/archive',)
EXCLUDED_PROJECTS = ('external/deqp', 'external/adt-infra')
PART_SIZE = '1900M'


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def included(path):
    if path in EXCLUDED_PROJECTS:
        return False
    return not path.startswith('prebuilts/') or path in INCLUDED_PREBUILTS


def expected_modifications(provenance):
    """Map project name -> {relative file: post-patch sha256} from recorded patches."""
    expected = {}
    for patch in provenance.get('patches', []):
        repository = patch.get('source_repository', '')
        name = repository.split('android.googlesource.com/', 1)[1] if repository else QEMU_PROJECT
        for file, hashes in patch.get('files', {}).items():
            expected.setdefault(name, {})[file] = hashes['after']
    return expected


def git(project, *args):
    # The read-only volume is owned by the build container's user, not ours.
    return subprocess.run(['git', '-c', 'safe.directory=*', '-C', str(project), *args], check=True,
                          capture_output=True, text=True).stdout


def verify_project(root, project, expected):
    directory = root / project['path']
    head = git(directory, 'rev-parse', 'HEAD').strip()
    if head != project['revision']:
        raise ValueError(f'{project["path"]} is at {head}, provenance pins {project["revision"]}')
    changed = set()
    for line in git(directory, 'status', '--porcelain', '--untracked-files=no').splitlines():
        changed.add(line[3:])
    allowed = expected.get(project['name'], {})
    unexpected = changed - set(allowed)
    if unexpected:
        raise ValueError(f'{project["path"]} has unrecorded changes: {sorted(unexpected)}')
    for file, digest in allowed.items():
        actual = hashlib.sha256((directory / file).read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError(f'{project["path"]}/{file} does not match its recorded patch result')
    return [f'{project["path"]}/{name}' for name in git(directory, 'ls-files', '-z').split('\0') if name]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('tag')
    parser.add_argument('--source', type=Path, default=Path('/work/source'))
    parser.add_argument('--provenance', type=Path, default=Path('/inputs/provenance.json'))
    parser.add_argument('--output', type=Path, default=Path('/out'))
    parser.add_argument('--check-only', action='store_true', help='verify the tree without packaging')
    args = parser.parse_args()
    provenance = json.loads(args.provenance.read_text())
    expected = expected_modifications(provenance)
    projects = provenance['toolchain_inputs']['projects']
    if not any(p['name'] == QEMU_PROJECT and p['revision'] == provenance['source_revision'] for p in projects):
        raise ValueError('Provenance does not pin QEMU at the recorded source revision')
    selected = [p for p in projects if included(p['path'])]
    missing = set(expected) - {p['name'] for p in selected}
    if missing:
        raise ValueError(f'Patched projects are excluded from the source archive: {sorted(missing)}')
    files, errors = [], []
    for project in selected:
        try:
            files.extend(verify_project(args.source, project, expected))
        except (ValueError, OSError, subprocess.CalledProcessError) as error:
            errors.append(str(error))
    if errors:
        raise ValueError('source tree does not match provenance:\n  ' + '\n  '.join(errors))
    files.sort()
    if args.check_only:
        print(f'Source tree matches provenance: {len(files)} files from {len(selected)} projects')
        return
    manifest = {
        'tag': args.tag,
        'source_revision': provenance['source_revision'],
        'manifest_revision': provenance['manifest_revision'],
        'projects': [{k: p[k] for k in ('name', 'path', 'revision')} for p in selected],
        'patches': provenance['patches'],
        'excluded': 'toolchain prebuilts (prebuilts/* except android-emulator-build/archive) and '
                    + ', '.join(EXCLUDED_PROJECTS),
    }
    work = Path('/tmp/package-source')
    work.mkdir(exist_ok=True)
    (work / 'SOURCE-MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (work / 'files').write_bytes(b''.join(name.encode() + b'\0' for name in files))
    base = f'source-{args.tag}.tar.xz'
    archive = args.output / base
    if archive.exists() or any(args.output.glob(f'{base}.part*')):
        raise ValueError(f'{args.output} already contains {base} or its parts; remove them first')
    subprocess.run(
        ['bash', '-o', 'pipefail', '-c',
         'tar --create --no-recursion --owner=0 --group=0 --numeric-owner --mtime=@0 '
         '-C "$1" SOURCE-MANIFEST.json -C "$2" --null --files-from "$1/files" '
         '| xz -T4 -6 > "$3"', 'tar', str(work), str(args.source), str(archive)],
        check=True)
    whole = sha256(archive)
    # GitHub release assets are limited to 2 GiB each.
    subprocess.run(['split', '-b', PART_SIZE, '-d', '-a', '2', str(archive), f'{archive}.part'], check=True)
    archive.unlink()
    parts = []
    for part in sorted(args.output.glob(f'{base}.part*')):
        parts.append({'name': part.name, 'sha256': sha256(part), 'size': part.stat().st_size})
    record = {'name': base, 'sha256': whole, 'files': len(files), 'parts': parts}
    (args.output / f'source-{args.tag}.json').write_text(json.dumps(record, indent=2) + '\n')
    print(f'Packaged {len(files)} files from {len(selected)} projects into {len(parts)} part(s)')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'package-source: {error}')
