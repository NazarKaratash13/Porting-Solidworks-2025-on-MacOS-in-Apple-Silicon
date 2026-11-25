#include "win32.h"

__declspec(dllexport) DWORD dependency_data;
static DWORD *volatile ready_pointer = &dependency_data;

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved) {
    (void)instance;
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH)
        dependency_data = 42;
    return TRUE;
}

__declspec(dllexport) DWORD WINAPI dependency_ready(void) {
    return *ready_pointer;
}

#ifdef FIXTURE_UNSUPPORTED_EXPORT
__declspec(dllexport) void WINAPI unsupported_fixture_export(void) {
    __asm__ volatile("pabsb %%xmm0, %%xmm0" ::: "xmm0");
}
#endif
