#!/usr/bin/env python3
"""Package locally built emulator inputs for a GitHub release.

Writes a reproducible archive of build-inputs/ (emulator/ and provenance.json)
and a release record under releases/. The record pins the archive hash; CI
refuses to publish an image from any other archive. It does not prove that the
archive was built from the recorded source: the build happens locally.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile

REPO = Path(__file__).resolve().parents[1]
TAG = re.compile(r'v(?P<version>\d+\.\d+\.\d+)-r(?P<revision>[1-9]\d*)')
DEFAULT_IMAGE = 'ghcr.io/wmontwe/podman-android-emulator'


def parse_tag(tag):
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError(f'Release tag must look like v37.3.10-r1, got {tag!r}')
    return match['version'], int(match['revision'])


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _members(inputs):
    yield inputs / 'provenance.json', 'provenance.json'
    emulator = inputs / 'emulator'
    yield emulator, 'emulator'
    for path in sorted(emulator.rglob('*'), key=lambda p: p.relative_to(emulator).as_posix()):
        yield path, 'emulator/' + path.relative_to(emulator).as_posix()


def write_archive(inputs, destination):
    """Write a byte-reproducible tar.gz: sorted names, zeroed owners and times."""
    with destination.open('wb') as raw, \
            gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed, \
            tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
        for path, name in _members(inputs):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError(f'Refusing symlink or special file: {path}')
            info = tarfile.TarInfo(name)
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            info.mtime = 0
            if path.is_dir():
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                archive.addfile(info)
                continue
            info.size = path.stat().st_size
            info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            with path.open('rb') as handle:
                archive.addfile(info, handle)


def check_release_inputs(tag, provenance, target, source):
    version, _ = parse_tag(tag)
    if provenance.get('distribution_revision') != version:
        raise ValueError(f'Provenance is for {provenance.get("distribution_revision")}, not {version}')
    if target.get('source_version') != version:
        raise ValueError(f'Release target selects {target.get("source_version")}, not {version}')
    if not source or not source.get('parts'):
        raise ValueError('Corresponding source is required; run scripts/package-source first')


def check_source_parts(source, directory):
    """The source record must describe the part files actually present."""
    for part in source['parts']:
        path = directory / part['name']
        if part['name'] != path.name or not path.is_file():
            raise ValueError(f'Missing source part {part["name"]}; rerun scripts/package-source')
        if path.stat().st_size != part['size'] or sha256(path) != part['sha256']:
            raise ValueError(f'Source part {part["name"]} does not match its record; rerun scripts/package-source')


def release_record(tag, provenance, target, archive, source, image):
    check_release_inputs(tag, provenance, target, source)
    version, revision = parse_tag(tag)
    return {
        'schema_version': 1,
        'tag': tag,
        'emulator_version': version,
        'release_revision': revision,
        'image': image,
        'image_tag': tag[1:],
        'guest_api': target.get('guest_api'),
        'build': 'local',
        'source_revision': provenance['source_revision'],
        'manifest_revision': provenance['manifest_revision'],
        'archive': {
            'name': archive.name,
            'sha256': sha256(archive),
            'size': archive.stat().st_size,
        },
        'source_archive': source,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('tag')
    parser.add_argument('--inputs', type=Path, default=REPO / 'build-inputs')
    parser.add_argument('--output', type=Path, default=REPO / 'dist-release')
    parser.add_argument('--releases', type=Path, default=REPO / 'releases')
    parser.add_argument('--image', default=DEFAULT_IMAGE)
    args = parser.parse_args()
    parse_tag(args.tag)
    provenance_path = args.inputs / 'provenance.json'
    target_path = REPO / 'upstream-release-target.json'
    # The same gates the image build applies, run before anything is packaged.
    subprocess.run([sys.executable, '-I', str(REPO / 'scripts/verify-upstream-release.py'),
                    str(target_path), str(provenance_path)], check=True)
    subprocess.run([sys.executable, '-I', str(REPO / 'scripts/verify-upstream-input.py'),
                    str(args.inputs / 'emulator'), str(provenance_path)], check=True)
    source_path = args.output / f'source-{args.tag}.json'
    if not source_path.exists():
        raise ValueError(f'Missing {source_path}; run scripts/package-source {args.tag} first')
    source = json.loads(source_path.read_text())
    provenance = json.loads(provenance_path.read_text())
    target = json.loads(target_path.read_text())
    # Validate everything before writing the (large) archive.
    check_release_inputs(args.tag, provenance, target, source)
    check_source_parts(source, args.output)
    archive = args.output / f'emulator-{args.tag}-linux-aarch64.tar.gz'
    write_archive(args.inputs, archive)
    record = release_record(args.tag, provenance, target, archive, source, args.image)
    args.releases.mkdir(parents=True, exist_ok=True)
    record_path = args.releases / f'{args.tag}.json'
    if record_path.exists() and json.loads(record_path.read_text()) != record:
        raise SystemExit(f'{record_path} exists with different content; use a new release revision')
    record_path.write_text(json.dumps(record, indent=2) + '\n')
    print(f'Wrote {archive} ({record["archive"]["sha256"]})')
    print(f'Wrote {record_path}; commit it before tagging {args.tag}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(f'package-release: {error}')
