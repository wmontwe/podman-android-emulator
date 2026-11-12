# Security

## No security support

This is a personal project, published as is and without warranty (see the
[license](LICENSE)). There is no vulnerability reporting process and no promise
of security fixes or updated images. Vulnerabilities in the emulator, QEMU,
Android or the system image belong upstream at Google.

## Isolation model

Android runs as a VM inside the emulator, inside a rootless container, inside the
Podman machine's Linux VM. An escape from Android must break through each layer
to reach your Mac.

The container runs with:

- Rootless Podman: container root maps to your unprivileged VM user.
- SELinux enforcing and the default seccomp profile.
- Only `/dev/kvm`; no privileged mode and no added capabilities.
- No host directory mounts, credentials or container-engine socket.
- ADB published on host loopback only.
- Memory and CPU limits from `scripts/run-android`.

Do not weaken these defaults (privileged mode, disabled SELinux labels, extra
capabilities, disabled seccomp) to work around a problem.

## What to keep in mind

- **`/dev/kvm`** exposes the KVM kernel interface to the emulator; that is the
  main attack surface toward the VM.
- **ADB** gives full control of Android. Never publish it beyond loopback.
- **Shared Podman machine.** Containers in the same machine share its kernel.
  A dedicated machine isolates Android from your other containers.
- **WebView** in the system image does not update itself; rebuild the local
  image for new system image revisions, especially when rendering untrusted
  content.
- **Network.** The container has normal outbound network access unless you
  restrict it.
- **Build provenance.** The emulator is built from pinned source, but release
  provenance cannot prove that; see [releases](docs/releases.md#what-the-provenance-proves).
