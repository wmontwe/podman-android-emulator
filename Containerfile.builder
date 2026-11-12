# Cross-build host for Google's Linux ARM64 emulator target.
# Invoke with --platform linux/amd64; requires existing binfmt support on ARM.
FROM docker.io/library/ubuntu:24.04@sha256:9c7f200c07e3d4a03e7249d2c16bf66a51120fb876aa2242cf31451412543289
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git python3 build-essential crossbuild-essential-arm64 \
    cmake ninja-build pkg-config bison flex zip unzip zstd curl ccache \
    libssl-dev libffi-dev libxml2-dev libglib2.0-dev libdrm-dev \
    libx11-dev libxext-dev libxrandr-dev libxinerama-dev libxcursor-dev \
    libpulse-dev libasound2-dev libgl1-mesa-dev && \
    rm -rf /var/lib/apt/lists/*
COPY scripts/fetch-upstream-sources.py /usr/local/libexec/fetch-upstream-sources.py
COPY upstream-source.lock.json /etc/upstream-source.lock.json
COPY scripts/patch-upstream-qemu.py /usr/local/libexec/patch-upstream-qemu.py
COPY scripts/build-upstream-emulator /usr/local/libexec/build-upstream-emulator
COPY scripts/build-upstream-uuid /usr/local/libexec/build-upstream-uuid
RUN chmod +x /usr/local/libexec/build-upstream-emulator /usr/local/libexec/build-upstream-uuid
WORKDIR /work
# No compiler/source execution is started by the image entrypoint.
ENTRYPOINT ["/bin/bash"]
