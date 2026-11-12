# podman-android-emulator

Run the Android emulator in a rootless Podman container on Apple Silicon.

The emulator is built from Google's upstream source for Linux ARM64 and runs an
official **Android 16 (API 36) Google APIs** system image inside the Podman
machine's Linux VM. The container only gets `/dev/kvm`: no privileged mode, no
added capabilities, SELinux enforcing. That makes it suitable for giving tools
and AI agents an Android device without access to your Mac.

> **Personal project.** I built this for my own use and publish it as is,
> without support, security fixes or any warranty. Issues and pull requests
> may go unanswered. Review it yourself before you rely on it.
>
> **Experimental.** Android 16 boots and runs apps with software rendering.
> Bluetooth is not available and there is no hardware GPU. See
> [limitations](#limitations).

## Requirements

- A Mac with Apple Silicon that supports nested virtualization. Only an M5 Max
  has been tested.
- [Podman](https://podman.io/) with a rootless machine using the `libkrun`
  provider ([krunkit](https://github.com/containers/krunkit)). The VM needs
  `/dev/kvm` (krunkit runs with nested virtualization) and 4 KiB pages.
- About 6 GB of VM disk for the image, plus space for the Android data volume.
- Acceptance of the [Android SDK license](https://developer.android.com/studio/terms),
  because you build the image that contains the system image yourself.

Tested on an M5 Max with macOS 27.2, Podman 6.2 (client) / 6.0.1 (machine) and
krunkit 1.3.2.

Check your machine:

```sh
podman info --format '{{.Host.Security.Rootless}}'            # true
podman machine ssh 'ls -l /dev/kvm; getconf PAGESIZE; getenforce'  # device, 4096, Enforcing
```

## Quick start

The published image contains the emulator but no Google SDK components, which
may not be redistributed. You add the system image with a local build.

1. Pick a release and verify its image (see [releases](docs/releases.md)):

   ```sh
   image=ghcr.io/wmontwe/podman-android-emulator
   digest=sha256:...   # from the release's image-<tag>.digest asset
   cosign verify "$image@$digest" \
     --certificate-oidc-issuer https://token.actions.githubusercontent.com \
     --certificate-identity-regexp '^https://github.com/wmontwe/podman-android-emulator/\.github/workflows/release\.yml@refs/(tags/v.*|heads/main)$'
   ```

2. Build the local image. This downloads the SDK tools and the system image and
   accepts the Android SDK licenses:

   ```sh
   podman build --platform linux/arm64 --build-arg BASE_IMAGE="$image@$digest" \
     -t localhost/podman-android-emulator:api36 -f Containerfile.local .
   ```

3. Start Android:

   ```sh
   scripts/run-android
   podman logs -f android
   ```

   The first boot creates the virtual device and takes about a minute and a half.

## Using the device

ADB is published on `127.0.0.1:5555` only.

```sh
podman exec android adb -s emulator-5554 shell getprop sys.boot_completed   # 1 when booted
adb connect 127.0.0.1:5555                                                  # from the Mac
podman exec android adb -s emulator-5554 exec-out screencap -p > screen.png
```

Stop it with `podman stop android`; the emulator shuts down cleanly. Android's
data persists in the `android-api36-data` volume.

## Configuration

`scripts/run-android` starts the container with these limits:

| Resource | Default |
|---|---|
| Android RAM | 4096 MiB |
| Android CPUs | 4 |
| Container memory (including swap) | 8 GiB |
| Container CPUs | 4 |
| Shared memory | 1 GiB |

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `ANDROID_IMAGE` | `localhost/podman-android-emulator:api36` | Image to run; never pulled automatically |
| `ANDROID_CONTAINER_NAME` | `android` | Container name |
| `ANDROID_DATA_VOLUME` | `android-api36-data` | Volume for Android data |
| `ANDROID_ADB_PORT` | `5555` | Loopback port for ADB |

Use a separate volume per Android version and never run two emulators on the
same volume. Starting `podman run` by hand skips the resource limits.

## Limitations

- **Software rendering only.** Rendering uses SwiftShader OpenGL ES on the
  container's CPUs; the guest has no Vulkan. That is fine for typical apps, UI
  tests and WebView content, but not for games, Vulkan apps or graphics
  benchmarks. Stock krunkit offers no hardware OpenGL ES 3; see
  [design notes](docs/design-notes.md#gpu-rendering).
- **No Bluetooth or UWB.** The Linux ARM64 emulator build lacks the `netsimd`
  helper, so Wi-Fi uses the legacy backend, the guest Bluetooth stack is
  disabled, and UWB reports itself as unavailable.
- **Google APIs, not Google Play.** Play services are included; the Play Store
  is not.
- **The WebView does not update itself.** Without the Play Store, it stays at the
  system image's version. Rebuild the local image when a new system image
  revision is released.
- **First boot of a new device is slow.** Play services set up for several
  minutes; later boots take about 45 s.
- **Validation is limited** to boot, lifecycle, memory and WebView tests; see
  [validation](docs/validation.md).

## Documentation

- [Releases](docs/releases.md): image contents, signature verification, release procedure
- [Building from source](docs/building-from-source.md): building the emulator and images yourself
- [Validation](docs/validation.md): what has been tested
- [Testing other Android versions](docs/android-versions.md)
- [Design notes](docs/design-notes.md): GPU, SELinux, KVM fixes, alternatives
- [CI](docs/container-ci.md)
- [Security](SECURITY.md)

## License

This project's scripts, Containerfiles and documentation are licensed under the
[Apache License 2.0](LICENSE). The images contain third-party software under
their own licenses: the emulator (Apache-2.0, see its `NOTICE.txt`), QEMU
(GPL-2.0) and Ubuntu packages. The Android system image and SDK tools in the
local image are covered by the Android SDK License Agreement; see
[releases](docs/releases.md).
