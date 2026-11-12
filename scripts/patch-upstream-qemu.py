#!/usr/bin/env python3
"""Apply narrow source fixes only to the pinned, clean upstream QEMU revision.

Produces a reviewable unified diff and hash record. These source regions are
identical to the older diagnostic baseline; the new build still needs validation.
"""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REVISION = '223638d03d23f1eeb303535ed5d55d4f211107fd'


def apply(root):
    actual = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != REVISION:
        raise ValueError('Refusing an unexpected QEMU revision')
    subprocess.run(['git', '-C', str(root), 'diff', '--exit-code', 'HEAD', '--'], check=True)
    replacements = {
        'linux-headers/linux/kvm.h': [(
            '#define KVM_CAP_GET_MSR_FEATURES 153',
            '#define KVM_CAP_GET_MSR_FEATURES 153\n'
            '/* Linux UAPI capability for explicit ARM VM IPA width selection. */\n'
            '#define KVM_CAP_ARM_VM_IPA_SIZE 165')],
        'accel/kvm/kvm-all.c': [(
            '    do {\n        ret = kvm_ioctl(s, KVM_CREATE_VM, type);',
            '''#ifdef TARGET_AARCH64
    /* VM type zero implies 40-bit IPA, unsupported on some ARM64 KVM hosts.
     * Preserve explicit machine selections and non-ARM behavior.
     */
    if (!kvm_type && type == 0) {
        int ipa_bits = kvm_check_extension(s, KVM_CAP_ARM_VM_IPA_SIZE);
        if (ipa_bits > 0 && ipa_bits < 40) {
            if (ipa_bits < 36) {
                ret = -EINVAL;
                error_report("ARM64 virt requires at least 36 IPA bits");
                goto err;
            }
            type = ipa_bits;
        }
    }
#endif

    do {
        ret = kvm_ioctl(s, KVM_CREATE_VM, type);''')],
        'target/arm/kvm.c': [(
            '    int ret, kvmfd = -1, vmfd = -1, cpufd = -1;',
            '    int ret, kvmfd = -1, vmfd = -1, cpufd = -1;\n'
            '    int vm_type = 0;\n#ifdef TARGET_AARCH64\n    int ipa_bits;\n#endif'), (
            '    vmfd = ioctl(kvmfd, KVM_CREATE_VM, 0);',
            '''    /* CPU feature probing creates a scratch VM before normal machine
     * initialization. It must obey the same host IPA limit as the real VM.
     */
#ifdef TARGET_AARCH64
    ipa_bits = ioctl(kvmfd, KVM_CHECK_EXTENSION, KVM_CAP_ARM_VM_IPA_SIZE);
    if (ipa_bits >= 32 && ipa_bits < 40) {
        vm_type = ipa_bits;
    }
#endif
    vmfd = ioctl(kvmfd, KVM_CREATE_VM, vm_type);'''), (
            'int kvm_arch_init(MachineState *ms, KVMState *s)\n{',
            '''int kvm_arm_get_max_ipa_bits(void)
{
    int bits = kvm_check_extension(kvm_state, KVM_CAP_ARM_VM_IPA_SIZE);
    /* Older kernels without the extension retain the default 40-bit IPA. */
    return bits > 0 ? bits : 40;
}

int kvm_arch_init(MachineState *ms, KVMState *s)
{''')],
        'target/arm/kvm_arm.h': [(
            'int kvm_arm_vgic_probe(void);',
            'int kvm_arm_get_max_ipa_bits(void);\nint kvm_arm_vgic_probe(void);'), (
            'static inline int kvm_arm_vgic_probe(void)\n{',
            'static inline int kvm_arm_get_max_ipa_bits(void)\n{\n    return 40;\n}\n\n'
            'static inline int kvm_arm_vgic_probe(void)\n{')],
        'include/hw/arm/virt.h': [(
            '    const MemMapEntry *memmap;',
            '    MemMapEntry memmap_storage[VIRT_SECURE_MEM + 1];\n'
            '    const MemMapEntry *memmap;')],
        'hw/arm/virt.c': [(
            '    vms->memmap = a15memmap;',
            '    QEMU_BUILD_BUG_ON(sizeof(vms->memmap_storage) != sizeof(a15memmap));\n'
            '    memcpy(vms->memmap_storage, a15memmap, sizeof(a15memmap));\n'
            '    vms->memmap = vms->memmap_storage;'), (
            '    bool firmware_loaded = bios_name || drive_get(IF_PFLASH, 0, 0);',
            '''    bool firmware_loaded = bios_name || drive_get(IF_PFLASH, 0, 0);

#ifdef TARGET_AARCH64
    if (kvm_enabled() && vms->highmem) {
        int ipa_bits = kvm_arm_get_max_ipa_bits();
        if (ipa_bits > 0 && ipa_bits < 40) {
            hwaddr high_base;
            if (ipa_bits < 36) {
                error_report("ARM64 virt requires at least 36 IPA bits");
                exit(1);
            }
            high_base = 1ULL << (ipa_bits - 1);
            /* High PCI occupies the upper half of the supported IPA space.
             * Reject RAM overlap rather than silently aliasing guest memory.
             */
            if (machine->ram_size > high_base - vms->memmap[VIRT_MEM].base) {
                error_report("Guest RAM overlaps the supported high PCI window");
                exit(1);
            }
            vms->memmap_storage[VIRT_PCIE_MMIO_HIGH].base = high_base;
            vms->memmap_storage[VIRT_PCIE_MMIO_HIGH].size = high_base;
        }
    }
#endif''')],
    }
    changes = {}
    for relative, edits in replacements.items():
        before = (root / relative).read_text()
        after = before
        for old, new in edits:
            if after.count(old) != 1:
                raise ValueError(f'Unexpected source layout: {relative}')
            after = after.replace(old, new, 1)
        changes[relative] = (before, after)
    diff = ''.join(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                      fromfile='a/' + relative, tofile='b/' + relative))
                   for relative, (before, after) in changes.items())
    for relative, (_, after) in changes.items():
        (root / relative).write_text(after)
    record = {
        'source_revision': REVISION,
        'patch_sha256': hashlib.sha256(diff.encode()).hexdigest(),
        'status': 'source-applied-not-compiled-or-boot-validated',
        'files': {relative: {'before': hashlib.sha256(before.encode()).hexdigest(),
                             'after': hashlib.sha256(after.encode()).hexdigest()}
                  for relative, (before, after) in changes.items()},
    }
    (root.parent / 'local-ipa-pci.patch').write_text(diff)
    (root.parent / 'local-ipa-pci.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Applied source-only IPA/PCI fixes; compile and boot validation still required')


if __name__ == '__main__':
    apply(Path(sys.argv[1]))
