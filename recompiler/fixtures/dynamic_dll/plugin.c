#include "win32.h"


IMPORT DWORD WINAPI dependency_ready(void);
IMPORT DWORD dependency_data;

static DWORD slot = TLS_OUT_OF_INDEXES;

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved) {
    (void)instance;
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        if (dependency_ready() != 42 || dependency_data != 42)
            return 0;
        dependency_data = 43;
        if (dependency_ready() != 43)
            return 0;
        dependency_data = 42;
        slot = TlsAlloc();
        return slot != TLS_OUT_OF_INDEXES;
    }
    if (reason == DLL_PROCESS_DETACH)
        TlsFree(slot);
    return TRUE;
}

typedef DWORD (WINAPI *Callback)(DWORD);

__declspec(dllexport) DWORD WINAPI call_plugin(DWORD value, Callback callback) {
    if (!TlsSetValue(slot, (LPVOID)(ULONG_PTR)value))
        return 0;
    return callback(value) + (DWORD)(ULONG_PTR)TlsGetValue(slot);
}

__declspec(dllexport) DWORD WINAPI read_plugin_tls(void) {
    return (DWORD)(ULONG_PTR)TlsGetValue(slot);
}
