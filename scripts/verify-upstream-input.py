#!/usr/bin/env python3
"""Validate local distribution integrity, not source trust or build attestation."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import xml.etree.ElementTree as ET

# Removed by strip-upstream-inputs.py: unused, and no corresponding source shipped.
UNSHIPPED = ('lib64/qt/', 'lib/pc-bios/', 'emulator-check', 'qemu/linux-aarch64/qemu-system-aarch64',
             'qemu/linux-aarch64/qemu-system-armel', 'qemu/linux-aarch64/qemu-system-armel-headless',
             'lib64/glibc-2.29.tgz', 'patchelf.tgz', 'linux-aarch64-fixgcc.sh', 'lib64/gles_llvmpipe/')


def is_arm64_elf(data):
    """64-bit little-endian ELF for AArch64 (e_machine 183)."""
    return len(data) >= 20 and data[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', data, 18)[0] == 183


def read_properties(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)


def verify(root, provenance):
    root = root.resolve()
    metadata = json.loads(provenance.read_text())
    if metadata.get('source_repository') != 'https://android.googlesource.com/platform/external/qemu':
        raise ValueError('Expected Google upstream QEMU source repository')
    if metadata.get('manifest_repository') != 'https://android.googlesource.com/platform/manifest':
        raise ValueError('Expected Google upstream manifest repository')
    for key in ('source_revision', 'manifest_revision'):
        if not re.fullmatch(r'[0-9a-f]{40}', metadata.get(key, '')):
            raise ValueError(f'Missing immutable {key}')
    for key in ('build_command', 'toolchain_inputs', 'patches'):
        if not metadata.get(key):
            raise ValueError(f'Missing build provenance: {key}')
    expected = metadata.get('files_sha256')
    if not isinstance(expected, dict) or not expected:
        raise ValueError('Missing complete distribution hash inventory')
    actual = set()
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'Symlinks are not accepted in prepared inputs: {path}')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise ValueError(f'Unexpected special file: {path}')
    if actual != set(expected):
        raise ValueError('Distribution files do not match provenance inventory')
    unshipped = sorted(name for name in actual
                       if any(name.startswith(p) if p.endswith('/') else name == p for p in UNSHIPPED))
    if unshipped:
        raise ValueError(f'Unused components must be removed with strip-upstream-inputs.py: {unshipped[0]}')
    for name, digest in expected.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe inventory path')
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError(f'Invalid SHA-256 for {name}')
        data = (root / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f'SHA-256 mismatch: {name}')
        if data.startswith(b'\x7fELF') and not is_arm64_elf(data):
            raise ValueError(f'Expected native ARM64 ELF: {name}')
    for name in ('emulator', 'qemu/linux-aarch64/qemu-system-aarch64-headless'):
        path = root / name
        with path.open('rb') as handle:
            header = handle.read(20)
        if not is_arm64_elf(header):
            raise ValueError(f'Expected native ARM64 ELF: {name}')
        if not path.stat().st_mode & 0o111:
            raise ValueError(f'Executable bit missing: {name}')
    if not (root / 'package.xml').is_file():
        raise ValueError('Missing recorded SDK registration package.xml')
    props = read_properties(root / 'source.properties')
    revision = metadata.get('distribution_revision', '')
    if not re.fullmatch(r'\d+\.\d+\.\d+', revision) or props.get('Pkg.Revision', '').strip() != revision:
        raise ValueError('Provenance revision must match unchanged source.properties')
    registered = ET.parse(root / 'package.xml').find('./localPackage/revision')
    if registered is None or '.'.join(registered.findtext(k, '0') for k in ('major', 'minor', 'micro')) != revision:
        raise ValueError('SDK registration revision must match source.properties')


if __name__ == '__main__':
    try:
        verify(Path(sys.argv[1]), Path(sys.argv[2]))
    except (ValueError, OSError, KeyError, IndexError, ET.ParseError) as error:
        sys.exit(f'Upstream input validation failed: {error}')
    print('Distribution hash inventory and ARM64 format validated; provenance still requires review')
