#pragma once

#include <stdint.h>

/* Win32 LONG, DWORD and BOOL are 32-bit. Guest handles and addresses are 64-bit. */

uint16_t subsys_GUI_RegisterClassExW(uint64_t class_ptr);
uint64_t subsys_GUI_CreateWindowExW(uint32_t ex_style, uint64_t class_name,
                                           uint64_t window_name, uint32_t style,
                                           int32_t x, int32_t y, int32_t width,
                                           int32_t height, uint64_t parent,
                                           uint64_t menu, uint64_t instance,
                                           uint64_t param);
int32_t subsys_GUI_ShowWindow(uint64_t hwnd, int32_t command);
int32_t subsys_GUI_GetMessageW(uint64_t msg_ptr, uint64_t hwnd,
                                      uint32_t filter_min, uint32_t filter_max);
int32_t subsys_GUI_TranslateMessage(uint64_t msg_ptr);
int64_t subsys_GUI_DispatchMessageW(uint64_t msg_ptr);
int64_t subsys_GUI_DefWindowProcW(uint64_t hwnd, uint32_t message,
                                        uint64_t wparam, int64_t lparam);
int32_t subsys_GUI_DestroyWindow(uint64_t hwnd);
void subsys_GUI_PostQuitMessage(int32_t exit_code);
uint64_t subsys_GUI_SetTimer(uint64_t hwnd, uint64_t id, uint32_t elapsed,
                                    uint64_t proc);
uint64_t subsys_GUI_BeginPaint(uint64_t hwnd, uint64_t paint_ptr);
int32_t subsys_GUI_EndPaint(uint64_t hwnd, uint64_t paint_ptr);
int32_t subsys_GUI_FillRect(uint64_t hdc, uint64_t rect_ptr, uint64_t brush);
int32_t subsys_GUI_GetClientRect(uint64_t hwnd, uint64_t rect_ptr);
uint64_t subsys_GUI_CreateSolidBrush(uint32_t color);
int32_t subsys_GUI_DeleteObject(uint64_t object);

/* Implemented in console_runtime.c: invokes a lifted WndProc with a fresh
 * x86 register frame, preserving the caller's CPU context. */
uint64_t guest_call_guest_proc(uint64_t target, uint64_t first,
                               uint64_t second, uint64_t third,
                               uint64_t fourth);
