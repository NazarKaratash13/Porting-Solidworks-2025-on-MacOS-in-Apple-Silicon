#pragma once

static HWND com_window_handle(const VARIANT *value)
{
    if (V_VT(value) == VT_I8) return (HWND)(UINT_PTR)V_I8(value);
    if (V_VT(value) == VT_UI8) return (HWND)(UINT_PTR)V_UI8(value);
    if (V_VT(value) == VT_I4) return (HWND)(UINT_PTR)(DWORD)V_I4(value);
    if (V_VT(value) == VT_UI4) return (HWND)(UINT_PTR)V_UI4(value);
    return NULL;
}

static HWND com_frame_window(IDispatch *app)
{
    VARIANT frame, value;
    HWND window = NULL;
    invoke(app, L"Frame", DISPATCH_PROPERTYGET | DISPATCH_METHOD, NULL, 0, &frame);
    if (V_VT(&frame) == VT_DISPATCH && V_DISPATCH(&frame))
    {
        invoke(V_DISPATCH(&frame), L"GetHWndx64", DISPATCH_METHOD, NULL, 0, &value);
        window = com_window_handle(&value);
        VariantClear(&value);
        if (!IsWindow(window))
        {
            invoke(V_DISPATCH(&frame), L"GetHWnd", DISPATCH_METHOD, NULL, 0, &value);
            window = com_window_handle(&value);
            VariantClear(&value);
        }
    }
    VariantClear(&frame);
    return IsWindow(window) ? window : NULL;
}
