#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "standalone_gui.h"
#include "win32_gui_layout.h"

uint64_t guest_load(uint64_t address, uint32_t width);
void guest_store(uint64_t address, uint64_t value, uint32_t width);
uint64_t guest_malloc(uint64_t size);
uint64_t guest_free(uint64_t address);
void guest_set_last_error(uint32_t error);

enum {
    WM_CREATE = 0x0001, WM_DESTROY = 0x0002, WM_PAINT = 0x000f,
    WM_CLOSE = 0x0010, WM_QUIT = 0x0012, WM_NCCREATE = 0x0081,
    WM_NCDESTROY = 0x0082, WM_TIMER = 0x0113,
};
enum {
    ERROR_NOT_ENOUGH_MEMORY = 8, ERROR_INVALID_PARAMETER = 87,
    ERROR_CALL_NOT_IMPLEMENTED = 120, ERROR_INVALID_WINDOW_HANDLE = 1400,
    ERROR_CANNOT_FIND_WND_CLASS = 1407, ERROR_CLASS_ALREADY_EXISTS = 1410,
    ERROR_INVALID_THREAD_ID = 1444,
};
enum { HDC_PAINT = 0x7fff4001, GUI_WAKE_EVENT = 0x1cf0 };
enum { WS_OVERLAPPEDWINDOW = 0x00cf0000, WS_VISIBLE = 0x10000000 };

@interface StandaloneClass : NSObject
@property(nonatomic) uint16_t atom;
@property(nonatomic) uint64_t wndproc;
@end
@implementation StandaloneClass
@end

@interface StandaloneMessage : NSObject
@property(nonatomic) WIN32_MSG value;
@end
@implementation StandaloneMessage
@end

@interface StandaloneWindow : NSObject <NSWindowDelegate>
@property(nonatomic) uint64_t hwnd;
@property(nonatomic) uint64_t wndproc;
@property(nonatomic) BOOL destroying;
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) NSMutableDictionary<NSNumber *, NSTimer *> *timers;
@end

@interface StandaloneView : NSView
@property(nonatomic) uint64_t hwnd;
@end

struct paint_frame {
    uint64_t hwnd;
    uint64_t paint_ptr;
    CGContextRef context;
    NSRect dirty;
};

static NSMutableDictionary<NSNumber *, StandaloneWindow *> *windows;
static NSMutableDictionary<NSString *, StandaloneClass *> *classes;
static NSMutableDictionary<NSNumber *, StandaloneClass *> *class_atoms;
static NSMutableDictionary<NSNumber *, NSColor *> *brushes;
static NSMutableArray<StandaloneMessage *> *messages;
static struct paint_frame *active_paint;
static uint64_t next_hwnd = UINT64_C(0x100000000);
static uint64_t next_brush = 0x7fff5000;
static uint32_t next_atom = 0xc001;

static int32_t fail(uint32_t error) {
    guest_set_last_error(error);
    return 0;
}

// The AppKit window and its guest message queue are owned by the main thread.
static bool gui_thread(void) {
    if (NSThread.isMainThread) return true;
    fail(ERROR_INVALID_THREAD_ID);
    return false;
}

static void ensure_state(void) {
    if (windows) return;
    windows = [NSMutableDictionary new];
    classes = [NSMutableDictionary new];
    class_atoms = [NSMutableDictionary new];
    brushes = [NSMutableDictionary new];
    messages = [NSMutableArray new];
}

static void ensure_app(void) {
    ensure_state();
    static bool launched;
    if (launched) return;
    launched = true;
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    [NSApp finishLaunching];
}

static StandaloneWindow *lookup_window(uint64_t hwnd) {
    if (!gui_thread()) return nil;
    StandaloneWindow *record = windows[@(hwnd)];
    if (!record) fail(ERROR_INVALID_WINDOW_HANDLE);
    return record;
}

static NSString *guest_utf16(uint64_t address) {
    if (!address) return @"";
    unichar units[1024];
    for (size_t i = 0; i < sizeof(units) / sizeof(*units); ++i) {
        units[i] = (unichar)guest_load(address + i * 2, 2);
        if (!units[i]) return [NSString stringWithCharacters:units length:i];
    }
    fail(ERROR_INVALID_PARAMETER);
    return nil;
}

static void store_struct(uint64_t address, const void *data, size_t size) {
    for (size_t offset = 0; offset < size; offset += 8) {
        uint64_t word = 0;
        size_t width = size - offset < 8 ? size - offset : 8;
        memcpy(&word, (const unsigned char *)data + offset, width);
        guest_store(address + offset, word, (uint32_t)width);
    }
}

static WIN32_RECT win_rect(NSRect rect) {
    return (WIN32_RECT){ (int32_t)NSMinX(rect), (int32_t)NSMinY(rect),
                        (int32_t)NSMaxX(rect), (int32_t)NSMaxY(rect) };
}

static void post_message(uint64_t hwnd, uint32_t code, uint64_t wparam) {
    for (StandaloneMessage *queued in messages) {
        WIN32_MSG pending = queued.value;
        if (pending.hwnd == hwnd && pending.message == code) {
            if (code == WM_TIMER && pending.wParam == wparam) return;
            if (code == WM_QUIT) {
                pending.wParam = wparam;
                queued.value = pending;
                return;
            }
        }
    }
    StandaloneMessage *item = [StandaloneMessage new];
    NSPoint point = NSEvent.mouseLocation;
    item.value = (WIN32_MSG){
        .hwnd = hwnd, .message = code, .wParam = wparam,
        .time = (uint32_t)(uint64_t)(NSProcessInfo.processInfo.systemUptime * 1000),
        .pt = { (int32_t)point.x, (int32_t)(NSMaxY(NSScreen.screens.firstObject.frame) - point.y) },
    };
    [messages addObject:item];
    // A timer fires inside AppKit's wait. Post an event to return from that wait.
    [NSApp postEvent:[NSEvent otherEventWithType:NSEventTypeApplicationDefined
                                        location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:0
                                          context:nil subtype:GUI_WAKE_EVENT data1:0 data2:0]
             atStart:NO];
}

@implementation StandaloneWindow
- (BOOL)windowShouldClose:(NSWindow *)sender {
    (void)sender;
    post_message(self.hwnd, WM_CLOSE, 0);
    return NO;
}
@end

@implementation StandaloneView
- (BOOL)isFlipped { return YES; }
- (void)drawRect:(NSRect)dirty {
    [super drawRect:dirty];
    StandaloneWindow *record = windows[@(self.hwnd)];
    CGContextRef context = NSGraphicsContext.currentContext.CGContext;
    if (!record || record.destroying || !context) return;
    struct paint_frame frame = { .hwnd = self.hwnd, .context = context, .dirty = dirty };
    struct paint_frame *previous = active_paint;
    active_paint = &frame;
    guest_call_guest_proc(record.wndproc, self.hwnd, WM_PAINT, 0, 0);
    active_paint = previous;
}
@end

static void destroy_window(StandaloneWindow *record, bool send_destroy) {
    uint64_t hwnd = record.hwnd;
    record.destroying = YES;
    for (NSTimer *timer in record.timers.allValues) [timer invalidate];
    if (send_destroy) guest_call_guest_proc(record.wndproc, hwnd, WM_DESTROY, 0, 0);
    guest_call_guest_proc(record.wndproc, hwnd, WM_NCDESTROY, 0, 0);
    for (NSUInteger i = messages.count; i > 0; --i)
        if (messages[i - 1].value.hwnd == hwnd) [messages removeObjectAtIndex:i - 1];
    record.window.delegate = nil;
    [record.window close];
    [windows removeObjectForKey:@(hwnd)];
}

uint16_t subsys_GUI_RegisterClassExW(uint64_t class_ptr) {
    @autoreleasepool {
        if (!gui_thread()) return 0;
        if (!class_ptr || guest_load(class_ptr, 4) != 80) return fail(ERROR_INVALID_PARAMETER);
        ensure_state();
        uint64_t wndproc = guest_load(class_ptr + 8, 8);
        NSString *name = guest_utf16(guest_load(class_ptr + 64, 8));
        if (!name.length || !wndproc) return fail(ERROR_INVALID_PARAMETER);
        if (classes[name.lowercaseString]) return fail(ERROR_CLASS_ALREADY_EXISTS);
        if (next_atom > UINT16_MAX) return fail(ERROR_NOT_ENOUGH_MEMORY);
        StandaloneClass *entry = [StandaloneClass new];
        entry.atom = (uint16_t)next_atom++;
        entry.wndproc = wndproc;
        classes[name.lowercaseString] = entry;
        class_atoms[@(entry.atom)] = entry;
        return entry.atom;
    }
}

uint64_t subsys_GUI_CreateWindowExW(uint32_t ex_style, uint64_t class_name,
                                   uint64_t window_name, uint32_t style,
                                   int32_t x, int32_t y, int32_t width, int32_t height,
                                   uint64_t parent, uint64_t menu, uint64_t instance,
                                   uint64_t param) {
    @autoreleasepool {
        if (!gui_thread()) return 0;
        if (ex_style || parent || menu || (style & ~(WS_OVERLAPPEDWINDOW | WS_VISIBLE)))
            return fail(ERROR_CALL_NOT_IMPLEMENTED);
        ensure_app();
        StandaloneClass *entry;
        if (class_name <= UINT16_MAX) {
            entry = class_atoms[@(class_name)];
        } else {
            NSString *name = guest_utf16(class_name);
            if (!name) return 0;
            entry = classes[name.lowercaseString];
        }
        if (!entry) return fail(ERROR_CANNOT_FIND_WND_CLASS);
        NSString *title = guest_utf16(window_name);
        if (!title) return 0;
        if (x == INT32_MIN) x = 64;
        if (y == INT32_MIN) y = 64;
        if (width == INT32_MIN) width = 640;
        if (height == INT32_MIN) height = 480;
        if (width < 0 || height < 0) return fail(ERROR_INVALID_PARAMETER);

        NSWindowStyleMask mask = NSWindowStyleMaskBorderless;
        if ((style & 0x00c00000) == 0x00c00000) mask |= NSWindowStyleMaskTitled;
        if (style & 0x00080000) mask |= NSWindowStyleMaskClosable;
        if (style & 0x00040000) mask |= NSWindowStyleMaskResizable;
        if (style & 0x00020000) mask |= NSWindowStyleMaskMiniaturizable;
        CGFloat screen_top = NSMaxY(NSScreen.screens.firstObject.frame);
        NSRect frame = NSMakeRect(x, screen_top - y - height, width, height);
        NSRect content = [NSWindow contentRectForFrameRect:frame styleMask:mask];
        NSWindow *window = [[NSWindow alloc] initWithContentRect:content styleMask:mask
                                                        backing:NSBackingStoreBuffered defer:NO];
        window.releasedWhenClosed = NO;
        window.title = title;

        StandaloneWindow *record = [StandaloneWindow new];
        record.hwnd = next_hwnd++;
        record.wndproc = entry.wndproc;
        record.window = window;
        record.timers = [NSMutableDictionary new];
        window.delegate = record;
        StandaloneView *view = [[StandaloneView alloc] initWithFrame:
            NSMakeRect(0, 0, content.size.width, content.size.height)];
        view.hwnd = record.hwnd;
        window.contentView = view;
        windows[@(record.hwnd)] = record;

        uint64_t create_ptr = guest_malloc(sizeof(WIN32_CREATESTRUCT));
        if (!create_ptr) {
            [window close];
            [windows removeObjectForKey:@(record.hwnd)];
            return fail(ERROR_NOT_ENOUGH_MEMORY);
        }
        WIN32_CREATESTRUCT create = {
            .param = param, .instance = instance, .menu = menu, .parent = parent,
            .height = height, .width = width, .y = y, .x = x, .style = (int32_t)style,
            .title = window_name, .class_name = class_name, .ex_style = ex_style,
        };
        store_struct(create_ptr, &create, sizeof(create));
        bool nc_created = guest_call_guest_proc(record.wndproc, record.hwnd, WM_NCCREATE, 0, create_ptr) != 0;
        bool accepted = nc_created;
        if (nc_created && !record.destroying) {
            accepted = (int64_t)guest_call_guest_proc(record.wndproc, record.hwnd, WM_CREATE, 0, create_ptr) != -1;
        }
        guest_free(create_ptr);
        if (record.destroying) return 0;
        if (!accepted) {
            destroy_window(record, nc_created);
            return 0;
        }
        if (style & WS_VISIBLE) subsys_GUI_ShowWindow(record.hwnd, 1);
        return record.hwnd;
    }
}

int32_t subsys_GUI_ShowWindow(uint64_t hwnd, int32_t command) {
    @autoreleasepool {
        StandaloneWindow *record = lookup_window(hwnd);
        if (!record) return 0;
        BOOL visible = record.window.visible;
        if (command == 0) [record.window orderOut:nil];
        else if (command == 1 || command == 5) {
            [record.window makeKeyAndOrderFront:nil];
            [record.window.contentView setNeedsDisplay:YES];
        } else return fail(ERROR_CALL_NOT_IMPLEMENTED);
        return visible;
    }
}

int32_t subsys_GUI_GetMessageW(uint64_t msg_ptr, uint64_t hwnd,
                              uint32_t filter_min, uint32_t filter_max) {
    if (!gui_thread()) return -1;
    if (!msg_ptr || filter_min > filter_max) {
        fail(ERROR_INVALID_PARAMETER);
        return -1;
    }
    if (hwnd && hwnd != UINT64_MAX && !lookup_window(hwnd)) return -1;
    ensure_app();
    for (;;) {
        @autoreleasepool {
            [NSApp updateWindows];
            for (NSUInteger i = 0; i < messages.count; ++i) {
                WIN32_MSG msg = messages[i].value;
                if (msg.message != WM_QUIT &&
                    ((hwnd && msg.hwnd != hwnd) ||
                     ((filter_min || filter_max) &&
                      (msg.message < filter_min || msg.message > filter_max)))) continue;
                store_struct(msg_ptr, &msg, sizeof(msg));
                [messages removeObjectAtIndex:i];
                return msg.message != WM_QUIT;
            }
            NSEvent *event = [NSApp nextEventMatchingMask:NSEventMaskAny untilDate:NSDate.distantFuture
                                                  inMode:NSDefaultRunLoopMode dequeue:YES];
            if (event && (event.type != NSEventTypeApplicationDefined || event.subtype != GUI_WAKE_EVENT))
                [NSApp sendEvent:event];
        }
    }
}

int32_t subsys_GUI_TranslateMessage(uint64_t msg_ptr) {
    (void)msg_ptr;
    // This backend currently enqueues no keyboard messages to translate.
    return 0;
}

int64_t subsys_GUI_DispatchMessageW(uint64_t msg_ptr) {
    @autoreleasepool {
        if (!gui_thread()) return 0;
        if (!msg_ptr) return fail(ERROR_INVALID_PARAMETER);
        uint64_t hwnd = guest_load(msg_ptr + offsetof(WIN32_MSG, hwnd), 8);
        if (!hwnd) return 0;
        StandaloneWindow *record = lookup_window(hwnd);
        if (!record) return 0;
        return (int64_t)guest_call_guest_proc(record.wndproc, hwnd,
            guest_load(msg_ptr + offsetof(WIN32_MSG, message), 4),
            guest_load(msg_ptr + offsetof(WIN32_MSG, wParam), 8),
            guest_load(msg_ptr + offsetof(WIN32_MSG, lParam), 8));
    }
}

int64_t subsys_GUI_DefWindowProcW(uint64_t hwnd, uint32_t message,
                                uint64_t wparam, int64_t lparam) {
    (void)wparam;
    (void)lparam;
    if (!gui_thread()) return 0;
    if (message == WM_NCCREATE) return 1;
    if (message == WM_CLOSE) subsys_GUI_DestroyWindow(hwnd);
    return 0;
}

int32_t subsys_GUI_DestroyWindow(uint64_t hwnd) {
    @autoreleasepool {
        StandaloneWindow *record = lookup_window(hwnd);
        if (!record || record.destroying) return 0;
        destroy_window(record, true);
        return 1;
    }
}

void subsys_GUI_PostQuitMessage(int32_t code) {
    @autoreleasepool {
        if (!gui_thread()) return;
        ensure_state();
        post_message(0, WM_QUIT, (uint64_t)(int64_t)code);
    }
}

uint64_t subsys_GUI_SetTimer(uint64_t hwnd, uint64_t id, uint32_t elapsed, uint64_t proc) {
    @autoreleasepool {
        if (!gui_thread()) return 0;
        if (!hwnd || proc) return fail(ERROR_CALL_NOT_IMPLEMENTED);
        StandaloneWindow *record = lookup_window(hwnd);
        if (!record || record.destroying) return 0;
        if (!id) {
            id = 1;
            while (record.timers[@(id)]) ++id;
        }
        [record.timers[@(id)] invalidate];
        uint32_t milliseconds = MAX(10u, MIN(elapsed, INT32_MAX));
        NSTimer *timer = [NSTimer timerWithTimeInterval:milliseconds / 1000.0 repeats:YES
                                                block:^(NSTimer *source) {
            (void)source;
            post_message(hwnd, WM_TIMER, id);
        }];
        record.timers[@(id)] = timer;
        [NSRunLoop.mainRunLoop addTimer:timer forMode:NSDefaultRunLoopMode];
        return id;
    }
}

uint64_t subsys_GUI_BeginPaint(uint64_t hwnd, uint64_t paint_ptr) {
    if (!gui_thread()) return 0;
    if (!active_paint || active_paint->hwnd != hwnd || active_paint->paint_ptr || !paint_ptr)
        return fail(ERROR_INVALID_PARAMETER);
    WIN32_PAINTSTRUCT paint = { .hdc = HDC_PAINT, .dirty = win_rect(active_paint->dirty) };
    store_struct(paint_ptr, &paint, sizeof(paint));
    active_paint->paint_ptr = paint_ptr;
    return HDC_PAINT;
}

int32_t subsys_GUI_EndPaint(uint64_t hwnd, uint64_t paint_ptr) {
    if (!gui_thread()) return 0;
    if (!paint_ptr || !active_paint || active_paint->hwnd != hwnd || active_paint->paint_ptr != paint_ptr)
        return fail(ERROR_INVALID_PARAMETER);
    active_paint->paint_ptr = 0;
    return 1;
}

int32_t subsys_GUI_FillRect(uint64_t hdc, uint64_t rect_ptr, uint64_t brush) {
    @autoreleasepool {
        if (!gui_thread()) return 0;
        NSColor *color = brushes[@(brush)];
        if (hdc != HDC_PAINT || !rect_ptr || !color || !active_paint || !active_paint->paint_ptr)
            return fail(ERROR_INVALID_PARAMETER);
        CGFloat left = (int32_t)guest_load(rect_ptr, 4);
        CGFloat top = (int32_t)guest_load(rect_ptr + 4, 4);
        CGFloat right = (int32_t)guest_load(rect_ptr + 8, 4);
        CGFloat bottom = (int32_t)guest_load(rect_ptr + 12, 4);
        CGContextSetFillColorWithColor(active_paint->context, color.CGColor);
        CGContextFillRect(active_paint->context, CGRectMake(left, top, right - left, bottom - top));
        return 1;
    }
}

int32_t subsys_GUI_GetClientRect(uint64_t hwnd, uint64_t rect_ptr) {
    @autoreleasepool {
        StandaloneWindow *record = lookup_window(hwnd);
        if (!record) return 0;
        if (!rect_ptr) return fail(ERROR_INVALID_PARAMETER);
        WIN32_RECT rect = win_rect(record.window.contentView.bounds);
        store_struct(rect_ptr, &rect, sizeof(rect));
        return 1;
    }
}

uint64_t subsys_GUI_CreateSolidBrush(uint32_t color) {
    @autoreleasepool {
        if (!gui_thread()) return 0;
        ensure_state();
        uint64_t token = next_brush++;
        brushes[@(token)] = [NSColor colorWithDeviceRed:(color & 0xff) / 255.0
                                                green:((color >> 8) & 0xff) / 255.0
                                                 blue:((color >> 16) & 0xff) / 255.0 alpha:1.0];
        return token;
    }
}

int32_t subsys_GUI_DeleteObject(uint64_t object) {
    @autoreleasepool {
        if (!gui_thread()) return 0;
        if (!brushes[@(object)]) return fail(ERROR_INVALID_PARAMETER);
        [brushes removeObjectForKey:@(object)];
        return 1;
    }
}
