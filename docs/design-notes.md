# Design notes

Background on the technical decisions.

## GPU rendering

Rendering is software only (`-gpu swiftshader_indirect`). Hardware rendering is
not possible with stock krunkit (tested with krunkit 1.3.2, libkrun 1.19.8 and
MoltenVK 1.4.2):

- **krunkit exposes Venus (Vulkan) only.** VirGL (OpenGL) is disabled, so the VM
  has no OpenGL path.
- **Page sizes differ.** The Linux guest uses 4 KiB pages and macOS 16 KiB. Stock
  Mesa Venus cannot map its shared command ring without a guest-side patch.
- **No OpenGL ES 3 over Vulkan.** ANGLE needs `VK_EXT_provoking_vertex` for
  ES 3, which MoltenVK lacks, so it offers ES 2 only. Zink fails because
  `nullDescriptor` is unsupported.
- **Android needs ES 3.** With ES 2, Android boots on the Apple GPU but renders
  the content area black and fails to open apps.

ES 3 was only reached by modifying krunkit and libkrun, which this project does
not do. Revisit if krunkit gains an OpenGL path or MoltenVK the missing features.

## SwiftShader JIT under SELinux

SwiftShader originally placed JIT code in heap memory and made it executable,
which enforcing SELinux denies for containers (`execheap`); the renderer then
crashed. The patch (`patches/swiftshader-jit-mmap.patch`) uses dedicated memory
mappings that switch from writable to executable, aborts if that fails, and
flushes instruction caches. No SELinux policy was changed. The alternative, a
custom SELinux domain allowing `execheap`, would weaken exploit protection and
was not used.

## KVM address space

krunkit's VM supports a 36-bit guest physical address space. Unpatched QEMU
creates VMs with the default address size, which fails (`KVM_CREATE_VM` returns
`EINVAL`), and places the high PCI window at 512 GiB–1 TiB on Linux. The QEMU
patch queries `KVM_CAP_ARM_VM_IPA_SIZE`, creates the VM with a supported size,
and bounds the high PCI window by it. It refuses hosts below 36 bits and any
overlap between RAM and the PCI window.

## libuuid TLS corruption

The prebuilt `libuuid.a` uses local-exec TLS relocations, which are only valid in
executables. Linked into a shared library, its random-number state overlapped
QEMU's `current_cpu` thread-local pointer, and the emulator crashed after boot.
`scripts/build-upstream-uuid` rebuilds it from the pinned Google source archive
with `-fPIC -ftls-model=global-dynamic` and rejects local-exec relocations.

## Alternatives considered

- **Running the emulator directly on macOS** gives GPU acceleration and Google's
  signed binaries, but no isolation from your user account.
- **Cuttlefish** runs Android on crosvm. Its rootless container setup needs
  `/dev/net/tun`, `/dev/vhost-net`, `/dev/vhost-vsock` and the `NET_ADMIN` and
  `NET_RAW` capabilities, has no Google APIs images, and would hit the same GPU
  limits in this VM.
- **Prebuilt third-party emulator binaries** were rejected because they cannot
  be traced to source.
