# Testing other Android versions

Android 16 / API 36 is the validated target. Other Google APIs ARM64 images can
be checked with:

```sh
scripts/test-android-version 35
scripts/test-android-version 33 localhost/podman-android-emulator:api36
```

Each run downloads the Google APIs ARM64 image into a disposable container and
starts it with the default launcher (`start-android`) on a fresh AVD, so the
emulator flags and the guest Bluetooth policy are the same as the default runtime. The working `android` container and its
volume are not used or stopped. No host ports are published. Rootless execution
is checked; no security settings are relaxed. SDK licenses accepted in the base
image apply to downloads; review them before running.

Run tests sequentially to limit VM disk use. The disposable container, downloaded
system image, and AVD are removed afterward; results, image revision metadata,
container configuration, guest logs, and a screenshot (if booted) remain under
`diagnostics/api-<API>/`. These local files are not committed. Copy results before
rerunning the same API, since that output directory is reused.

A pass requires boot completion, Zygote and SurfaceFlinger running, and successful
home-screen/screenshot commands. Review boot animation state, screenshot, and logs
as well; a pass is a basic compatibility check, not a CTS or long-duration test.
The boot timeout is seven minutes after SDK installation, not including downloads.
No renderer fallback is applied.

For reproducibility, compare `system-image.properties` and the pinned emulator /
SwiftShader source revisions. Google can update the SDK image revision between
runs. Check each image's minimum emulator dependency against the source-built
version. System image variants such as Google Play and 16 KiB page images are not
covered by testing the standard Google APIs ARM64 package.
