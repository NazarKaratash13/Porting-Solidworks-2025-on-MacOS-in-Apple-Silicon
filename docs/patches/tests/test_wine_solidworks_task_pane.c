#define _WIN32_WINNT 0x0a00
#include <windows.h>
#include <stdio.h>

static HWND make(HWND parent, PCWSTR class_name, PCWSTR title, DWORD style, int width)
{
    return CreateWindowExW(0, class_name, title, style, 0, 0, width, 400, parent, NULL,
                           GetModuleHandleW(NULL), NULL);
}

static BOOL position(HWND hwnd, int x, int width)
{
    return SetWindowPos(hwnd, NULL, x, 0, width, 400,
                        SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOSENDCHANGING);
}

static BOOL span(HWND hwnd, HWND origin, int x, int width)
{
    RECT rect;
    if (!GetWindowRect(hwnd, &rect)) return FALSE;
    if (origin) MapWindowPoints(NULL, origin, (POINT *)&rect, 2);
    if (x < 0) x = rect.left;
    printf("x=%ld width=%ld expected=%d,%d\n", rect.left, rect.right - rect.left, x, width);
    return rect.left == x && rect.right - rect.left == width;
}

int main(void)
{
    WNDCLASSW cls = {0};
    DWORD main_style = WS_POPUP | WS_THICKFRAME | WS_SYSMENU | WS_MAXIMIZEBOX;
    HWND target, other, mdi, pane, other_mdi, other_pane;
    UINT dpi;
    BOOL ok;

    if (!SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)) return 2;
    cls.lpfnWndProc = DefWindowProcW;
    cls.hInstance = GetModuleHandleW(NULL);
    cls.lpszClassName = L"V3BoundaryFixture";
    if (!RegisterClassW(&cls)) return 3;
    cls.lpszClassName = L"swMdiClient";
    if (!RegisterClassW(&cls)) return 3;
    target = make(NULL, L"V3BoundaryFixture", L"SOLIDWORKS Student Edition fixture", main_style, 2200);
    other = make(NULL, L"V3BoundaryFixture", L"Ordinary window fixture", main_style, 2200);
    if (!target || !other) return 4;
    mdi = make(target, L"swMdiClient", L"", WS_CHILD, 1244);
    other_mdi = make(other, L"swMdiClient", L"", WS_CHILD, 1244);
    if (!mdi || !other_mdi) return 5;
    pane = make(mdi, L"V3BoundaryFixture", L"Auto Hider", WS_CHILD, 300);
    other_pane = make(other_mdi, L"V3BoundaryFixture", L"Auto Hider", WS_CHILD, 300);
    if (!pane || !other_pane) return 6;
    dpi = GetDpiForWindow(target);
    printf("dpi=%u\n", dpi);
    if (dpi != 192) return 7;

    puts("Oversize Auto Hider inside target");
    ok = position(pane, 0, 1244) && span(pane, mdi, 830, 414);
    puts("Valid Auto Hider geometry");
    ok &= position(pane, 944, 300) && span(pane, mdi, 944, 300);
    puts("Same pane name in an ordinary window");
    ok &= position(other_pane, 0, 1244) && span(other_pane, other_mdi, 0, 1244);
    puts("Target frame lower bound");
    ok &= position(target, 0, 1254) && span(target, NULL, -1, 1640);
    puts("Unrelated frame width");
    ok &= position(other, 0, 1254) && span(other, NULL, -1, 1254);
    DestroyWindow(target);
    DestroyWindow(other);
    return !ok;
}
