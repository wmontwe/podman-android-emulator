# Validation

What has been tested for emulator **37.3.10** with the Android 16 (API 36)
Google APIs system image, revision 7. All tests ran on an M5 Max Mac with
krunkit, rootless Podman, SELinux enforcing, only `/dev/kvm` passed, and the
default limits (4 GiB / 4 CPUs for Android, 8 GiB / 4 CPUs for the container).

## Results

| Test | Result |
|---|---|
| Boot | Boots in about 70–100 s, including first-start device creation. The VM was also running other workloads (load average about 8 on 10 CPUs). 37.2.12 booted in about 44 s on an idle VM. |
| Services | Zygote and SurfaceFlinger running, boot animation finished, guest SELinux enforcing |
| ADB and screenshots | Working, using Ubuntu's `adb` 34.0.4 |
| Shutdown | Clean in about 1–3 s, no forced kill |
| App lifecycle memory | 36 restarts of Settings: host memory levels off at about 810 MB after 6 restarts. Container anonymous memory stays at about 4.8 GB of 8 GB (guest RAM is capped at 4 GiB), plus about 1.7 GB of reclaimable page cache |
| Fresh and persistent device | Both boot; no guest crashes and no `system_server` crashes recorded |
| Release/local image split | Local image built on the release image boots and passes all checks above |
| Stripped distribution | Without Qt, windowed and 32-bit QEMU, the glibc bundle, x86 firmware and the x86-64 llvmpipe libraries; the emulator runs `qemu-system-aarch64-headless` |
| Runtime update | `Containerfile.runtime-update` builds against the release target |
| WebView | WebView 133 (HTMLViewer) renders an HTML email (tables, inline CSS, images, gradients) and scrolls; 24 open/close cycles: host memory flat (1,128 → 1,133 MB), no crashes or ANRs |
| Network | Guest Wi-Fi validates (DNS, HTTP, HTTPS); Chrome loads and scrolls a JavaScript-heavy page |

## Issues found and fixed

- **Startup hang without `netsimd`.** The ARM64 distribution has no `netsimd`,
  and the default Wi-Fi backend waited for it until the watchdog killed the
  emulator. The launcher now selects legacy Wi-Fi and disables Bluetooth
  emulation when `netsimd` is missing.
- **WebView hang.** The emulator offered the guest Vulkan, but the distribution
  has no host Vulkan driver. WebView's GPU thread then waited forever for its
  first Vulkan call, spinning at 100% CPU until the app (and later System UI)
  stopped responding. The launcher now disables the emulator's Vulkan feature,
  so Android renders with OpenGL ES through SwiftShader.
- **UWB retry loop.** Disabling UWB emulation left the guest without its UWB
  port, while the system image still declares UWB hardware. Android then tried
  to start the missing UWB HAL several times a second, keeping about 17% of a
  guest CPU busy. UWB emulation now stays enabled; Android reports UWB as
  unavailable once and stops.
- **Bluetooth crashes in the guest.** The guest Bluetooth stack aborted on every
  boot. The launcher turns guest Bluetooth off from launch, disables the
  Bluetooth package and BLE scanning after boot, and stops the emulator if that
  fails within 3 minutes of boot completion.
- **Graphics memory leak.** Before Google's gfxstream fix
  [`a5b0def9`](https://android.googlesource.com/platform/hardware/google/gfxstream/+/a5b0def9cd0f858b3fc9e2fa88a11a6271f46b02),
  host memory grew by about 90 MB per app restart until the container hit its
  limit. 37.2.12 needed a local backport; 37.3.10 includes the fix.

| Same Settings restart workload | Restarts | Host memory growth |
|---|---:|---:|
| 37.2.12 without fix | 12 | 1.06 GiB |
| 37.2.12 with backport | 36 | 107 MiB (warm-up, then flat) |
| 37.3.10 | 36 | 182 MiB (warm-up, then flat) |

## Known limitations

- **First boot is heavy.** On a fresh device, Google Play services set up for
  several minutes after boot completes, and Android may report a few apps not
  responding during that time. The network may take up to two minutes to come
  up. Later boots of the same device take about 45 s and are quiet. Wait for
  the load to settle before using a new device.

## Not tested

- Real app workloads, such as signing in to a mail app, and frame rates.
- Google account sign-in and Play Integrity.
- Other Android versions (see [testing other versions](android-versions.md)).
- Builds other than this ARM64 build; results do not transfer to Google's SDK
  binaries.
