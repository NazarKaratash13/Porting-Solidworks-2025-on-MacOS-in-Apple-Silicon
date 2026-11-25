#define COBJMACROS
#include <windows.h>
#include <oleauto.h>
#include <limits.h>
#include <stdio.h>
#include <wchar.h>

/* The V3 win32u patch translates this window message to the original MFC command. */
#define SW_ORIGINAL_SAVE_AS (WM_APP + 0x571)

static const GUID model_extension_iid = {0x99f4d4af,0xf268,0x4ee1,{0x8c,0x55,0x04,0x1f,0x7b,0xec,0xf8,0x79}};

static HRESULT invoke(IDispatch *object, WCHAR *name, WORD flags,
                      VARIANT *args, UINT count, VARIANT *result)
{
    DISPID id;
    DISPID named = DISPID_PROPERTYPUT;
    DISPPARAMS params = {args, NULL, count, 0};
    HRESULT hr = IDispatch_GetIDsOfNames(object, &IID_NULL, &name, 1, LOCALE_USER_DEFAULT, &id);
    VariantInit(result);
    if (FAILED(hr)) return hr;
    if (flags == DISPATCH_PROPERTYPUT)
    {
        params.rgdispidNamedArgs = &named;
        params.cNamedArgs = 1;
    }
    return IDispatch_Invoke(object, id, &IID_NULL, LOCALE_USER_DEFAULT, flags,
                            &params, result, NULL, NULL);
}

static VARIANT integer(LONG value)
{
    VARIANT arg;
    VariantInit(&arg);
    V_VT(&arg) = VT_I4;
    V_I4(&arg) = value;
    return arg;
}

static VARIANT string(const WCHAR *value)
{
    VARIANT arg;
    VariantInit(&arg);
    V_VT(&arg) = VT_BSTR;
    V_BSTR(&arg) = SysAllocString(value);
    return arg;
}

static VARIANT output_integer(LONG *value)
{
    VARIANT arg;
    VariantInit(&arg);
    V_VT(&arg) = VT_I4 | VT_BYREF;
    V_I4REF(&arg) = value;
    return arg;
}

static LONG document_kind(const WCHAR *path)
{
    const WCHAR *ext = wcsrchr(path, L'.');
    if (!ext) return 0;
    if (!_wcsicmp(ext, L".sldprt")) return 1;
    if (!_wcsicmp(ext, L".sldasm")) return 2;
    if (!_wcsicmp(ext, L".slddrw")) return 3;
    return 0;
}

static BOOL can_save_as(const WCHAR *path, LONG kind, LONG *options)
{
    const WCHAR *ext = wcsrchr(path, L'.');
    if (!ext) return FALSE;
    if (document_kind(path) == kind) return TRUE;

    /* Export uses the current SOLIDWORKS exporter settings. */
    *options = 1;
    if (kind == 3) return !_wcsicmp(ext, L".pdf") || !_wcsicmp(ext, L".dxf") || !_wcsicmp(ext, L".dwg");
    return (kind == 1 || kind == 2) &&
           (!_wcsicmp(ext, L".step") || !_wcsicmp(ext, L".igs") ||
            !_wcsicmp(ext, L".x_t") || !_wcsicmp(ext, L".stl"));
}

static int save_document(IDispatch *doc, const WCHAR *path, LONG options)
{
    VARIANT extension, result, none;
    LONG errors = 0, warnings = 0;
    HRESULT hr = invoke(doc, L"Extension", DISPATCH_PROPERTYGET, NULL, 0, &extension);
    int status = 5;

    if (FAILED(hr) || V_VT(&extension) != VT_DISPATCH || !V_DISPATCH(&extension))
    {
        printf("IModelDocExtension: 0x%08lx\n", (unsigned long)hr);
        VariantClear(&extension);
        return status;
    }

    VariantInit(&none);
    V_VT(&none) = VT_DISPATCH;
    V_DISPATCH(&none) = NULL;
    VARIANT args[] = {output_integer(&warnings), output_integer(&errors), none, none,
                      integer(options), integer(0), string(path)};
    hr = invoke(V_DISPATCH(&extension), L"SaveAs3", DISPATCH_METHOD, args, 7, &result);
    DWORD attrs = GetFileAttributesW(path);
    if (SUCCEEDED(hr) && V_VT(&result) == VT_BOOL && V_BOOL(&result) && !errors &&
        attrs != INVALID_FILE_ATTRIBUTES && !(attrs & FILE_ATTRIBUTE_DIRECTORY)) status = 0;
    if (status || warnings)
        printf("SaveAs3 0x%08lx, errors=0x%lx, warnings=0x%lx\n", (unsigned long)hr, errors, warnings);
    VariantClear(&result);
    VariantClear(&args[6]);
    VariantClear(&extension);
    return status;
}

static VARIANT bool_argument(BOOL value)
{
    VARIANT arg;
    VariantInit(&arg);
    V_VT(&arg) = VT_BOOL;
    V_BOOL(&arg) = value ? VARIANT_TRUE : VARIANT_FALSE;
    return arg;
}

static HRESULT set_pack_option(IDispatch *pack, WCHAR *name, BOOL enabled)
{
    VARIANT value = bool_argument(enabled), result;
    HRESULT hr = invoke(pack, name, DISPATCH_PROPERTYPUT, &value, 1, &result);
    VariantClear(&result);
    return hr;
}

static BOOL pack_status_ok(const VARIANT *status)
{
    SAFEARRAY *array = V_ARRAY(status);
    LONG first, last, code;

    if (V_VT(status) != (VT_ARRAY | VT_I4) || !array || SafeArrayGetDim(array) != 1 ||
        FAILED(SafeArrayGetLBound(array, 1, &first)) ||
        FAILED(SafeArrayGetUBound(array, 1, &last)) || first > last) return FALSE;
    for (LONG index = first; index <= last; ++index)
    {
        if (FAILED(SafeArrayGetElement(array, &index, &code))) return FALSE;
        if (code)
        {
            printf("Pack and Go, файл %ld: статус %ld\n", index + 1 - first, code);
            return FALSE;
        }
    }
    return TRUE;
}

static BOOL document_is_saved(IDispatch *doc)
{
    VARIANT dirty;
    HRESULT hr = invoke(doc, L"GetSaveFlag", DISPATCH_METHOD, NULL, 0, &dirty);
    BOOL clean = SUCCEEDED(hr) && V_VT(&dirty) == VT_BOOL && !V_BOOL(&dirty);
    VariantClear(&dirty);
    return clean;
}

static int pack_document(IDispatch *doc, const WCHAR *path, const WCHAR *options)
{
    WCHAR *end;
    LONG mask = wcstol(options, &end, 10);
    VARIANT extended, result, location, statuses;
    IUnknown *typed = NULL;
    IDispatch *pack = NULL;
    HRESULT hr;
    int status = 5;

    /* Dual-interface slots from the installed x64 IModelDocExtension type library. */
    typedef HRESULT (STDMETHODCALLTYPE *get_pack_and_go)(IUnknown *, IDispatch **);
    typedef HRESULT (STDMETHODCALLTYPE *save_pack_and_go)(IUnknown *, IDispatch *, VARIANT *);

    if (!*path || end == options || *end || mask < 0 || mask > 15)
        return 2;
    if (GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES)
    {
        puts("Укажите новое имя папки, чтобы сохранить существующие файлы.");
        return 5;
    }
    if (!document_is_saved(doc))
    {
        puts("Сохраните открытый документ перед упаковкой.");
        return 5;
    }

    hr = invoke(doc, L"Extension", DISPATCH_PROPERTYGET, NULL, 0, &extended);
    if (FAILED(hr) || V_VT(&extended) != VT_DISPATCH || !V_DISPATCH(&extended) ||
        FAILED(hr = IDispatch_QueryInterface(V_DISPATCH(&extended), &model_extension_iid, (void **)&typed)))
        goto done;

    get_pack_and_go get_pack = ((get_pack_and_go *)typed->lpVtbl)[219];
    save_pack_and_go save_pack = ((save_pack_and_go *)typed->lpVtbl)[220];
    hr = get_pack(typed, &pack);
    if (FAILED(hr) || !pack) goto done;
    if (FAILED(hr = set_pack_option(pack, L"IncludeDrawings", (mask & 1) != 0)) ||
        FAILED(hr = set_pack_option(pack, L"IncludeToolboxComponents", (mask & 2) != 0)) ||
        FAILED(hr = set_pack_option(pack, L"IncludeSimulationResults", (mask & 4) != 0)) ||
        FAILED(hr = set_pack_option(pack, L"FlattenToSingleFolder", (mask & 8) != 0))) goto done;

    /* Use a fresh folder and keep Unicode filenames as stored by SOLIDWORKS.
     * The program's ZIP writer uses a legacy encoding for path names. */
    if (!CreateDirectoryW(path, NULL))
    {
        hr = HRESULT_FROM_WIN32(GetLastError());
        goto done;
    }
    location = string(path);
    VARIANT args[] = {location, bool_argument(TRUE)};
    hr = invoke(pack, L"SetSaveToName", DISPATCH_METHOD, args, 2, &result);
    BOOL ready = SUCCEEDED(hr) && V_VT(&result) == VT_BOOL && V_BOOL(&result);
    VariantClear(&location);
    VariantClear(&result);
    if (!ready) goto done;

    VariantInit(&statuses);
    hr = save_pack(typed, pack, &statuses);
    if (SUCCEEDED(hr) && pack_status_ok(&statuses) &&
        GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES) status = 0;
    VariantClear(&statuses);

done:
    if (status) printf("Pack and Go: 0x%08lx\n", (unsigned long)hr);
    if (pack) IDispatch_Release(pack);
    if (typed) IUnknown_Release(typed);
    VariantClear(&extended);
    return status;
}

static void utf8_line(const WCHAR *value)
{
    int size = WideCharToMultiByte(CP_UTF8, 0, value, -1, NULL, 0, NULL, NULL);
    char *buffer = size > 0 ? malloc(size) : NULL;
    if (buffer && WideCharToMultiByte(CP_UTF8, 0, value, -1, buffer, size, NULL, NULL)) puts(buffer);
    free(buffer);
}

static int open_document(IDispatch *app, const WCHAR *path)
{
    LONG errors = 0, warnings = 0, kind = document_kind(path);
    VARIANT result, activated;
    VARIANT args[] = {output_integer(&warnings), output_integer(&errors), string(L""),
                      integer(1), integer(kind), string(path)};
    HRESULT hr = E_INVALIDARG;
    BOOL opened = FALSE;
    VariantInit(&result);
    if (kind && GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES)
    {
        hr = invoke(app, L"OpenDoc6", DISPATCH_METHOD, args, 6, &result);
        opened = SUCCEEDED(hr) && V_VT(&result) == VT_DISPATCH && V_DISPATCH(&result);
        if (opened)
        {
            VARIANT title;
            if (SUCCEEDED(invoke(V_DISPATCH(&result), L"GetTitle", DISPATCH_METHOD, NULL, 0, &title)) &&
                V_VT(&title) == VT_BSTR)
            {
                LONG activation_error = 0;
                VARIANT activate_args[] = {output_integer(&activation_error), integer(0), integer(0), title};
                V_VT(&activate_args[2]) = VT_BOOL;
                V_BOOL(&activate_args[2]) = VARIANT_FALSE;
                invoke(app, L"ActivateDoc3", DISPATCH_METHOD, activate_args, 4, &activated);
                VariantClear(&activated);
            }
            VariantClear(&title);
        }
    }
    if (!opened) printf("OpenDoc6 0x%08lx, errors=%ld, warnings=%ld, type=%u\n",
                        (unsigned long)hr, errors, warnings, V_VT(&result));
    VariantClear(&result);
    VariantClear(&args[2]);
    VariantClear(&args[5]);
    return opened ? 0 : 4;
}

static int active_document(IDispatch *app, int argc, WCHAR **argv)
{
    VARIANT active, title, path, kind;
    IDispatch *document;
    int status = 5;

    if (FAILED(invoke(app, L"ActiveDoc", DISPATCH_PROPERTYGET | DISPATCH_METHOD, NULL, 0, &active)) ||
        V_VT(&active) != VT_DISPATCH || !(document = V_DISPATCH(&active)))
    {
        VariantClear(&active);
        puts("В SOLIDWORKS нет активного документа.");
        return status;
    }

    invoke(document, L"GetTitle", DISPATCH_METHOD, NULL, 0, &title);
    invoke(document, L"GetPathName", DISPATCH_METHOD, NULL, 0, &path);
    invoke(document, L"GetType", DISPATCH_METHOD, NULL, 0, &kind);
    if (V_VT(&title) == VT_BSTR && V_BSTR(&title) && V_VT(&path) == VT_BSTR && V_VT(&kind) == VT_I4)
    {
        const WCHAR *current_path = V_BSTR(&path) ? V_BSTR(&path) : L"";
        if (argc == 2 && (!wcscmp(argv[1], L"active") || !wcscmp(argv[1], L"pack-active")))
        {
            if (!wcscmp(argv[1], L"pack-active") && (!*current_path || !document_is_saved(document)))
            {
                puts("Сохраните открытый документ перед упаковкой.");
                goto done;
            }
            printf("%ld\n", V_I4(&kind));
            utf8_line(V_BSTR(&title));
            utf8_line(current_path);
            status = 0;
        }
        else if ((argc == 5 || argc == 6) && !wcscmp(argv[1], L"save") &&
                 !wcscmp(V_BSTR(&title), argv[3]) && !wcscmp(current_path, argv[4]))
        {
            LONG options = 1;
            if (argc == 6 && !wcscmp(argv[5], L"2")) options |= 2;
            else if (argc == 6 && !wcscmp(argv[5], L"512")) options |= 512;
            else if (argc == 6 && wcscmp(argv[5], L"0")) goto done;
            if (can_save_as(argv[2], V_I4(&kind), &options))
                status = save_document(document, argv[2], options);
            else puts("Этот формат недоступен для активного документа.");
        }
        else if (argc == 6 && !wcscmp(argv[1], L"pack") && *current_path &&
                 !wcscmp(V_BSTR(&title), argv[3]) && !wcscmp(current_path, argv[4]))
            status = pack_document(document, argv[2], argv[5]);
        else puts("Активный документ или его тип изменились. Вызовите сохранение снова.");
    }
    else puts("Не удалось определить активный документ SOLIDWORKS.");

done:
    VariantClear(&kind);
    VariantClear(&path);
    VariantClear(&title);
    VariantClear(&active);
    return status;
}

static int run_command(IDispatch *app, const WCHAR *command)
{
    WCHAR *end;
    LONG id = wcstol(command, &end, 10);
    VARIANT result;
    HRESULT hr;
    int status;

    if (end == command || *end || id < 0 || id == LONG_MAX) return 2;
    VARIANT args[] = {string(L""), integer(id)};
    hr = invoke(app, L"RunCommand", DISPATCH_METHOD, args, 2, &result);
    status = SUCCEEDED(hr) && V_VT(&result) == VT_BOOL && V_BOOL(&result) ? 0 : 5;
    if (status) printf("RunCommand(%ld): 0x%08lx\n", id, (unsigned long)hr);
    VariantClear(&result);
    VariantClear(&args[0]);
    return status;
}

static int show_original_save_dialog(IDispatch *app)
{
    VARIANT frame, value;
    HWND hwnd = NULL;
    HRESULT hr = invoke(app, L"Frame", DISPATCH_PROPERTYGET | DISPATCH_METHOD, NULL, 0, &frame);

    if (SUCCEEDED(hr) && V_VT(&frame) == VT_DISPATCH && V_DISPATCH(&frame))
    {
        /* HWND values in this Wine prefix are 32-bit user handles. */
        hr = invoke(V_DISPATCH(&frame), L"GetHWnd", DISPATCH_METHOD, NULL, 0, &value);
        if (SUCCEEDED(hr) && V_VT(&value) == VT_I4) hwnd = (HWND)(ULONG_PTR)(DWORD)V_I4(&value);
        VariantClear(&value);
    }
    VariantClear(&frame);
    if (IsWindow(hwnd) && IsWindowEnabled(hwnd) && PostMessageW(hwnd, SW_ORIGINAL_SAVE_AS, 0, 0)) return 0;
    puts("Окно SOLIDWORKS занято или недоступно.");
    return 5;
}

int wmain(int argc, WCHAR **argv)
{
    CLSID clsid;
    IUnknown *unknown = NULL;
    IDispatch *app = NULL;
    HRESULT hr;
    BOOL opening = argc > 2 && !wcscmp(argv[1], L"open");
    int status = 3;

    if (argc < 2 || FAILED(CoInitializeEx(NULL, COINIT_APARTMENTTHREADED))) return 2;
    hr = CLSIDFromProgID(L"SldWorks.Application", &clsid);
    if (SUCCEEDED(hr))
    {
        ULONGLONG deadline = GetTickCount64() + (opening ? 90000 : 3000);
        while (FAILED(hr = GetActiveObject(&clsid, NULL, &unknown)) && GetTickCount64() < deadline)
            Sleep(300);
    }
    if (SUCCEEDED(hr)) hr = IUnknown_QueryInterface(unknown, &IID_IDispatch, (void **)&app);
    if (unknown) IUnknown_Release(unknown);
    if (SUCCEEDED(hr))
    {
        if (opening)
        {
            status = 0;
            for (int i = 2; i < argc; ++i)
                if (open_document(app, argv[i])) status = 4;
        }
        else if (argc == 3 && !wcscmp(argv[1], L"command"))
            status = run_command(app, argv[2]);
        else if (argc == 2 && !wcscmp(argv[1], L"original-save-as"))
            status = show_original_save_dialog(app);
        else status = active_document(app, argc, argv);
        IDispatch_Release(app);
    }
    else printf("Подключение к SOLIDWORKS: 0x%08lx\n", (unsigned long)hr);
    CoUninitialize();
    return status;
}
