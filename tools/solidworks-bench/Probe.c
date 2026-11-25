/* Attach to a running SOLIDWORKS session to measure test-document operations. */
#define wmain file_bridge_main
#include "../solidworks-v3-file-bridge.c"
#undef wmain

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

int wmain(int argc, WCHAR **argv)
{
    CLSID clsid;
    IUnknown *running = NULL;
    IDispatch *app = NULL;
    int result = 1;
    if (argc < 2 || FAILED(CoInitializeEx(NULL, COINIT_APARTMENTTHREADED))) return 2;
    if (SUCCEEDED(CLSIDFromProgID(L"SldWorks.Application", &clsid)) &&
        SUCCEEDED(GetActiveObject(&clsid, NULL, &running)) &&
        SUCCEEDED(IUnknown_QueryInterface(running, &IID_IDispatch, (void **)&app)))
    {
        if (argc == 3 && !wcscmp(argv[1], L"ready"))
            result = ready(app, argv[2]) ? 0 : 3;
        else if (argc == 4 && !wcscmp(argv[1], L"measure"))
            result = measure(app, argv[2], argv[3]);
        else if (argc == 2 && !wcscmp(argv[1], L"orbit"))
            result = orbit(app);
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
