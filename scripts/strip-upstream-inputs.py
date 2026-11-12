#!/usr/bin/env python3
"""Remove distribution components a headless ARM64 container does not use.

Google's distribution also serves desktop users and old Linux distributions.
The removed components are prebuilt or firmware binaries whose corresponding
source is not part of this build's source release, so they are not shipped.
Each removal is recorded with the removed files' SHA-256 in provenance.json,
and NOTICE.txt/NOTICE.csv are updated to list only shipped files.
"""
import argparse
import hashlib
import json
from pathlib import Path

COMPONENTS = (
    {
        'component': 'Qt desktop UI',
        'paths': ('lib64/qt/', 'qemu/linux-aarch64/qemu-system-aarch64', 'emulator-check'),
        'reason': 'Windowed UI only; with -no-window the emulator runs qemu-system-aarch64-headless, '
                  'which does not link Qt. Prebuilt LGPL-3.0 Qt 6.5.3 has no corresponding source in this build.',
    },
    {
        'component': '32-bit ARM guest support',
        'paths': ('qemu/linux-aarch64/qemu-system-armel', 'qemu/linux-aarch64/qemu-system-armel-headless'),
        'reason': 'Supported system images are arm64-v8a.',
    },
    {
        'component': 'old-distribution glibc compatibility',
        'paths': ('lib64/glibc-2.29.tgz', 'patchelf.tgz', 'linux-aarch64-fixgcc.sh'),
        'reason': 'Only used by linux-aarch64-fixgcc.sh for old host distributions; the image uses Ubuntu glibc. '
                  'Prebuilt LGPL glibc and GPL-3.0 patchelf have no corresponding source in this build.',
    },
    {
        'component': 'x86 firmware',
        'paths': ('lib/pc-bios/',),
        'reason': 'x86 BIOS, VGA and network option ROMs are not used by arm64 guests. Prebuilt SeaBIOS and iPXE '
                  'images have no corresponding source in the checkout (empty roms/ submodules).',
    },
    {
        'component': 'optional gles_llvmpipe backend',
        'paths': ('lib64/gles_llvmpipe/',),
        'reason': "Google's cross-build bundles AMD64 Mesa objects into the ARM64 distribution; the selected "
                  'renderer is the source-built ARM64 SwiftShader.',
    },
)


# Notice entries Google attributes to shipped files whose code none of them
# contains (attribution follows Google's build graph). Each is dropped only after
# scanning every shipped file for the component's markers.
MISATTRIBUTED = {
    'Qt 6': (b'qt_version_tag', b'_ZN7QObject', b'QCoreApplication'),
    'bios': (b'SeaBIOS', b'iPXE', b'VGABios'),
}
# Google's NOTICE.csv names the source of an older FFmpeg; archive/PACKAGES.TXT
# builds the shipped 4.4.2 from the unpatched release tarball.
CSV_URL_FIXES = {
    'ffmpeg': ('/archive/+/refs/heads/emu-master-dev/ffmpeg-3.4.5.tar.xz',
               '/archive/+/refs/heads/emu-master-dev/ffmpeg-4.4.2.tar.gz'),
}


def matches(name, paths):
    return any(name.startswith(p) if p.endswith('/') else name == p for p in paths)


def filter_notice_txt(text, removed, drop=()):
    """Drop removed files from each 'Notices for file(s):' list; drop sections left empty or in drop."""
    lines = text.split('\n')
    starts = [i - 1 for i, line in enumerate(lines) if line == 'Notices for file(s):']
    if not starts or any(lines[i] != '=' * 59 for i in starts):
        raise ValueError('Unexpected NOTICE.txt layout')
    out, dropped = lines[:starts[0]], []
    for start, end in zip(starts, starts[1:] + [len(lines)]):
        section = lines[start:end]
        footer = next(i for i, line in enumerate(section) if line.startswith('The notices is included for the library: '))
        library = section[footer].split(': ', 1)[1]
        files = [line for line in section[2:footer] if removed(line)]
        kept = [line for line in section[2:footer] if not removed(line)]
        if (files and not kept) or library in drop:
            dropped.append(library)
            continue
        out += section[:2] + kept + section[footer:]
    return '\n'.join(out), dropped


def filter_notice_csv(text, removed, drop=()):
    """Drop removed files from each row's binaries column; drop rows left empty or in drop."""
    lines = text.split('\n')
    out, dropped, fixes = [lines[0]], [], dict(CSV_URL_FIXES)
    for line in lines[1:]:
        if not line:
            out.append(line)
            continue
        fields = line.split(', ')
        if len(fields) != 5:
            raise ValueError('Unexpected NOTICE.csv layout')
        binaries = fields[3].split(' ')
        kept = [b for b in binaries if not removed(b)]
        if not kept or fields[0] in drop:
            dropped.append(fields[0])
            continue
        fields[3] = ' '.join(kept)
        if fields[0] in fixes:
            old, new = fixes.pop(fields[0])
            if not fields[4].endswith(old):
                raise ValueError(f'Unexpected NOTICE.csv source URL for {fields[0]}')
            fields[4] = fields[4][:-len(old)] + new
        out.append(', '.join(fields))
    if fixes:
        raise ValueError(f'NOTICE.csv rows not found: {sorted(fixes)}')
    return '\n'.join(out), dropped


def strip(inputs):
    meta_path = inputs / 'provenance.json'
    meta = json.loads(meta_path.read_text())
    root = inputs / 'emulator'
    inventory = meta['files_sha256']
    excluded = meta.setdefault('excluded_components', [])
    recorded = {entry['component'] for entry in excluded}
    plan = []
    for spec in COMPONENTS:
        if spec['component'] in recorded:
            raise ValueError(f'Already removed: {spec["component"]}')
        files = sorted(name for name in inventory if matches(name, spec['paths']))
        if not files:
            raise ValueError(f'Nothing to remove for {spec["component"]}; distribution layout changed?')
        for name in files:
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != inventory[name]:
                raise ValueError(f'Staged file differs from provenance: {name}')
        plan.append((spec, files))
    removed_names = {name for _, files in plan for name in files}

    def removed(entry):
        return (entry[2:] if entry.startswith('./') else entry) in removed_names

    notice_names = ('NOTICE.txt', 'NOTICE.csv')
    for name in inventory:
        if name in removed_names or name in notice_names:
            continue
        data = (root / name).read_bytes()
        for component, markers in MISATTRIBUTED.items():
            if any(marker in data for marker in markers):
                raise ValueError(f'{name} contains {component} code; keep its notice')
    notices = {}
    for name, rewrite in (('NOTICE.txt', filter_notice_txt), ('NOTICE.csv', filter_notice_csv)):
        data = (root / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != inventory[name]:
            raise ValueError(f'Staged file differs from provenance: {name}')
        text, dropped = rewrite(data.decode(), removed, tuple(MISATTRIBUTED))
        notices[name] = (text.encode(), dropped)
    # All files are checked before anything is removed.
    for spec, files in plan:
        for name in files:
            (root / name).unlink()
        excluded.append({
            'component': spec['component'],
            'reason': spec['reason'],
            'files_sha256': {name: inventory[name] for name in files},
        })
    meta['notice_update'] = {
        'reason': 'Removed files dropped from the notice file lists; entries left without shipped files dropped. '
                  'Qt 6 and bios entries dropped: no shipped file contains their code. '
                  'FFmpeg source URL corrected to the 4.4.2 tarball archive/PACKAGES.TXT builds.',
        'files': {},
    }
    for name, (data, dropped) in notices.items():
        (root / name).write_bytes(data)
        meta['notice_update']['files'][name] = {
            'before_sha256': inventory[name],
            'after_sha256': hashlib.sha256(data).hexdigest(),
            'dropped_entries': dropped,
        }
    for directory in sorted((p for p in root.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
    meta['files_sha256'] = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in root.rglob('*') if path.is_file()}
    meta_path.write_text(json.dumps(meta, indent=2) + '\n')
    removed = sum(len(files) for _, files in plan)
    print(f'Removed {removed} files in {len(plan)} components; {len(meta["files_sha256"])} files remain')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', type=Path, default=Path('build-inputs'))
    strip(parser.parse_args().inputs)
