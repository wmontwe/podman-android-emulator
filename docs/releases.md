# Releases

Releases publish a **release image** to
`ghcr.io/wmontwe/podman-android-emulator`, tagged `<emulator version>-r<n>`
(for example `37.3.10-r1`). Users add the Android system image locally.

## Image split

| Image | Contents | Built |
|---|---|---|
| Release (`Containerfile`) | Ubuntu 24.04, runtime packages, Ubuntu's open-source `adb`, the source-built emulator, launcher and checks | GitHub Actions |
| Local (`Containerfile.local`) | Release image plus Android SDK command-line tools, accepted SDK licenses and the Google APIs system image | Your machine |

The Android system image, SDK command-line tools and SDK platform-tools are
covered by the Android SDK License Agreement, which does not permit
redistribution. Google APIs system images also contain proprietary Google apps.
The release image therefore contains none of them. The emulator built from source
is Apache-2.0 licensed with third-party components listed in its `NOTICE.txt`.
QEMU is GPL-2.0 and glib LGPL-2.1, so every release carries their corresponding
source. Prebuilt parts of Google's distribution that a headless container does
not use (the Qt desktop UI, 32-bit ARM support, an old-distribution glibc
bundle, x86 firmware, and x86-64 Mesa libraries bundled by mistake) are removed
before packaging, because their source is not part of the source release; see [building from source](building-from-source.md#4-prepare-the-build-inputs).
`NOTICE.txt` and `NOTICE.csv` are Google's files, corrected to match what is
shipped: removed files are taken out, the Qt 6 and PC BIOS entries are dropped
because no shipped file contains their code (Google attributes them to
`emulator` through its build graph), and the FFmpeg source points to the
version actually linked.

Some copyleft parts are linked from Google's prebuilt libraries rather than
built here. Their source is in the source release under
`prebuilts/android-emulator-build/archive`, matching the SHA-1 recorded in its
`PACKAGES.TXT`; Google's build scripts are in
`external/qemu/android/scripts/unix/` (`build-ffmpeg.sh`, `build-x264.sh`,
`build-e2fsprogs.sh`):

| Component | License | Shipped in | Source in the archive |
|---|---|---|---|
| FFmpeg 4.4.2 (built with `--enable-gpl`) | GPL-2.0-or-later | statically in `emulator`, `qsn`, QEMU, gfxstream | `ffmpeg-4.4.2.tar.gz`, the unpatched release |
| x264 build 148 | GPL-2.0-or-later | statically, via FFmpeg | `x264-snapshot-20170103-2245.tar.bz2` and patches |
| e2fsprogs 1.42.13 | GPL-2.0 | `bin64/` (`e2fsck`, `resize2fs`, …) | `e2fsprogs-1.42.13.tar.xz` and patches |

This is not legal advice.

## Use a release image

Verify the signature, then build the local image from the verified digest:

```sh
image=ghcr.io/wmontwe/podman-android-emulator
digest=sha256:...   # from the release's image-<tag>.digest asset
cosign verify "$image@$digest" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github.com/wmontwe/podman-android-emulator/\.github/workflows/release\.yml@refs/(tags/v.*|heads/main)$'
gh attestation verify "oci://$image@$digest" --repo wmontwe/podman-android-emulator

podman build --platform linux/arm64 --build-arg BASE_IMAGE="$image@$digest" \
  -t localhost/podman-android-emulator:api36 -f Containerfile.local .
scripts/run-android
```

Building `Containerfile.local` accepts the Android SDK licenses; review them first.
It downloads SDK command-line tools and the system image from `dl.google.com`;
these downloads are not digest-locked.

Podman's `policy.json` matches keyless Fulcio signatures by email identity
(`fulcio.subjectEmail`), while GitHub Actions signatures carry a workflow URI.
Podman therefore does not enforce these signatures itself; verify with cosign
and pin the digest as above.

## Build everything locally

Without a release, build the emulator and both images yourself; see
[building from source](building-from-source.md).

## Maintainer procedure

The emulator is built locally (see [building from source](building-from-source.md));
CI only verifies and publishes.

1. Build the emulator distribution into `build-inputs/` and review it.
2. Check that the source tree still matches the build provenance, then package
   the corresponding source:

   ```sh
   scripts/package-source --check-only v37.3.10-r1
   scripts/package-source v37.3.10-r1
   ```

   The source volume is mounted read-only into a network-less container. The
   check requires every recorded project at its pinned revision, and allows only
   the recorded patches, with their recorded post-patch hashes. Only tracked
   files are archived. Toolchain prebuilts and test-only projects (`external/deqp`,
   `external/adt-infra`) are excluded; dependency source tarballs under
   `prebuilts/android-emulator-build/archive` are included. The archive is split
   into parts below GitHub's 2 GiB asset limit.
3. Package the emulator and write the release record:

   ```sh
   python3 scripts/package-release.py v37.3.10-r1
   ```

   This runs the same release-target and input checks as the image build, writes
   a reproducible `dist-release/emulator-<tag>-linux-aarch64.tar.gz`, and records
   its SHA-256 in `releases/<tag>.json`.
4. Build the local image from these inputs and run the boot test on a KVM host
   with enforcing SELinux. On a Mac, run it inside the Podman machine:

   ```sh
   podman machine ssh 'out=$(mktemp -d); ANDROID_TEST_OUTPUT=$out bash -s boot' < scripts/verify-container
   ```
5. Commit `releases/<tag>.json`, tag the commit, and push both.
6. Create a draft release for the tag and attach the emulator archive and all
   source parts:

   ```sh
   gh release create v37.3.10-r1 --draft --verify-tag \
     dist-release/emulator-v37.3.10-r1-linux-aarch64.tar.gz \
     dist-release/source-v37.3.10-r1.tar.xz.part* dist-release/source-v37.3.10-r1.json
   ```

7. Publish the release. `.github/workflows/release.yml` then:
   - downloads the emulator archive and rejects it unless it matches the hash in
     the tagged `releases/<tag>.json`;
   - runs the unit tests and builds the release image on a GitHub ARM64 runner;
   - runs the smoke test, pushes to GHCR and signs the digest with keyless cosign;
   - attaches build-provenance and SPDX SBOM attestations to the image;
   - uploads the SBOM and image digest to the release.

Configure the GitHub environment `release` to require your approval. Releases must
be published by a person: releases created with the workflow token do not trigger
workflows.

## What the provenance proves

The attestation proves that GitHub Actions built the image from this repository
at the tag, using the archive whose hash is committed there. It does **not** prove
that the archive was built from the recorded source: that build runs locally.
`provenance.json` inside the image records the source pins and patches, but it is
self-declared.

## Open points

- **KVM on GitHub runners.** Whether GitHub's ARM64 runners expose `/dev/kvm` is
  unverified, so the boot test stays local (step 4).
- **Ubuntu packages** are not pinned; the `ubuntu:24.04` base is pinned by digest
  and checked by `.github/workflows/upstream-updates.yml`.
