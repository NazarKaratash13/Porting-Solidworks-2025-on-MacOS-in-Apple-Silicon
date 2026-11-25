#pragma once

#include <stddef.h>
#include <stdint.h>

/* Layout of the Windows x64 MSG structure used by the standalone GUI shims.
   WPARAM/LPARAM are 8-byte aligned, but POINT is 4-byte aligned: there is no
   padding between time and pt. The struct is 48 bytes, not 56. */

typedef struct {
    int32_t x, y;
} WIN32_POINT;

typedef struct {
    int32_t left, top, right, bottom;
} WIN32_RECT;

typedef struct {
    uint64_t hwnd;          /* 0  */
    uint32_t message;       /* 8  */
    uint32_t padding;
    uint64_t wParam;        /* 16 */
    int64_t lParam;         /* 24 */
    uint32_t time;          /* 32 */
    WIN32_POINT pt;         /* 36 */
    uint32_t lPrivate;      /* 44 */
} WIN32_MSG;

_Static_assert(sizeof(WIN32_MSG) == 48, "Windows x64 MSG must be 48 bytes");
_Static_assert(offsetof(WIN32_MSG, hwnd) == 0, "MSG.hwnd");
_Static_assert(offsetof(WIN32_MSG, message) == 8, "MSG.message");
_Static_assert(offsetof(WIN32_MSG, wParam) == 16, "MSG.wParam");
_Static_assert(offsetof(WIN32_MSG, lParam) == 24, "MSG.lParam");
_Static_assert(offsetof(WIN32_MSG, time) == 32, "MSG.time");
_Static_assert(offsetof(WIN32_MSG, pt.x) == 36, "MSG.pt.x");
_Static_assert(offsetof(WIN32_MSG, pt.y) == 40, "MSG.pt.y");
_Static_assert(offsetof(WIN32_MSG, lPrivate) == 44, "MSG.lPrivate");

typedef struct {
    uint64_t param, instance, menu, parent;
    int32_t height, width, y, x, style;
    uint32_t padding0;
    uint64_t title, class_name;
    uint32_t ex_style, padding1;
} WIN32_CREATESTRUCT;

typedef struct {
    uint64_t hdc;
    int32_t erase;
    WIN32_RECT dirty;
    int32_t restore, inc_update;
    uint8_t reserved[32];
    uint32_t padding;
} WIN32_PAINTSTRUCT;

_Static_assert(sizeof(WIN32_CREATESTRUCT) == 80, "Windows x64 CREATESTRUCTW");
_Static_assert(offsetof(WIN32_CREATESTRUCT, width) == 36, "CREATESTRUCTW.cx");
_Static_assert(offsetof(WIN32_CREATESTRUCT, title) == 56, "CREATESTRUCTW.lpszName");
_Static_assert(sizeof(WIN32_PAINTSTRUCT) == 72, "Windows x64 PAINTSTRUCT");
_Static_assert(offsetof(WIN32_PAINTSTRUCT, dirty) == 12, "PAINTSTRUCT.rcPaint");
