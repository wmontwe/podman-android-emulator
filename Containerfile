# Release image: Linux ARM64 Android emulator built from Google upstream source.
# Contains no Android SDK components covered by the SDK license (no system image,
# command-line tools, or platform-tools). Containerfile.local adds those locally.
# No prebuilt emulator binaries are downloaded by this build.
FROM docker.io/library/ubuntu:24.04@sha256:9c7f200c07e3d4a03e7249d2c16bf66a51120fb876aa2242cf31451412543289

ARG DEBIAN_FRONTEND=noninteractive
ARG ANDROID_API=36
LABEL org.opencontainers.image.title="podman-android-emulator" \
      org.opencontainers.image.description="Source-built Linux ARM64 Android emulator for rootless Podman; add an Android system image locally" \
      org.opencontainers.image.source="https://github.com/wmontwe/podman-android-emulator"
ENV ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    ANDROID_API=${ANDROID_API} \
    ANDROID_MEMORY_MB=4096 \
    ANDROID_CORES=4
ENV PATH="${ANDROID_HOME}/platform-tools:${PATH}"
ENV LD_LIBRARY_PATH="${ANDROID_HOME}/emulator/lib64:${ANDROID_HOME}/emulator/lib64/gles_swiftshader"

# adb comes from Ubuntu's open-source package, not Google's SDK platform-tools.
RUN test "$(dpkg --print-architecture)" = arm64 && \
    apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates adb socat python3 \
    libasound2t64 libdbus-1-3 libfontconfig1 libfreetype6 libgl1 \
    libnss3 libpulse0 libx11-6 libxcb1 libxcomposite1 libxcursor1 \
    libxi6 libxrandr2 libxrender1 libxtst6 libxkbcommon0 libvulkan1 && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p "$ANDROID_HOME/platform-tools" "$ANDROID_HOME/platforms" && \
    ln -sf /usr/bin/adb "$ANDROID_HOME/platform-tools/adb"

# Distribution includes recorded SDK registration matching source.properties. Build intentionally
# fails when these inputs are absent; there is no binary-download fallback.
COPY build-inputs/emulator/ /opt/android-sdk/emulator/
COPY build-inputs/provenance.json /usr/share/android-emulator/provenance.json
COPY scripts/verify-upstream-input.py /usr/local/libexec/verify-upstream-input.py
COPY scripts/check-sdk-image-compatibility.py /usr/local/libexec/check-sdk-image-compatibility.py
COPY scripts/verify-upstream-release.py /usr/local/libexec/verify-upstream-release.py
COPY upstream-release-target.json /usr/share/android-emulator/release-target.json
RUN python3 /usr/local/libexec/verify-upstream-release.py \
      /usr/share/android-emulator/release-target.json /usr/share/android-emulator/provenance.json && \
    python3 /usr/local/libexec/verify-upstream-input.py \
      /opt/android-sdk/emulator /usr/share/android-emulator/provenance.json

COPY scripts/start-android /usr/local/bin/start-android
RUN chmod +x /usr/local/bin/start-android
EXPOSE 15555
VOLUME ["/root/.android"]
ENTRYPOINT ["/usr/local/bin/start-android"]
