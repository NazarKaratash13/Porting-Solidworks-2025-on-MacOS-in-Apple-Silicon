#include <stdint.h>

typedef unsigned long DWORD;
typedef void *HANDLE;
__declspec(dllimport) HANDLE GetStdHandle(DWORD);
__declspec(dllimport) int WriteFile(HANDLE, const void *, DWORD, DWORD *, void *);
__declspec(dllimport) __attribute__((noreturn)) void ExitProcess(DWORD);

static char output[] = "pcmpeq passed\n";

__attribute__((aligned(16))) static unsigned int a32[4] = { 10, 20, 30, 40 };
__attribute__((aligned(16))) static unsigned int b32[4] = { 10, 99, 30, 88 };
__attribute__((aligned(16))) static unsigned int r32[4] = { 0 };

__attribute__((aligned(16))) static unsigned short a16[8] = { 1, 2, 3, 4, 5, 6, 7, 8 };
__attribute__((aligned(16))) static unsigned short b16[8] = { 1, 0, 3, 0, 5, 0, 7, 0 };
__attribute__((aligned(16))) static unsigned short r16[8] = { 0 };

__attribute__((aligned(16))) static unsigned char a8[16] = { 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16 };
__attribute__((aligned(16))) static unsigned char b8[16] = { 1,0,3,0,5,0,7,0,9, 0,11, 0,13, 0,15, 0 };
__attribute__((aligned(16))) static unsigned char r8[16] = { 0 };

_Alignas(16) static uint64_t a64[2] = { UINT64_C(0x8000010203040506), UINT64_C(0xa1b2c3d4e5f60718) };
_Alignas(16) static uint64_t b64[2] = { UINT64_C(0x8000010203040506), UINT64_C(0x8010100102030405) };
_Alignas(16) static uint64_t r64[2];

static void check_polynomial_product(uint64_t left, uint64_t right) {
    uint64_t low = 0, high = 0;
    for (unsigned bit = 0; bit < 64; ++bit) {
        if ((right >> bit) & 1) {
            low ^= left << bit;
            if (bit) high ^= left >> (64 - bit);
        }
    }
    if (low != r64[0] || high != r64[1])
        ExitProcess(107);
}

static void check_new_instructions(void) {
    __asm__ volatile(
        "movdqu %1, %%xmm0\n\t"
        "movdqu %2, %%xmm1\n\t"
        "pcmpeqq %%xmm1, %%xmm0\n\t"
        "movdqu %%xmm0, %0"
        : "=m"(r64) : "m"(a64), "m"(b64) : "xmm0", "xmm1"
    );
    if (r64[0] != UINT64_MAX || r64[1] != 0)
        ExitProcess(105);
    __asm__ volatile(
        "movdqu %1, %%xmm0\n\t"
        "pcmpeqq %2, %%xmm0\n\t"
        "movdqu %%xmm0, %0"
        : "=m"(r64) : "m"(a64), "m"(b64) : "xmm0"
    );
    if (r64[0] != UINT64_MAX || r64[1] != 0)
        ExitProcess(106);

#define CHECK_PRODUCT(immediate, first, second) do {                               \
    __asm__ volatile("movdqu %1, %%xmm0\n\t"                                      \
                     "pclmulqdq $" #immediate ", %2, %%xmm0\n\t"                  \
                     "movdqu %%xmm0, %0"                                          \
                     : "=m"(r64) : "m"(a64), "m"(b64) : "xmm0");                  \
    check_polynomial_product(a64[first], b64[second]);                            \
} while (0)
    CHECK_PRODUCT(0x00, 0, 0);
    CHECK_PRODUCT(0x01, 1, 0);
    CHECK_PRODUCT(0x10, 0, 1);
    CHECK_PRODUCT(0xff, 1, 1);
#undef CHECK_PRODUCT

    static unsigned char replacement = 0xdf;
    uint32_t extracted;
    __asm__ volatile(
        "movdqu %2, %%xmm0\n\t"
        "pinsrd $6, %3, %%xmm0\n\t"
        "pinsrb $31, %4, %%xmm0\n\t"
        "pextrd $6, %%xmm0, %1\n\t"
        "movdqu %%xmm0, %0"
        : "=m"(r64), "=r"(extracted)
        : "m"(a64), "r"(UINT32_C(0x89abcdef)), "m"(replacement)
        : "xmm0"
    );
    if (extracted != UINT32_C(0x89abcdef) || r64[0] != a64[0] ||
        r64[1] != UINT64_C(0xdfb2c3d489abcdef))
        ExitProcess(108);

    static int32_t integers[2] = { INT32_MIN, INT32_MAX };
    __asm__ volatile("cvtdq2pd %1, %%xmm0\n\tmovdqu %%xmm0, %0"
                     : "=m"(r64) : "m"(integers) : "xmm0");
    union { double number; uint64_t bits; } lower = { .number = INT32_MIN },
                                          upper = { .number = INT32_MAX };
    if (r64[0] != lower.bits || r64[1] != upper.bits)
        ExitProcess(109);

    uint64_t accumulator = UINT64_C(0x1111222233338000);
    uint64_t extension = UINT64_C(0x0123456789abff00);
    __asm__ volatile("cwd" : "+a"(accumulator), "+d"(extension));
    if (accumulator != UINT64_C(0x1111222233338000) || extension != UINT64_C(0x0123456789abffff))
        ExitProcess(110);
}

void entry(void) {
    // 1. pcmpeqd self-comparison
    unsigned long long self_res[2] = {0};
    __asm__ volatile(
        "pcmpeqd %%xmm0, %%xmm0\n\t"
        "movdqu %%xmm0, %0"
        : "=m"(self_res)
        :
        : "xmm0"
    );
    if (self_res[0] != 0xffffffffffffffffULL || self_res[1] != 0xffffffffffffffffULL)
        ExitProcess(101);

    // 2. pcmpeqd vector comparison
    __asm__ volatile(
        "movdqu %1, %%xmm0\n\t"
        "movdqu %2, %%xmm1\n\t"
        "pcmpeqd %%xmm1, %%xmm0\n\t"
        "movdqu %%xmm0, %0"
        : "=m"(r32)
        : "m"(a32), "m"(b32)
        : "xmm0", "xmm1"
    );
    if (r32[0] != 0xffffffff || r32[1] != 0 || r32[2] != 0xffffffff || r32[3] != 0)
        ExitProcess(102);

    // 3. pcmpeqw vector comparison
    __asm__ volatile(
        "movdqu %1, %%xmm0\n\t"
        "movdqu %2, %%xmm1\n\t"
        "pcmpeqw %%xmm1, %%xmm0\n\t"
        "movdqu %%xmm0, %0"
        : "=m"(r16)
        : "m"(a16), "m"(b16)
        : "xmm0", "xmm1"
    );
    if (r16[0] != 0xffff || r16[1] != 0 || r16[2] != 0xffff || r16[3] != 0 ||
        r16[4] != 0xffff || r16[5] != 0 || r16[6] != 0xffff || r16[7] != 0)
        ExitProcess(103);

    // 4. pcmpeqb vector comparison
    __asm__ volatile(
        "movdqu %1, %%xmm0\n\t"
        "movdqu %2, %%xmm1\n\t"
        "pcmpeqb %%xmm1, %%xmm0\n\t"
        "movdqu %%xmm0, %0"
        : "=m"(r8)
        : "m"(a8), "m"(b8)
        : "xmm0", "xmm1"
    );
    if (r8[0] != 0xff || r8[1] != 0 || r8[2] != 0xff || r8[3] != 0)
        ExitProcess(104);

    check_new_instructions();
    DWORD written;
    int ok = WriteFile(GetStdHandle((DWORD)-11), output, sizeof(output) - 1, &written, 0);
    ExitProcess(!ok || written != sizeof(output) - 1);
}
