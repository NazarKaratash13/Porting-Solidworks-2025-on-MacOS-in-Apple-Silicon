/* Observe one SOLIDWORKS window and its Task Pane through Wine's Win32 API.
 * Build with x86_64-w64-mingw32-gcc -municode -O2 ... -o pane-trace.exe.
 * Run in the same prefix as SOLIDWORKS. Optional duration: 1–120 seconds.
 */
#define _WIN32_WINNT 0x0a00
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>

enum { FRAME, CLIENT, PANE, TABS, WINDOW_COUNT };
static const WCHAR *const window_names[] = {L"", L"swMdiClient", L"Auto Hider", L"Task Pane Tabs Wnd"};
static HWND windows[WINDOW_COUNT];
static DWORD start_tick;
static HKEY pane_key;

struct window_state
{
    RECT per_monitor, unaware;
    UINT dpi;
    DPI_AWARENESS awareness;
    BOOL visible;
    BOOL has_per_monitor, has_unaware;
};

struct snapshot
{
    struct window_state windows[WINDOW_COUNT];
    DWORD pane_width, vertical_width;
};

static struct snapshot last;

static BOOL CALLBACK find_frame(HWND window, LPARAM unused)
{
    WCHAR title[256];
    static const WCHAR prefix[] = L"SOLIDWORKS Student Edition";
    (void)unused;
    if (IsWindowVisible(window) && GetWindowTextW(window, title, 256) &&
        !wcsncmp(title, prefix, ARRAYSIZE(prefix) - 1))
    {
        windows[FRAME] = window;
        return FALSE;
    }
    return TRUE;
}

static BOOL CALLBACK find_children(HWND window, LPARAM unused)
{
    WCHAR title[128] = {0}, class_name[128] = {0};
    (void)unused;
    GetWindowTextW(window, title, ARRAYSIZE(title));
    GetClassNameW(window, class_name, ARRAYSIZE(class_name));
    for (int i = CLIENT; i < WINDOW_COUNT; i++)
        if (!wcscmp(title, window_names[i]) || !wcscmp(class_name, window_names[i]))
            windows[i] = window;
    return TRUE;
}

static DWORD read_width(const WCHAR *name)
{
    DWORD width;
    DWORD size = sizeof(width);
    return RegGetValueW(pane_key, NULL, name, RRF_RT_REG_DWORD, NULL, &width, &size)
           == ERROR_SUCCESS ? width : MAXDWORD;
}

static void print_rect(RECT rect, BOOL valid)
{
    if (valid) printf("%ld,%ld,%ld,%ld", rect.left, rect.top, rect.right, rect.bottom);
    else fputs("unavailable", stdout);
}

static void capture(DWORD event, DWORD event_tick)
{
    struct snapshot state = {0};
    if (!windows[CLIENT] || !IsWindow(windows[CLIENT]) ||
        !windows[PANE] || !IsWindow(windows[PANE]))
        EnumChildWindows(windows[FRAME], find_children, 0);

    DPI_AWARENESS_CONTEXT prior =
        SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE);
    for (int i = 0; i < WINDOW_COUNT; i++)
    {
        HWND window = windows[i];
        struct window_state *sample = &state.windows[i];
        if (!IsWindow(window)) continue;
        sample->has_per_monitor = GetWindowRect(window, &sample->per_monitor);
        sample->dpi = GetDpiForWindow(window);
        sample->awareness = GetAwarenessFromDpiAwarenessContext(GetWindowDpiAwarenessContext(window));
        sample->visible = IsWindowVisible(window);
    }
    SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_UNAWARE);
    for (int i = 0; i < WINDOW_COUNT; i++)
        if (IsWindow(windows[i]))
            state.windows[i].has_unaware = GetWindowRect(windows[i], &state.windows[i].unaware);
    if (prior) SetThreadDpiAwarenessContext(prior);

    state.pane_width = read_width(L"paneWndWidth");
    state.vertical_width = read_width(L"sizeVertCX");
    if (!memcmp(&state, &last, sizeof(state)) &&
        event != EVENT_SYSTEM_MOVESIZESTART && event != EVENT_SYSTEM_MOVESIZEEND)
        return;
    last = state;

    printf("t=%lu event=%#lx event_t=%ld registry=%lu,%lu",
           GetTickCount() - start_tick, event, (LONG)(event_tick - start_tick),
           state.pane_width, state.vertical_width);
    for (int i = 0; i < WINDOW_COUNT; i++)
    {
        struct window_state *sample = &state.windows[i];
        printf(" %c=%p/", "FCPT"[i], windows[i]);
        print_rect(sample->per_monitor, sample->has_per_monitor);
        putchar('/');
        print_rect(sample->unaware, sample->has_unaware);
        printf("/%u,%d,%d", sample->dpi, sample->awareness, sample->visible);
    }
    putchar('\n');
    fflush(stdout);
}

static void CALLBACK on_event(HWINEVENTHOOK hook, DWORD event, HWND window, LONG object,
                              LONG child, DWORD thread, DWORD tick)
{
    (void)hook;
    (void)thread;
    if (object != OBJID_WINDOW || child != CHILDID_SELF) return;
    for (int i = 0; i < WINDOW_COUNT; i++)
        if (window == windows[i])
        {
            capture(event, tick);
            return;
        }
}

int wmain(int argc, WCHAR **argv)
{
    int seconds = argc == 2 ? _wtoi(argv[1]) : 120;
    if (argc > 2 || seconds < 1 || seconds > 120)
    {
        fputs("Usage: pane-trace.exe [seconds, 1–120]\n", stderr);
        return 2;
    }
    EnumWindows(find_frame, 0);
    if (!windows[FRAME])
    {
        fputs("No visible SOLIDWORKS frame\n", stderr);
        return 1;
    }
    DWORD process = 0;
    GetWindowThreadProcessId(windows[FRAME], &process);
    if (RegOpenKeyExW(HKEY_CURRENT_USER,
                      L"Software\\SolidWorks\\SOLIDWORKS 2025\\User Interface\\General-Bar-59465",
                      0, KEY_QUERY_VALUE, &pane_key) != ERROR_SUCCESS)
    {
        fputs("Task Pane preferences are unavailable\n", stderr);
        return 1;
    }

    start_tick = GetTickCount();
    HWINEVENTHOOK live_resize = SetWinEventHook(EVENT_SYSTEM_MOVESIZESTART, EVENT_SYSTEM_MOVESIZEEND,
                                               NULL, on_event, process, 0, WINEVENT_OUTOFCONTEXT);
    HWINEVENTHOOK layout = SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_LOCATIONCHANGE,
                                          NULL, on_event, process, 0, WINEVENT_OUTOFCONTEXT);
    printf("pid=%lu hooks=%d,%d; frame/client/pane/tabs = hwnd/PM rect/unaware rect/dpi,awareness,visible\n",
           process, live_resize != NULL, layout != NULL);
    do
    {
        MSG msg;
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) DispatchMessageW(&msg);
        capture(0, GetTickCount());
        MsgWaitForMultipleObjects(0, NULL, FALSE, 25, QS_ALLINPUT);
    } while (GetTickCount() - start_tick < (DWORD)seconds * 1000 && IsWindow(windows[FRAME]));
    if (layout) UnhookWinEvent(layout);
    if (live_resize) UnhookWinEvent(live_resize);
    RegCloseKey(pane_key);
    return 0;
}
