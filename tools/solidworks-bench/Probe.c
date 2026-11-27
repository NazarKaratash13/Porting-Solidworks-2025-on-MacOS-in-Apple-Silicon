/* Attach to a running SOLIDWORKS session to measure test-document operations. */
#define wmain file_bridge_main
#include "../solidworks-v3-file-bridge.c"
#undef wmain
#include <math.h>
#include "UiWindow.h"

static double now_ms(void)
{
    LARGE_INTEGER elapsed, frequency;
    QueryPerformanceCounter(&elapsed);
    QueryPerformanceFrequency(&frequency);
    return 1000.0 * elapsed.QuadPart / frequency.QuadPart;
}

static IDispatch *get_object(IDispatch *object, WCHAR *name, WORD flags)
{
    VARIANT value;
    if (SUCCEEDED(invoke(object, name, flags, NULL, 0, &value)) &&
        V_VT(&value) == VT_DISPATCH)
        return V_DISPATCH(&value); /* transfer the reference */
    VariantClear(&value);
    return NULL;
}

static BOOL ready(IDispatch *app, const WCHAR *expected)
{
    VARIANT started, path;
    IDispatch *doc;
    BOOL matches;

    invoke(app, L"StartupProcessCompleted", DISPATCH_PROPERTYGET, NULL, 0, &started);
    BOOL completed = V_VT(&started) == VT_BOOL && V_BOOL(&started);
    VariantClear(&started);
    if (!completed || !(doc = get_object(app, L"ActiveDoc", DISPATCH_PROPERTYGET))) return FALSE;
    invoke(doc, L"GetPathName", DISPATCH_METHOD, NULL, 0, &path);
    matches = V_VT(&path) == VT_BSTR && V_BSTR(&path) && !_wcsicmp(V_BSTR(&path), expected);
    VariantClear(&path);
    IDispatch_Release(doc);
    return matches;
}

static int report_view_flag(IDispatch *object, WCHAR *name, WORD flags, VARIANT *argument)
{
    VARIANT result;
    HRESULT hr = invoke(object, name, flags, argument, argument ? 1 : 0, &result);
    int value = SUCCEEDED(hr) && V_VT(&result) == VT_BOOL ? !!V_BOOL(&result) : -1;
    printf("%ls hr=0x%08lx vt=%u flag=%d\n", name, (unsigned long)hr, V_VT(&result), value);
    VariantClear(&result);
    return value;
}

static int inspect_view(IDispatch *app, const WCHAR *path, const WCHAR *action)
{
    BOOL change_realview = !wcscmp(action, L"real-on") || !wcscmp(action, L"real-off");
    BOOL change_tree = !wcscmp(action, L"hide-tree") || !wcscmp(action, L"show-tree");
    if (!change_realview && !change_tree && wcscmp(action, L"inspect")) return 2;
    if (!ready(app, path)) return 3;

    IDispatch *doc = get_object(app, L"ActiveDoc", DISPATCH_PROPERTYGET);
    if (!doc) return 3;
    IDispatch *ext = get_object(doc, L"Extension", DISPATCH_PROPERTYGET);
    if (!ext)
    {
        IDispatch_Release(doc);
        return 4;
    }

    report_view_flag(ext, L"ViewDisplayRealView", DISPATCH_PROPERTYGET, NULL);
    if (change_realview)
    {
        VARIANT flag = bool_argument(!wcscmp(action, L"real-on"));
        report_view_flag(ext, L"ViewDisplayRealView", DISPATCH_PROPERTYPUT, &flag);
        report_view_flag(doc, L"GraphicsRedraw2", DISPATCH_METHOD, NULL);
    }
    if (change_tree)
    {
        VARIANT hide = bool_argument(!wcscmp(action, L"hide-tree"));
        report_view_flag(ext, L"HideFeatureManager", DISPATCH_METHOD, &hide);
    }
    int realview = report_view_flag(ext, L"ViewDisplayRealView", DISPATCH_PROPERTYGET, NULL);

    IDispatch *view_manager = get_object(doc, L"ModelViewManager", DISPATCH_PROPERTYGET);
    if (view_manager)
    {
        report_view_flag(view_manager, L"FeatureManagerTabsVisible", DISPATCH_PROPERTYGET, NULL);
        IDispatch_Release(view_manager);
    }
    IDispatch *feature_manager = get_object(doc, L"FeatureManager", DISPATCH_PROPERTYGET);
    if (feature_manager)
    {
        VARIANT pane = integer(1), root;
        HRESULT hr = invoke(feature_manager, L"GetFeatureTreeRootItem2", DISPATCH_METHOD, &pane, 1, &root);
        BOOL present = SUCCEEDED(hr) && V_VT(&root) == VT_DISPATCH && V_DISPATCH(&root);
        printf("FeatureManagerRoot hr=0x%08lx present=%d\n", (unsigned long)hr, present);
        VariantClear(&root);
        IDispatch_Release(feature_manager);
    }
    IDispatch_Release(ext);
    IDispatch_Release(doc);
    return !wcscmp(action, L"real-off") && realview != 0 ? 5 : 0;
}

static BOOL disable_render_toggle(IDispatch *app, LONG preference)
{
    VARIANT args[] = {bool_argument(FALSE), integer(preference)}, result;
    invoke(app, L"SetUserPreferenceToggle", DISPATCH_METHOD, args, ARRAYSIZE(args), &result);
    VariantClear(&result);
    HRESULT hr = invoke(app, L"GetUserPreferenceToggle", DISPATCH_METHOD, &args[1], 1, &result);
    BOOL off = SUCCEEDED(hr) && V_VT(&result) == VT_BOOL && !V_BOOL(&result);
    VariantClear(&result);
    return off;
}

static int plain_view(IDispatch *app, const WCHAR *path)
{
    enum { shadows_in_shaded_mode = 131, ambient_occlusion_shadows = 485, realview_graphics = 814 };
    if (!ready(app, path)) return 3;
    BOOL shadows_off = disable_render_toggle(app, shadows_in_shaded_mode);
    BOOL ambient_occlusion_off = disable_render_toggle(app, ambient_occlusion_shadows);
    BOOL realview_off = disable_render_toggle(app, realview_graphics);
    printf("effects_off %d %d %d\n", shadows_off, ambient_occlusion_off, realview_off);
    if (!shadows_off || !ambient_occlusion_off || !realview_off) return 5;
    return inspect_view(app, path, L"real-off");
}

static BOOL fixtures_are_saved(IDispatch *app, const WCHAR *root)
{
    const size_t length = wcslen(root);
    VARIANT document;

    if ((length && root[length - 1] != L'\\') ||
        FAILED(invoke(app, L"GetFirstDocument", DISPATCH_METHOD, NULL, 0, &document)))
        return FALSE;
    while (V_VT(&document) == VT_DISPATCH && V_DISPATCH(&document))
    {
        IDispatch *doc = V_DISPATCH(&document);
        VARIANT path, dirty, next;
        invoke(doc, L"GetPathName", DISPATCH_METHOD, NULL, 0, &path);
        invoke(doc, L"GetSaveFlag", DISPATCH_METHOD, NULL, 0, &dirty);
        BOOL allowed = V_VT(&path) == VT_BSTR && V_BSTR(&path) && *V_BSTR(&path) &&
                       (!length || !_wcsnicmp(V_BSTR(&path), root, length)) &&
                       V_VT(&dirty) == VT_BOOL && !V_BOOL(&dirty);
        HRESULT hr = allowed ? invoke(doc, L"GetNext", DISPATCH_METHOD, NULL, 0, &next) : E_FAIL;
        VariantClear(&path);
        VariantClear(&dirty);
        VariantClear(&document);
        if (FAILED(hr)) return FALSE;
        document = next;
    }
    BOOL exhausted = V_VT(&document) == VT_EMPTY || V_VT(&document) == VT_NULL ||
                     (V_VT(&document) == VT_DISPATCH && !V_DISPATCH(&document));
    VariantClear(&document);
    return exhausted;
}

static int measure(IDispatch *app, const WCHAR *source, const WCHAR *copy)
{
    if (GetFileAttributesW(copy) != INVALID_FILE_ATTRIBUTES) return 2;
    double before = now_ms();
    if (open_document(app, source)) return 3;
    double open_ms = now_ms() - before;
    if (!ready(app, source)) return 3;
    IDispatch *doc = get_object(app, L"ActiveDoc", DISPATCH_PROPERTYGET);
    if (!doc) return 3;
    VARIANT result, top_only = bool_argument(FALSE);
    before = now_ms();
    HRESULT hr = invoke(doc, L"ForceRebuild3", DISPATCH_METHOD, &top_only, 1, &result);
    double rebuild_ms = now_ms() - before;
    BOOL rebuilt = SUCCEEDED(hr) && V_VT(&result) == VT_BOOL && V_BOOL(&result);
    VariantClear(&result);

    before = now_ms();
    int saved = save_document(doc, copy, 3);
    double save_ms = now_ms() - before;
    IDispatch_Release(doc);
    if (!rebuilt || saved)
    {
        printf("Rebuild returned %d; save status %d\n", rebuilt, saved);
        return 4;
    }
    printf("%.3f %.3f %.3f\n", open_ms, rebuild_ms, save_ms);
    return 0;
}

static BOOL real_property(IDispatch *object, WCHAR *name, double *value)
{
    VARIANT result;
    HRESULT hr = invoke(object, name, DISPATCH_PROPERTYGET, NULL, 0, &result);
    BOOL valid = SUCCEEDED(hr) && V_VT(&result) == VT_R8 && isfinite(V_R8(&result));
    if (valid) *value = V_R8(&result);
    VariantClear(&result);
    return valid;
}

static int verify_model(IDispatch *app, const WCHAR *source, WCHAR **outputs)
{
    for (int i = 0; outputs && i < 3; ++i)
        if (GetFileAttributesW(outputs[i]) != INVALID_FILE_ATTRIBUTES) return 2;
    double started = now_ms();
    if (open_document(app, source) || !ready(app, source)) return 3;
    const double opened = now_ms() - started;
    IDispatch *doc = get_object(app, L"ActiveDoc", DISPATCH_PROPERTYGET);
    if (!doc) return 3;
    VARIANT result, top_only = bool_argument(FALSE);
    started = now_ms();
    HRESULT hr = invoke(doc, L"ForceRebuild3", DISPATCH_METHOD, &top_only, 1, &result);
    const double rebuilt = now_ms() - started;
    BOOL valid = SUCCEEDED(hr) && V_VT(&result) == VT_BOOL && V_BOOL(&result);
    VariantClear(&result);

    IDispatch *ext = get_object(doc, L"Extension", DISPATCH_PROPERTYGET);
    IDispatch *mass = ext ? get_object(ext, L"CreateMassProperty2", DISPATCH_METHOD) : NULL;
    double kg = 0, cubic_metres = 0;
    if (mass)
    {
        VARIANT system_units = bool_argument(TRUE);
        hr = invoke(mass, L"UseSystemUnits", DISPATCH_PROPERTYPUT, &system_units, 1, &result);
        VariantClear(&result);
    }
    valid = valid && mass && SUCCEEDED(hr) && real_property(mass, L"Mass", &kg) &&
            real_property(mass, L"Volume", &cubic_metres) && kg > 0 && cubic_metres > 0;
    if (mass) IDispatch_Release(mass);
    if (ext) IDispatch_Release(ext);
    if (!valid)
    {
        IDispatch_Release(doc);
        return 4;
    }
    printf("model open_ms=%.3f rebuild_ms=%.3f mass_kg=%.15g volume_m3=%.15g\n",
           opened, rebuilt, kg, cubic_metres);
    if (!outputs)
    {
        IDispatch_Release(doc);
        return 0;
    }

    VARIANT all = bool_argument(TRUE);
    hr = invoke(doc, L"ClearSelection2", DISPATCH_METHOD, &all, 1, &result);
    VariantClear(&result);
    int status = FAILED(hr) ? 5 : 0;
    for (int i = 0; i < 3 && !status; ++i)
        status = save_document(doc, outputs[i], 3) ? 6 : 0;
    IDispatch_Release(doc);
    return status;
}

static VARIANT real(double value)
{
    VARIANT arg;
    VariantInit(&arg);
    V_VT(&arg) = VT_R8;
    V_R8(&arg) = value;
    return arg;
}

static int orbit(IDispatch *app)
{
    IDispatch *doc = get_object(app, L"ActiveDoc", DISPATCH_PROPERTYGET);
    if (!doc) return 3;
    IDispatch *view = get_object(doc, L"ActiveView", DISPATCH_PROPERTYGET);
    if (!view) { IDispatch_Release(doc); return 3; }
    HRESULT hr = S_OK;
    for (int i = 0; i < 54 && SUCCEEDED(hr); ++i)
    {
        VARIANT result, angles[] = {real(0.026), real(0.008)};
        hr = invoke(view, L"RotateAboutCenter", DISPATCH_METHOD, angles, 2, &result);
        VariantClear(&result);
        Sleep(42);
    }
    IDispatch_Release(view);
    IDispatch_Release(doc);
    return FAILED(hr) ? 5 : 0;
}

static int scene(IDispatch *app, const WCHAR *path)
{
    BOOL was_active = ready(app, path);
    double start = now_ms();
    if (!was_active && (open_document(app, path) || !ready(app, path))) return 3;
    double open_ms = now_ms() - start;
    IDispatch *doc = get_object(app, L"ActiveDoc", DISPATCH_PROPERTYGET);
    if (!doc) return 3;
    VARIANT count, top_level = bool_argument(FALSE), revision;
    invoke(doc, L"GetComponentCount", DISPATCH_METHOD, &top_level, 1, &count);
    LONG components = V_VT(&count) == VT_I4 ? V_I4(&count) : -1;
    VariantClear(&count);
    IDispatch_Release(doc);
    printf("scene %.6f %ld %d\n", open_ms, (long)components, was_active);
    if (SUCCEEDED(invoke(app, L"RevisionNumber", DISPATCH_METHOD, NULL, 0, &revision)) &&
        V_VT(&revision) == VT_BSTR && V_BSTR(&revision))
        utf8_line(V_BSTR(&revision));
    VariantClear(&revision);
    return 0;
}

static int rebuild_scene(IDispatch *app, const WCHAR *path)
{
    if (!ready(app, path)) return 3;
    IDispatch *doc = get_object(app, L"ActiveDoc", DISPATCH_PROPERTYGET);
    if (!doc) return 3;
    VARIANT result, top_only = bool_argument(FALSE);
    double start = now_ms();
    HRESULT hr = invoke(doc, L"ForceRebuild3", DISPATCH_METHOD, &top_only, 1, &result);
    double elapsed = now_ms() - start;
    BOOL rebuilt = SUCCEEDED(hr) && V_VT(&result) == VT_BOOL && V_BOOL(&result);
    VariantClear(&result);
    IDispatch_Release(doc);
    printf("rebuild %.6f %d %#lx\n", elapsed, rebuilt, (unsigned long)hr);
    return 0;
}

static int shade_scene(IDispatch *app, const WCHAR *path)
{
    if (!ready(app, path)) return 3;
    IDispatch *doc = get_object(app, L"ActiveDoc", DISPATCH_PROPERTYGET);
    if (!doc) return 3;
    VARIANT result;
    HRESULT hr = invoke(doc, L"ViewDisplayShaded", DISPATCH_METHOD, NULL, 0, &result);
    VariantClear(&result);
    IDispatch_Release(doc);
    return FAILED(hr) ? 5 : 0;
}

static LONG detail_value(IDispatch *object, WCHAR *name, WORD flags, VARIANT *args, UINT count)
{
    VARIANT result;
    LONG value = -1;
    if (SUCCEEDED(invoke(object, name, flags, args, count, &result)))
    {
        if (V_VT(&result) == VT_I4 && V_I4(&result) >= 0) value = V_I4(&result);
        if (V_VT(&result) == VT_BOOL) value = V_BOOL(&result) ? 1 : 0;
    }
    VariantClear(&result);
    return value;
}

/* Enum values from the SOLIDWORKS 2025 swconst type library. */
enum { lod_preference = 233, large_assembly_preference = 297, large_assembly_threshold = 194 };

static int detail_state(IDispatch *app, const WCHAR *path)
{
    if (!ready(app, path)) return 3;
    IDispatch *doc = get_object(app, L"ActiveDoc", DISPATCH_PROPERTYGET);
    if (!doc) return 3;

    VARIANT lod = integer(lod_preference);
    VARIANT enabled = integer(large_assembly_preference);
    VARIANT threshold = integer(large_assembly_threshold);
    printf("detail %ld %ld %ld %ld %ld\n",
           detail_value(app, L"GetUserPreferenceIntegerValue", DISPATCH_METHOD, &lod, 1),
           detail_value(doc, L"LargeAssemblyMode", DISPATCH_PROPERTYGET, NULL, 0),
           detail_value(doc, L"GetLightWeightComponentCount", DISPATCH_METHOD, NULL, 0),
           detail_value(app, L"GetUserPreferenceToggle", DISPATCH_METHOD, &enabled, 1),
           detail_value(app, L"GetUserPreferenceIntegerValue", DISPATCH_METHOD, &threshold, 1));
    IDispatch_Release(doc);
    return 0;
}

static int prepare_detail(IDispatch *app, const WCHAR *path)
{
    if (!ready(app, path)) return 3;
    VARIANT lod[] = {integer(0), integer(lod_preference)};
    if (detail_value(app, L"SetUserPreferenceIntegerValue", DISPATCH_METHOD, lod, 2) != 1 ||
        !disable_render_toggle(app, large_assembly_preference)) return 5;
    return 0;
}

static int frame_size(IDispatch *app, const WCHAR *path, const WCHAR *width, const WCHAR *height)
{
    if (!ready(app, path)) return 3;
    HWND frame = com_frame_window(app);
    if (!frame) return 5;
    if (width)
    {
        LONG w = _wtol(width), h = _wtol(height);
        if (w < 700 || h < 550 || w > 10000 || h > 10000) return 2;
        if (!SetWindowPos(frame, NULL, 0, 0, w, h, SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOZORDER)) return 5;
    }
    RECT rect;
    if (!GetWindowRect(frame, &rect)) return 5;
    printf("size %ld %ld\n", rect.right - rect.left, rect.bottom - rect.top);
    return 0;
}

static BOOL reset_view(IDispatch *doc)
{
    VARIANT result;
    VARIANT orientation[] = {integer(7), string(L"*Isometric")};
    HRESULT status = invoke(doc, L"ShowNamedView2", DISPATCH_METHOD, orientation, 2, &result);
    VariantClear(&orientation[1]);
    VariantClear(&result);
    if (FAILED(status)) return FALSE;
    status = invoke(doc, L"ViewZoomtofit2", DISPATCH_METHOD, NULL, 0, &result);
    VariantClear(&result);
    return SUCCEEDED(status);
}

static int timed_view(IDispatch *app, const WCHAR *path, const WCHAR *steps, const WCHAR *pace,
                      BOOL inspect_only, BOOL cache_dispatch)
{
    WCHAR *end;
    unsigned long count = wcstoul(steps, &end, 10);
    if (*end || count < 2 || count > 2000) return 2;
    unsigned long pace_ms = wcstoul(pace, &end, 10);
    if (*end || pace_ms > 1000) return 2;
    if (!ready(app, path)) return 3;
    IDispatch *doc = get_object(app, L"ActiveDoc", DISPATCH_PROPERTYGET);
    if (!doc) return 3;
    IDispatch *view = NULL;
    VARIANT result;
    if (!inspect_only)
    {
        if (reset_view(doc))
            view = get_object(doc, L"ActiveView", DISPATCH_PROPERTYGET);
        if (!view) { IDispatch_Release(doc); return 5; }
        Sleep(300);
    }
    IDispatch *target = inspect_only ? doc : view;
    WCHAR *method = inspect_only ? L"GetType" : L"RotateAboutCenter";
    DISPID id = DISPID_UNKNOWN;
    HRESULT hr = S_OK;
    if (cache_dispatch)
        hr = IDispatch_GetIDsOfNames(target, &IID_NULL, &method, 1, LOCALE_USER_DEFAULT, &id);
    double *durations = SUCCEEDED(hr) ? calloc(count, sizeof(*durations)) : NULL;
    if (!durations)
    {
        if (view) IDispatch_Release(view);
        IDispatch_Release(doc);
        return 2;
    }
    double start = now_ms();
    for (unsigned long i = 0; i < count; ++i)
    {
        double before = now_ms();
        VARIANT angles[] = {real(0.026), real(0.008)};
        DISPPARAMS args = {.rgvarg = inspect_only ? NULL : angles, .cArgs = inspect_only ? 0 : 2};
        if (cache_dispatch)
        {
            VariantInit(&result);
            hr = IDispatch_Invoke(target, id, &IID_NULL, LOCALE_USER_DEFAULT,
                                  DISPATCH_METHOD, &args, &result, NULL, NULL);
        }
        else hr = invoke(target, method, DISPATCH_METHOD, args.rgvarg, args.cArgs, &result);
        durations[i] = now_ms() - before;
        VariantClear(&result);
        if (FAILED(hr)) break;
        double remaining = start + (i + 1) * (double)pace_ms - now_ms();
        if (remaining > 1 && i + 1 < count) Sleep((DWORD)remaining);
    }
    double finish = now_ms();
    if (SUCCEEDED(hr))
    {
        printf("phase %.6f %.6f\n", start, finish);
        for (unsigned long i = 0; i < count; ++i) printf("%.6f\n", durations[i]);
    }
    free(durations);
    if (view) IDispatch_Release(view);
    IDispatch_Release(doc);
    return FAILED(hr) ? 5 : 0;
}

static BOOL send_mouse(DWORD flags, LONG x, LONG y)
{
    INPUT event = {.type = INPUT_MOUSE, .mi = {.dx = x, .dy = y, .dwFlags = flags}};
    return SendInput(1, &event, sizeof(event)) == 1;
}

static BOOL camera_scale(IDispatch *app, double *scale)
{
    IDispatch *doc = get_object(app, L"ActiveDoc", DISPATCH_PROPERTYGET);
    IDispatch *view = doc ? get_object(doc, L"ActiveView", DISPATCH_PROPERTYGET) : NULL;
    BOOL valid = view && real_property(view, L"Scale2", scale) && *scale > 0;
    if (view) IDispatch_Release(view);
    if (doc) IDispatch_Release(doc);
    return valid;
}

static int mouse_view(IDispatch *app, const WCHAR *path, const WCHAR *steps, const WCHAR *pace)
{
    WCHAR *end;
    unsigned long count = wcstoul(steps, &end, 10);
    if (*end || count < 2 || count > 2000) return 2;
    unsigned long pace_ms = wcstoul(pace, &end, 10);
    if (*end || !pace_ms || pace_ms > 1000 || count * pace_ms > 120000) return 2;
    if (!ready(app, path)) return 3;

    IDispatch *doc = get_object(app, L"ActiveDoc", DISPATCH_PROPERTYGET);
    if (!doc) return 3;
    BOOL reset = reset_view(doc);
    IDispatch_Release(doc);
    if (!reset) return 5;
    Sleep(300);
    double scale_before, scale_after;
    if (!camera_scale(app, &scale_before)) return 5;
    HWND root = GetForegroundWindow();
    RECT bounds;
    WCHAR title[1024];
    const WCHAR *filename = wcsrchr(path, L'\\');
    HWND frame = com_frame_window(app);
    BOOL matches = frame ? GetAncestor(frame, GA_ROOT) == root :
        filename && GetWindowTextW(root, title, ARRAYSIZE(title)) && wcsstr(title, filename + 1);
    if (!root || !matches || !GetWindowRect(root, &bounds))
    {
        fputs("The foreground window is not the verified SOLIDWORKS frame.\n", stderr);
        return 6;
    }
    if (bounds.right - bounds.left < 700 || bounds.bottom - bounds.top < 550)
    {
        fputs("The frame is too small for the orbit path.\n", stderr);
        return 6;
    }

    POINT center = {(bounds.left + bounds.right) / 2,
                    bounds.top + (bounds.bottom - bounds.top) * 55 / 100};
    HWND viewport = WindowFromPoint(center);
    DWORD frame_pid = 0, hit_pid = 0;
    GetWindowThreadProcessId(root, &frame_pid);
    DWORD gui_thread = GetWindowThreadProcessId(viewport, &hit_pid);
    if (!gui_thread || frame_pid != hit_pid || GetAncestor(viewport, GA_ROOT) != root ||
        GetAsyncKeyState(VK_MBUTTON) < 0 || GetAsyncKeyState(VK_SHIFT) < 0 ||
        GetAsyncKeyState(VK_CONTROL) < 0 || GetAsyncKeyState(VK_MENU) < 0)
    {
        fputs("The intended drag does not hit the verified SOLIDWORKS frame.\n", stderr);
        return 6;
    }
    double *durations = calloc(count, sizeof(*durations));
    if (!durations) return 2;

    POINT saved;
    BOOL moved = GetCursorPos(&saved) && SetCursorPos(center.x, center.y);
    if (moved) Sleep(150);
    double start = now_ms();
    BOOL down = moved && GetForegroundWindow() == root && send_mouse(MOUSEEVENTF_MIDDLEDOWN, 0, 0);
    GUITHREADINFO state = {.cbSize = sizeof(state)};
    BOOL captured = FALSE;
    for (int attempt = 0; down && attempt < 10 && GetForegroundWindow() == root; ++attempt)
    {
        Sleep(75);
        if (GetGUIThreadInfo(gui_thread, &state) && GetAsyncKeyState(VK_MBUTTON) < 0 &&
            (state.hwndCapture == viewport || IsChild(viewport, state.hwndCapture)))
        {
            captured = TRUE;
            break;
        }
    }
    LONG x = 0, y = 0;
    unsigned long sent = 0;
    while (captured && sent < count && GetForegroundWindow() == root)
    {
        const double angle = 3.141592653589793 * (sent + 1) / count;
        LONG next_x = (LONG)(145 * sin(8 * angle));
        LONG next_y = (LONG)(90 * sin(12 * angle));
        double before = now_ms();
        if (!send_mouse(MOUSEEVENTF_MOVE, next_x - x, next_y - y)) break;
        durations[sent++] = now_ms() - before;
        x = next_x;
        y = next_y;
        Sleep(pace_ms);
    }
    BOOL released = down && send_mouse(MOUSEEVENTF_MIDDLEUP, 0, 0);
    double finish = now_ms();
    if (moved && GetForegroundWindow() == root) SetCursorPos(saved.x, saved.y);
    if (sent == count && released &&
        (!camera_scale(app, &scale_after) || fabs(scale_after - scale_before) > scale_before * 1e-5))
    {
        fputs("The viewport scale changed during the drag.\n", stderr);
        free(durations);
        return 7;
    }
    if (sent == count && released)
    {
        printf("phase %.6f %.6f\n", start, finish);
        for (unsigned long i = 0; i < count; ++i) printf("%.6f\n", durations[i]);
    }
    else
    {
        printf("target capture=%d, sent=%lu, released=%d\n", captured, sent, released);
    }
    free(durations);
    return sent == count && released ? 0 : 6;
}

int wmain(int argc, WCHAR **argv)
{
    CLSID clsid;
    IUnknown *running = NULL;
    IDispatch *app = NULL;
    int result = 1;
    if (argc < 2) return 2;
    if (!wcscmp(argv[1], L"mouse-view") || !wcscmp(argv[1], L"frame-size")) SetProcessDPIAware();
    if (FAILED(CoInitializeEx(NULL, COINIT_APARTMENTTHREADED))) return 2;
    if (SUCCEEDED(CLSIDFromProgID(L"SldWorks.Application", &clsid)) &&
        SUCCEEDED(GetActiveObject(&clsid, NULL, &running)) &&
        SUCCEEDED(IUnknown_QueryInterface(running, &IID_IDispatch, (void **)&app)))
    {
        if (argc == 3 && !wcscmp(argv[1], L"ready"))
            result = ready(app, argv[2]) ? 0 : 3;
        else if (argc == 4 && !wcscmp(argv[1], L"measure"))
            result = measure(app, argv[2], argv[3]);
        else if ((argc == 3 || argc == 6) && !wcscmp(argv[1], L"verify-model"))
            result = verify_model(app, argv[2], argc == 6 ? &argv[3] : NULL);
        else if (argc == 4 && !wcscmp(argv[1], L"inspect-view"))
            result = inspect_view(app, argv[2], argv[3]);
        else if (argc == 3 && !wcscmp(argv[1], L"plain-view"))
            result = plain_view(app, argv[2]);
        else if (argc == 2 && !wcscmp(argv[1], L"orbit"))
            result = orbit(app);
        else if (argc == 3 && !wcscmp(argv[1], L"scene"))
            result = scene(app, argv[2]);
        else if (argc == 3 && !wcscmp(argv[1], L"rebuild-scene"))
            result = rebuild_scene(app, argv[2]);
        else if (argc == 3 && !wcscmp(argv[1], L"shade-scene"))
            result = shade_scene(app, argv[2]);
        else if (argc == 3 && !wcscmp(argv[1], L"detail-state"))
            result = detail_state(app, argv[2]);
        else if (argc == 3 && !wcscmp(argv[1], L"prepare-detail"))
            result = prepare_detail(app, argv[2]);
        else if ((argc == 3 || argc == 5) && !wcscmp(argv[1], L"frame-size"))
            result = frame_size(app, argv[2], argc == 5 ? argv[3] : NULL, argc == 5 ? argv[4] : NULL);
        else if (argc == 5 && !wcscmp(argv[1], L"timed-view"))
            result = timed_view(app, argv[2], argv[3], argv[4], FALSE, FALSE);
        else if (argc == 5 && !wcscmp(argv[1], L"timed-ipc"))
            result = timed_view(app, argv[2], argv[3], argv[4], TRUE, FALSE);
        else if (argc == 5 && !wcscmp(argv[1], L"cached-view"))
            result = timed_view(app, argv[2], argv[3], argv[4], FALSE, TRUE);
        else if (argc == 5 && !wcscmp(argv[1], L"cached-ipc"))
            result = timed_view(app, argv[2], argv[3], argv[4], TRUE, TRUE);
        else if (argc == 5 && !wcscmp(argv[1], L"mouse-view"))
            result = mouse_view(app, argv[2], argv[3], argv[4]);
        else if (argc == 3 && !wcscmp(argv[1], L"can-exit"))
            result = fixtures_are_saved(app, argv[2]) ? 0 : 6;
        else if (argc == 3 && !wcscmp(argv[1], L"exit") && fixtures_are_saved(app, argv[2]))
        {
            VARIANT ignored;
            HRESULT hr = invoke(app, L"ExitApp", DISPATCH_METHOD, NULL, 0, &ignored);
            VariantClear(&ignored);
            result = FAILED(hr) ? 5 : 0;
        }
        IDispatch_Release(app);
    }
    if (running) IUnknown_Release(running);
    CoUninitialize();
    return result;
}
