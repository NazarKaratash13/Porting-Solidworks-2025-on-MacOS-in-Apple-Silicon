/*
 * A minimal Win32 GUI program: registers a class, opens a window, paints it,
 * and closes itself on a timer. Hosted on Wine's unix side, every user32 and
 * gdi32 call below runs lifted Wine code down to the NtUser/NtGdi syscalls,
 * which win32u.so and winemac.so serve natively.
 */
#include <stddef.h>
#include <stdint.h>

#define WINAPI __attribute__((ms_abi))
#define IMPORT __declspec(dllimport)
typedef void *HANDLE, *HWND, *HDC, *HBRUSH, *HINSTANCE, *HICON, *HCURSOR, *HMENU;
typedef uint16_t WCHAR, ATOM;
typedef uint32_t DWORD, UINT;
typedef int32_t BOOL, LONG;
typedef uint64_t WPARAM, UINT_PTR;
typedef int64_t LPARAM, LRESULT;
typedef LRESULT (WINAPI *WNDPROC)(HWND, UINT, WPARAM, LPARAM);
typedef struct { LONG left, top, right, bottom; } RECT;
typedef struct { LONG x, y; } POINT;
typedef struct { HWND hwnd; UINT message; WPARAM wParam; LPARAM lParam; DWORD time; POINT pt; DWORD lPrivate; } MSG;
typedef struct { HDC hdc; BOOL fErase; RECT rcPaint; BOOL fRestore, fIncUpdate; uint8_t rgbReserved[32]; } PAINTSTRUCT;
typedef struct {
    UINT cbSize, style; WNDPROC lpfnWndProc; int cbClsExtra, cbWndExtra; HINSTANCE hInstance;
    HICON hIcon; HCURSOR hCursor; HBRUSH hbrBackground; const WCHAR *lpszMenuName, *lpszClassName; HICON hIconSm;
} WNDCLASSEXW;

IMPORT __declspec(noreturn) void WINAPI ExitProcess(UINT);
IMPORT HANDLE WINAPI GetStdHandle(DWORD);
IMPORT BOOL WINAPI WriteFile(HANDLE, const void *, DWORD, DWORD *, void *);
IMPORT HINSTANCE WINAPI GetModuleHandleW(const WCHAR *);
IMPORT ATOM WINAPI RegisterClassExW(const WNDCLASSEXW *);
IMPORT HWND WINAPI CreateWindowExW(DWORD, const WCHAR *, const WCHAR *, DWORD, int, int, int, int, HWND, HMENU, HINSTANCE, void *);
IMPORT BOOL WINAPI ShowWindow(HWND, int);
IMPORT BOOL WINAPI GetMessageW(MSG *, HWND, UINT, UINT);
IMPORT BOOL WINAPI TranslateMessage(const MSG *);
IMPORT LRESULT WINAPI DispatchMessageW(const MSG *);
IMPORT LRESULT WINAPI DefWindowProcW(HWND, UINT, WPARAM, LPARAM);
IMPORT BOOL WINAPI DestroyWindow(HWND);
IMPORT void WINAPI PostQuitMessage(int);
IMPORT UINT_PTR WINAPI SetTimer(HWND, UINT_PTR, UINT, void *);
IMPORT HDC WINAPI BeginPaint(HWND, PAINTSTRUCT *);
IMPORT BOOL WINAPI EndPaint(HWND, const PAINTSTRUCT *);
IMPORT int WINAPI FillRect(HDC, const RECT *, HBRUSH);
IMPORT BOOL WINAPI GetClientRect(HWND, RECT *);
IMPORT HBRUSH WINAPI CreateSolidBrush(DWORD);
IMPORT BOOL WINAPI DeleteObject(void *);

enum { WM_CREATE = 0x0001, WM_DESTROY = 0x0002, WM_PAINT = 0x000f, WM_TIMER = 0x0113,
       WS_OVERLAPPEDWINDOW = 0x00cf0000, SW_SHOWNORMAL = 1 };

static int created, painted;
static LONG client_width, client_height;

#ifdef STANDALONE_ABI_FIXTURE
IMPORT DWORD WINAPI GetLastError(void);
IMPORT DWORD WINAPI dependency_ready(void);
typedef struct {
    void *param;
    HINSTANCE instance;
    HMENU menu;
    HWND parent;
    int height, width, y, x;
    LONG style;
    const WCHAR *title, *class_name;
    DWORD ex_style;
} CREATESTRUCTW;
_Static_assert(sizeof(MSG) == 48 && offsetof(MSG, lPrivate) == 44, "MSG");
_Static_assert(sizeof(CREATESTRUCTW) == 80 && offsetof(CREATESTRUCTW, x) == 44, "CREATESTRUCTW");
_Static_assert(sizeof(PAINTSTRUCT) == 72 && offsetof(PAINTSTRUCT, rcPaint) == 12, "PAINTSTRUCT");
enum { WM_QUIT = 0x12, WM_NCCREATE = 0x81, WM_NCDESTROY = 0x82 };
static int destroyed, nc_destroyed;
static HWND shown_window;
static int creation_cookie;
static HINSTANCE fixture_instance;
#define MEMORY_CANARY UINT64_C(0x1122334455667788)

typedef HWND (WINAPI *create_window_fn)(DWORD, const WCHAR *, const WCHAR *, DWORD,
                                        int, int, int, int, HWND, HMENU, HINSTANCE, void *);

__attribute__((noinline))
static HWND WINAPI tail_create(DWORD ext, const WCHAR *class_name, const WCHAR *title,
                               DWORD style, int x, int y, int width, int height,
                               HWND parent, HMENU menu, HINSTANCE instance, void *arg) {
    __attribute__((musttail))
    return CreateWindowExW(ext, class_name, title, style, x, y, width, height, parent, menu, instance, arg);
}
#endif

static void say(const char *text) {
    DWORD length = 0, written;
    while (text[length]) ++length;
    WriteFile(GetStdHandle((DWORD)-11), text, length, &written, NULL);
}

static void say_number(const char *label, long value) {
    char digits[24], *end = digits + sizeof digits, *p = end;
    *--p = 0;
    *--p = '\n';
    unsigned long v = value < 0 ? 0 : (unsigned long)value;
    do *--p = (char)('0' + v % 10); while (v /= 10);
    say(label);
    say(p);
}

static LRESULT WINAPI window_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    switch (message) {
#ifdef STANDALONE_ABI_FIXTURE
    case WM_NCCREATE: {
        const CREATESTRUCTW *create = (const CREATESTRUCTW *)(uintptr_t)lparam;
        if (!create || create->param != &creation_cookie || create->instance != fixture_instance ||
            create->x != -23 || create->y != -19 || create->width != 480 || create->height != 320 ||
            create->style != WS_OVERLAPPEDWINDOW || create->parent || create->menu || create->ex_style)
            ExitProcess(14);
        return 1;
    }
    case WM_NCDESTROY:
        ++nc_destroyed;
        return 0;
#endif
    case WM_CREATE:
        ++created;
#ifndef STANDALONE_ABI_FIXTURE
        SetTimer(hwnd, 1, 2000, NULL);
#endif
        return 0;
    case WM_PAINT: {
#ifdef STANDALONE_ABI_FIXTURE
        struct { PAINTSTRUCT paint; uint64_t canary; } paint = { .canary = MEMORY_CANARY };
        PAINTSTRUCT *ps = &paint.paint;
#else
        PAINTSTRUCT data;
        PAINTSTRUCT *ps = &data;
#endif
        RECT client;
        HDC hdc = BeginPaint(hwnd, ps);
        HBRUSH brush = CreateSolidBrush(0x00c86e28); /* BGR */
        BOOL got_rect = GetClientRect(hwnd, &client);
        int filled = FillRect(hdc, &client, brush);
        BOOL deleted = DeleteObject(brush);
        BOOL ended = EndPaint(hwnd, ps);
#ifdef STANDALONE_ABI_FIXTURE
        if (!hdc || !got_rect || !filled || !deleted || !ended || paint.canary != MEMORY_CANARY)
            ExitProcess(15);
#endif
        client_width = client.right - client.left;
        client_height = client.bottom - client.top;
        ++painted;
        return 0;
    }
    case WM_TIMER:
        DestroyWindow(hwnd);
        return 0;
    case WM_DESTROY:
#ifdef STANDALONE_ABI_FIXTURE
        ++destroyed;
        if (hwnd == shown_window) PostQuitMessage(23);
#else
        PostQuitMessage(0);
#endif
        return 0;
    }
    return DefWindowProcW(hwnd, message, wparam, lparam);
}

void entry(void) {
    static const WCHAR class_name[] = {'F','i','x','t','u','r','e','W','i','n','d','o','w',0};
    static const WCHAR title[] = {'L','i','f','t','e','d',' ','w','i','n','d','o','w',0};
    HINSTANCE instance = GetModuleHandleW(NULL);
    WNDCLASSEXW wc = {.cbSize = sizeof wc, .style = 3, .lpfnWndProc = window_proc, .hInstance = instance,
                      .lpszClassName = class_name};
    ATOM window_class = RegisterClassExW(&wc);
    if (!window_class) {
        say("RegisterClassExW failed\n");
        ExitProcess(10);
    }
    say("registered class\n");
#ifdef STANDALONE_ABI_FIXTURE
    fixture_instance = instance;
    if (dependency_ready() != 42) ExitProcess(16);
    if (GetMessageW(NULL, NULL, 0, 0) != -1 || GetLastError() != 87) ExitProcess(17);
    const WCHAR *atom = (const WCHAR *)(uintptr_t)window_class;
    HWND hwnd = CreateWindowExW(0, class_name, title, WS_OVERLAPPEDWINDOW, -23, -19, 480, 320,
                                NULL, NULL, instance, &creation_cookie);
    if (!hwnd || !DestroyWindow(hwnd)) ExitProcess(18);
    create_window_fn volatile indirect_create = CreateWindowExW;
    hwnd = indirect_create(0, atom, title, WS_OVERLAPPEDWINDOW, -23, -19, 480, 320,
                           NULL, NULL, instance, &creation_cookie);
    if (!hwnd || !DestroyWindow(hwnd)) ExitProcess(19);
    hwnd = tail_create(0, class_name, title, WS_OVERLAPPEDWINDOW, -23, -19, 480, 320,
                        NULL, NULL, instance, &creation_cookie);
    if (!hwnd || created != 3) ExitProcess(20);
    shown_window = hwnd;
    if (!SetTimer(hwnd, 1, 250, NULL)) ExitProcess(21);
#else
    HWND hwnd = CreateWindowExW(0, class_name, title, WS_OVERLAPPEDWINDOW, 200, 200, 480, 320,
                                NULL, NULL, instance, NULL);
    if (!hwnd || created != 1) {
        say("CreateWindowExW failed\n");
        ExitProcess(11);
    }
#endif
    say("created window\n");
    ShowWindow(hwnd, SW_SHOWNORMAL);
    struct { MSG message; uint64_t canary; } guarded = { .canary = UINT64_C(0x1122334455667788) };
    int status;
    while ((status = GetMessageW(&guarded.message, NULL, 0, 0)) > 0) {
        TranslateMessage(&guarded.message);
        DispatchMessageW(&guarded.message);
    }
    if (status < 0 || guarded.canary != UINT64_C(0x1122334455667788)) ExitProcess(13);
#ifdef STANDALONE_ABI_FIXTURE
    if (guarded.message.message != WM_QUIT || guarded.message.wParam != 23 ||
        destroyed != 3 || nc_destroyed != 3) ExitProcess(22);
    say("standalone GUI ABI and DLL passed\n");
#endif
    say_number("paints ", painted);
    say_number("client width ", client_width);
    say_number("client height ", client_height);
    ExitProcess(painted ? 0 : 12);
}
