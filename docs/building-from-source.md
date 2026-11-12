# Building from source

This guide builds the Linux ARM64 emulator from Google's source and packages it
into the images. Releases use the same steps; see [releases](releases.md).

Building needs a lot of space and time: the source checkout is about 80 GB and
the build output about 36 GB in a Podman volume, and the build uses 16 GiB RAM
and 8 CPUs.

## Source selection

The build uses Google's published **37.3.10 Stable** commit of
`platform/external/qemu` (`223638d03d23f1eeb303535ed5d55d4f211107fd`).

| File | Purpose |
|---|---|
| `upstream-release-target.json` | Selected stable source version and pins; the image build refuses anything else |
| `upstream-source.lock.json` | Pinned dependency manifest used by the fetcher |
| `upstream-dependencies/<version>/` | How each dependency revision was resolved |
| `upstream-graphics.lock.json` | Pinned SwiftShader source for the GLES libraries |

Google does not publish a resolved release manifest for the emulator. The
dependencies (65 Google projects) were therefore resolved from Google's branch
history at or before the stable commit's timestamp. This is a compatible
candidate, not Google's official manifest, and the build is not claimed to be
identical to the SDK's emulator binary. Beta, RC and development heads are not
used, and versions are never relabeled.

The official API 36 system image requires emulator 35.4.9 or newer;
`scripts/check-sdk-image-compatibility.py` enforces such minimums when the local
image is built.

## Patches

All changes are source patches with recorded before/after hashes:

| Patch | Why |
|---|---|
| QEMU IPA size and PCI layout (`scripts/patch-upstream-qemu.py`) | krunkit's VM supports only a 36-bit guest physical address space; see [design notes](design-notes.md#kvm-address-space) |
| libuuid as PIC (`scripts/build-upstream-uuid`) | The prebuilt `libuuid.a` corrupts QEMU's thread-local state on ARM64; see [design notes](design-notes.md#libuuid-tls-corruption) |
| SwiftShader JIT (`patches/swiftshader-jit-mmap.patch`) | JIT memory compatible with enforcing SELinux; see [design notes](design-notes.md#swiftshader-jit-under-selinux) |

## Steps

### 1. Fetch the source

The fetcher runs natively on ARM64 with Git hooks and credential helpers
disabled. It fetches only the pinned revisions, excluding prebuilt emulators,
system images and Windows/macOS toolchains.

```sh
podman build --platform linux/arm64 -t localhost/android-upstream-fetcher -f Containerfile.fetcher .
podman volume create --ignore android-upstream-source
podman run --pull=never -d --name android-upstream-fetch-37-3-10 \
  --cap-drop=all --security-opt=no-new-privileges --memory=2g --memory-swap=2g --cpus=2 \
  -v android-upstream-source:/work localhost/android-upstream-fetcher
podman logs -f android-upstream-fetch-37-3-10
```

`scripts/continue-upstream-build` waits for a container with exactly this name
(override with `ANDROID_FETCH_CONTAINER`).

### 2. Build the emulator

Google's toolchain is x86-64 only, so the build cross-compiles in an AMD64
container (using the VM's x86-64 emulation). It runs without network,
capabilities or devices, with 16 GiB memory and one concurrent linker.

```sh
podman build --platform linux/amd64 -t localhost/android-upstream-builder:37.3.10 -f Containerfile.builder .
scripts/continue-upstream-build            # waits for the fetch, then builds
scripts/continue-upstream-build --resume   # continue an interrupted build incrementally
```

`scripts/build-upstream-emulator` checks every project revision, applies the
patches, and runs configure, compile and packaging. The distribution ends up in
`/work/dist-37.3.10` in the volume.

### 3. Build the SwiftShader libraries

```sh
podman build --platform linux/arm64 -t localhost/android-upstream-graphics-builder -f Containerfile.graphics-builder .
```

`scripts/build-upstream-graphics` builds the pinned SwiftShader with the JIT
patch, offline.

### 4. Prepare the build inputs

`scripts/prepare-upstream-inputs.py` stages the exported emulator archive
(`--archive`, `--archive-sha256`, `--records`) and its SDK registration.
`scripts/overlay-upstream-graphics.py` then replaces the GLES libraries with the
SwiftShader build from step 3 (`--libraries`, `--records`, `--archive`).
Finally, `scripts/strip-upstream-inputs.py` removes what Google ships for desktop
users and old Linux distributions but a headless container never runs:

| Removed | Why it's unused |
|---|---|
| Qt libraries, windowed QEMU, `emulator-check` | With `-no-window` the emulator runs `qemu-system-aarch64-headless`, which doesn't link Qt |
| 32-bit ARM QEMU | Only arm64 system images are supported |
| `glibc-2.29.tgz`, `patchelf.tgz`, `linux-aarch64-fixgcc.sh` | Compatibility with old distributions; the image uses Ubuntu's glibc |
| `lib/pc-bios` | x86 firmware, not used by arm64 guests |
| `lib64/gles_llvmpipe` | Google's cross-build bundles x86-64 Mesa libraries here; the image renders with SwiftShader |

These are prebuilt binaries whose source isn't in the source release, so
shipping them would break the LGPL/GPL source obligations.
`scripts/verify-upstream-input.py` rejects inputs that still contain them. The
step also takes the removed files out of `NOTICE.txt` and `NOTICE.csv` and
corrects their attributions; see [releases](releases.md#image-split). All three
steps record their inputs in the provenance:

```text
build-inputs/
├── emulator/          # the emulator distribution
└── provenance.json    # source pins, patches, build command, file hashes
```

`build-inputs/` is not tracked by Git. `scripts/verify-upstream-input.py` checks
that every file matches the recorded SHA-256, that there are no symlinks or
special files, and that the binaries are ARM64. It checks integrity, not that the
binaries really came from the recorded source.

### 5. Build the images

```sh
podman build --platform linux/arm64 -t localhost/podman-android-emulator:base -f Containerfile .
podman build --platform linux/arm64 --build-arg BASE_IMAGE=localhost/podman-android-emulator:base \
  -t localhost/podman-android-emulator:api36 -f Containerfile.local .
scripts/run-android
```

`Containerfile` verifies the inputs against `upstream-release-target.json`
before packaging. Ubuntu base images are pinned by digest; Ubuntu packages and
SDK downloads are not.

## Development helpers

- `Containerfile.runtime-update` swaps a newly built emulator into an existing
  local image without downloading the system image again.
- `Containerfile.debug` adds `gdb` and `strace` to a local image.
- `tests/uuid_tls_probe.c` reproduces the libuuid TLS corruption without Android
  or KVM.

## Keeping up to date

`.github/workflows/upstream-updates.yml` opens an issue when a newer stable
emulator, SDK command-line tools, system image revision or Ubuntu base image is
available. To move to a new emulator version:

1. Find the commit titled "Bump Emulator to <version> Stable" on the
   `emu-main-dev` branch of `platform/external/qemu`, and check that the
   `source.properties` it changes names that version.
2. In the fetcher image, run `scripts/resolve-upstream-sources.py` with the
   commit, the `platform/manifest` revision, the version and the commit
   timestamp as `--cutoff`. Copy its output to `upstream-dependencies/<version>/`
   and its lock to `upstream-source.lock.json`.
3. Update `upstream-release-target.json`, the version defaults in the scripts and
   Containerfiles, and `emulator_source` in `upstream-watch.json`. Check that the
   files `scripts/patch-upstream-qemu.py` patches are unchanged before updating
   its `REVISION`; otherwise rework the patch.
4. Revert the recorded patches in the source volume, then fetch, build and run
   steps 3–5 and the checks in [validation](validation.md).
