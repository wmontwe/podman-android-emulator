/* Run only in an isolated Linux ARM64 test container. Link against a DSO
 * embedding libuuid.a: random UUID generation must not modify executable TLS.
 * This catches the pinned non-PIC archive's local-exec TLS corruption without
 * booting Android or granting KVM access. */
#include <stdio.h>
#include <string.h>

extern void uuid_generate_random(unsigned char result[16]);
static __thread volatile unsigned char sentinel[256];

int main(void) {
    unsigned char result[16];
    for (unsigned int i = 0; i < sizeof(sentinel); ++i) sentinel[i] = 0xa5;
    for (unsigned int n = 0; n < 32; ++n) uuid_generate_random(result);
    for (unsigned int i = 0; i < sizeof(sentinel); ++i) {
        if (sentinel[i] != 0xa5) {
            fprintf(stderr, "Executable TLS corrupted at byte %u: %#x\n", i, sentinel[i]);
            return 1;
        }
    }
    puts("UUID generation preserved executable TLS");
    return 0;
}
