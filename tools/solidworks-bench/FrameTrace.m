/* Optional lab-only recorder for the Apple OpenGL path in WineMac. */
#import <AppKit/AppKit.h>
#import <OpenGL/gl.h>
#import <objc/runtime.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

static void (*flush_buffer)(NSOpenGLContext *, SEL);
static pthread_mutex_t trace_lock = PTHREAD_MUTEX_INITIALIZER;
static int frames = -1, contexts = -1;
static CGLContextObj observed[128];
static size_t context_count;

static void record_flush(NSOpenGLContext *self, SEL selector)
{
    uint64_t before = clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW);
    flush_buffer(self, selector);
    uint64_t after = clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW);
    CGLContextObj context = [self CGLContextObj];
    if (!context || after < before) return;

    uint64_t record[] = {(uintptr_t)context, before, after};
    pthread_mutex_lock(&trace_lock);
    if (frames >= 0 && write(frames, record, sizeof(record)) != sizeof(record))
    {
        close(frames);
        frames = -1;
    }
    if (contexts >= 0 && CGLGetCurrentContext() == context && context_count < sizeof(observed) / sizeof(*observed))
    {
        size_t index = 0;
        while (index < context_count && observed[index] != context) index++;
        if (index == context_count)
        {
            const GLubyte *renderer = glGetString(GL_RENDERER);
            const GLubyte *version = glGetString(GL_VERSION);
            const GLubyte *vendor = glGetString(GL_VENDOR);
            GLint viewport[4] = {0}, interval = 0, accelerated = 0, profile = 0;
            CGLPixelFormatObj pixels = CGLGetPixelFormat(context);
            glGetIntegerv(GL_VIEWPORT, viewport);
            CGLGetParameter(context, kCGLCPSwapInterval, &interval);
            if (pixels)
            {
                CGLDescribePixelFormat(pixels, 0, kCGLPFAAccelerated, &accelerated);
                CGLDescribePixelFormat(pixels, 0, kCGLPFAOpenGLProfile, &profile);
            }
            observed[context_count++] = context;
            dprintf(contexts, "%llu\t%d\t%d\t%d\t%d\t%d\t%s\t%s\t%s\n",
                    (unsigned long long)(uintptr_t)context, viewport[2], viewport[3], interval,
                    accelerated, profile, renderer ? (const char *)renderer : "",
                    version ? (const char *)version : "", vendor ? (const char *)vendor : "");
        }
    }
    pthread_mutex_unlock(&trace_lock);
}

__attribute__((constructor)) static void install_recorder(void)
{
    const char *pid = getenv("SWV3_FRAME_TRACE_PID");
    const char *path = getenv("SWV3_FRAME_TRACE");
    if (!pid || !path || strtol(pid, NULL, 10) != getpid()) return;

    Method method = class_getInstanceMethod([NSOpenGLContext class], @selector(flushBuffer));
    if (!method) return;
    flush_buffer = (void *)method_getImplementation(method);
    if (!flush_buffer) return;
    char meta[4096];
    int length = snprintf(meta, sizeof(meta), "%s.contexts.tsv", path);
    if (length < 0 || (size_t)length >= sizeof(meta)) return;
    frames = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (frames < 0) return;
    contexts = open(meta, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (contexts < 0)
    {
        close(frames);
        frames = -1;
        unlink(path);
        return;
    }
    method_setImplementation(method, (IMP)record_flush);
}
