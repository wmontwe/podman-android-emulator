#!/usr/bin/env python3
"""Overlay locally built GLES libraries and record their separate source inputs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import zipfile

# Shared checks live in verify-upstream-input.py, which the images also run standalone.
_spec = importlib.util.spec_from_file_location('verify_upstream_input', Path(__file__).with_name('verify-upstream-input.py'))
verify_input = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_input)


def overlay(inputs, libraries, records, archive):
    if archive.exists():
        raise ValueError('Refusing to overwrite an exported artifact')
    source = json.loads((records / 'source.lock.json').read_text())
    if source['source_repository'] != 'https://android.googlesource.com/platform/external/swiftshader' or source['source_revision'] != '9759b180cf5b6687afc1f231b1b9fa230da1b261':
        raise ValueError('Unexpected graphics source')
    meta_path = inputs / 'provenance.json'
    meta = json.loads(meta_path.read_text())
    root = inputs / 'emulator'
    component = {
        'source_repository': source['source_repository'],
        'source_revision': source['source_revision'],
        'patch_sha256': hashlib.sha256((records / 'applied.patch').read_bytes()).hexdigest(),
        'builder_packages_sha256': hashlib.sha256((records / 'builder-packages.txt').read_bytes()).hexdigest(),
        'build_command': 'scripts/build-upstream-graphics; native ARM64; Release; libEGL libGLESv2 libGLES_CM; offline',
        'replaced_files': {},
    }
    for name in ('libEGL.so', 'libGLESv2.so', 'libGLES_CM.so'):
        path = libraries / name
        data = path.read_bytes()
        if not verify_input.is_arm64_elf(data):
            raise ValueError('Expected an ARM64 graphics ELF')
        relative = 'lib64/gles_swiftshader/' + name
        target = root / relative
        if hashlib.sha256(target.read_bytes()).hexdigest() != meta['files_sha256'][relative]:
            raise ValueError('Existing staged graphics differ from provenance')
        component['replaced_files'][relative] = {
            'before_sha256': meta['files_sha256'][relative],
            'after_sha256': hashlib.sha256(data).hexdigest(),
        }
    # All files are checked before modifying the staged distribution.
    for name in ('libEGL.so', 'libGLESv2.so', 'libGLES_CM.so'):
        shutil.copy2(libraries / name, root / 'lib64/gles_swiftshader' / name)
    meta['additional_components'] = [component]
    meta['base_emulator_archive_sha256'] = meta.get('base_emulator_archive_sha256', meta['archive_sha256'])
    meta['files_sha256'] = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in root.rglob('*') if path.is_file()}
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(root.rglob('*')):
            if path.is_file():
                zipped.write(path, 'emulator/' + path.relative_to(root).as_posix())
    meta['archive_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
    meta['review_status'] = 'source-graphics-overlay-runtime-validation-pending'
    meta_path.write_text(json.dumps(meta, indent=2) + '\n')
    shutil.copytree(records, inputs / 'graphics-build-records')
    print('Exported composite archive:', archive)
    print('SHA256:', meta['archive_sha256'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', type=Path, default=Path('build-inputs'))
    parser.add_argument('--libraries', type=Path, required=True)
    parser.add_argument('--records', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    overlay(args.inputs, args.libraries, args.records, args.archive)
