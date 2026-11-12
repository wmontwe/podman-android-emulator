# Container CI

`.github/workflows/verify-container.yml` runs shell syntax checks and Python
unit tests on pull requests and pushes to main. Tests use synthetic fixtures;
they do not execute downloaded emulator binaries.

Pull requests and pushes never build images. `.github/workflows/release.yml`
builds the release image only for a published release, from the locally built
emulator archive pinned in `releases/<tag>.json`; see [releases](releases.md).
Input validation checks format/integrity, not the truth of self-declared
provenance.

## Optional manual integration test

The `boot_test` dispatch input enables a main-branch-only integration job. It
requires a dedicated self-hosted Linux ARM64 runner labeled
`android-kvm-selinux`, accessible KVM, rootless Podman, enforcing SELinux, Bash,
Python 3, coreutils, and a preloaded, separately reviewed image tagged
`localhost/podman-android-emulator:api36`. The workflow does not pull an image or
rebuild from unreviewed inputs.

Configure the GitHub environment `android-boot-test` to require trusted reviewer
approval and restrict it to main. Naming an environment in YAML does not create
those protections. Do not expose a persistent self-hosted runner to untrusted
PR code; prefer an ephemeral runner without valuable credentials.

The test creates a unique disposable AVD volume and container with only KVM
passed, no added capabilities, no host directory mounts, and no published ports.
It applies an 8 GiB memory limit, 8 GiB combined memory/swap limit, 4-CPU quota,
4096 MiB guest RAM, and 4 guest vCPUs. It checks boot completion, services,
screenshot capture, rootless mode, and enforcing SELinux, then removes the test
state. These are basic functionality/boundary checks, not malware detection or
a complete audit of AVCs and vulnerabilities.

Logs, inspect output, and a screenshot are uploaded when available, with seven-day
retention. Hard runner cancellation can interrupt cleanup; inspect only that
job's orphaned `android-ci-*` containers/volumes before removing them.

```sh
scripts/verify-container smoke localhost/podman-android-emulator:api36
# Run on a suitable Linux host, not directly on macOS:
scripts/verify-container boot localhost/podman-android-emulator:api36
```

The smoke mode can use a Mac's remote Podman connection. Full boot mode requires
host-side Linux/SELinux checks. Neither mode uses an existing Android AVD volume.
A passing source-check job is not evidence of a working runtime image.

## Dependency updates

Dependabot keeps the SHA-pinned GitHub Actions current (`.github/dependabot.yml`).
`.github/workflows/upstream-updates.yml` runs weekly and opens an issue for each
newer stable emulator, SDK command-line tools build, system image revision or
Ubuntu base digest than recorded in `upstream-watch.json`.
