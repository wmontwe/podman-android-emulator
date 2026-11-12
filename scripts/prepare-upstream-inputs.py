#!/usr/bin/env python3
"""Stage a locally built archive and honest SDK registration metadata.

Does not execute archive contents or authenticate self-declared build provenance.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile

# Shared checks live in verify-upstream-input.py, which the images also run standalone.
_spec = importlib.util.spec_from_file_location('verify_upstream_input', Path(__file__).with_name('verify-upstream-input.py'))
verify_input = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_input)


def prepare(archive, expected_sha256, records, destination):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError('Built archive SHA-256 mismatch')
    lock = json.loads((records / 'upstream-source.lock.json').read_text())
    patch = json.loads((records / 'local-ipa-pci.json').read_text())
    if patch['source_revision'] != lock['qemu_revision']:
        raise ValueError('Source and patch records disagree')
    if hashlib.sha256((records / 'resolved-manifest.xml').read_bytes()).hexdigest() != lock['manifest_sha256']:
        raise ValueError('Resolved manifest hash mismatch')
    if hashlib.sha256((records / 'local-ipa-pci.patch').read_bytes()).hexdigest() != patch['patch_sha256']:
        raise ValueError('Source patch hash mismatch')
    patches = [patch]
    uuid_record = records / 'local-uuid-pic.json'
    if uuid_record.exists():
        uuid_patch = json.loads(uuid_record.read_text())
        if uuid_patch['source_revision'] != lock['qemu_revision']:
            raise ValueError('UUID source and patch records disagree')
        if hashlib.sha256((records / 'local-uuid-pic.patch').read_bytes()).hexdigest() != uuid_patch['patch_sha256']:
            raise ValueError('UUID source patch hash mismatch')
        patches.append(uuid_patch)
    gfx_record = records / 'local-gfxstream-process-gl.json'
    if gfx_record.exists():
        gfx_patch = json.loads(gfx_record.read_text())
        projects = json.loads((records / 'fetched-projects.json').read_text())
        pins = [p['revision'] for p in projects if p['path'] == 'hardware/google/gfxstream']
        if pins != [gfx_patch['source_revision']] or gfx_patch['source_repository'] != 'https://android.googlesource.com/platform/hardware/google/gfxstream':
            raise ValueError('Gfxstream source and patch records disagree')
        if hashlib.sha256((records / 'local-gfxstream-process-gl.patch').read_bytes()).hexdigest() != gfx_patch['patch_sha256']:
            raise ValueError('Gfxstream source patch hash mismatch')
        patches.append(gfx_patch)
    if destination.exists():
        raise ValueError('Destination already exists; refusing to overwrite inputs')
    with zipfile.ZipFile(archive) as zipped:
        for item in zipped.infolist():
            path = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'emulator':
                raise ValueError('Unsafe archive path')
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise ValueError('Archive contains a symlink or special file')
        destination.mkdir(parents=True)
        for item in zipped.infolist():
            target = destination / item.filename
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zipped.read(item))
            target.chmod(0o755 if (item.external_attr >> 16) & 0o111 else 0o644)
    root = destination / 'emulator'
    props = verify_input.read_properties(root / 'source.properties')
    revision = props['Pkg.Revision'].strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', revision):
        raise ValueError('Unexpected distribution version; do not fabricate one')
    generated = {}
    if not (root / 'package.xml').exists():
        major, minor, micro = revision.split('.')
        metadata = f'''<?xml version="1.0" encoding="UTF-8"?>
<ns2:repository xmlns:ns2="http://schemas.android.com/repository/android/common/02"
 xmlns:ns3="http://schemas.android.com/repository/android/generic/02"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
 <localPackage path="emulator" obsolete="false">
  <type-details xsi:type="ns3:genericDetailsType"/>
  <revision><major>{major}</major><minor>{minor}</minor><micro>{micro}</micro></revision>
  <display-name>Android Emulator (local upstream source build)</display-name>
 </localPackage>
</ns2:repository>
'''
        (root / 'package.xml').write_text(metadata)
        generated['package.xml'] = 'Local SDK registration derived from unchanged source.properties version'
    inventory = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in root.rglob('*') if path.is_file()}
    provenance = {
        'review_status': 'static-inspection-complete-runtime-validation-pending',
        'source_repository': 'https://android.googlesource.com/platform/external/qemu',
        'source_revision': lock['qemu_revision'],
        'manifest_repository': lock['manifest_repository'],
        'manifest_revision': lock['manifest_revision'],
        'manifest_sha256': lock['manifest_sha256'],
        'release_branch': lock.get('release_branch'),
        'source_ref_type': lock.get('source_ref_type', 'release-branch'),
        'manifest_resolution': lock.get('manifest_resolution', 'direct-upstream-manifest'),
        'upstream_manifest_sha256': lock.get('upstream_manifest_sha256'),
        'resolution_records_sha256': lock.get('resolution_records_sha256'),
        'distribution_revision': revision,
        'archive_sha256': expected_sha256,
        'build_command': ((records / 'upstream-build-command.txt').read_text().strip()
                          if (records / 'upstream-build-command.txt').exists() else
                          'scripts/build-upstream-emulator: configure, compile, distribution; linux_aarch64; release; crash=none'),
        'toolchain_inputs': {
            'builder_packages_sha256': hashlib.sha256((records / 'builder-packages.txt').read_bytes()).hexdigest(),
            'projects': json.loads((records / 'fetched-projects.json').read_text()),
        },
        'patches': patches,
        'generated_files': generated,
        'files_sha256': inventory,
    }
    (destination / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    shutil.copytree(records, destination / 'build-records')
    print(f'Staged {len(inventory)} files; real distribution revision {revision}; runtime validation pending')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--archive-sha256', required=True)
    parser.add_argument('--records', type=Path, required=True)
    parser.add_argument('--destination', type=Path, default=Path('build-inputs'))
    args = parser.parse_args()
    prepare(args.archive, args.archive_sha256, args.records, args.destination)
