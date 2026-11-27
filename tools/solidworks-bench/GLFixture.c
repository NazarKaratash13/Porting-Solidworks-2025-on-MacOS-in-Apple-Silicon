/* Standalone WGL test for renderer identity, batching, and context isolation. */
#include <windows.h>
#include <GL/gl.h>
#include <stdio.h>
#include <string.h>

typedef HGLRC (WINAPI *create_context_fn)(HDC, HGLRC, const int *);

static void draw_triangle(void)
{
    /* Each call must consume the three coordinates before the caller reuses
     * this stack storage. This also holds while recording a display list. */
    GLfloat vertex[] = {-0.8f, -0.8f, 0.0f};
    glBegin(GL_TRIANGLES);
    glVertex3fv(vertex);
    vertex[0] = 0.8f;
    glVertex3fv(vertex);
    vertex[0] = 0.0f;
    vertex[1] = 0.8f;
    glVertex3fv(vertex);
    glEnd();
}

static BOOL draw(float red, float green, BOOL compile_list)
{
    glDrawBuffer(GL_BACK);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glMatrixMode(GL_MODELVIEW);
    glLoadIdentity();
    glColor3f(red, green, 0.0f);
    if (!compile_list)
    {
        draw_triangle();
        return TRUE;
    }
    GLuint list = glGenLists(1);
    if (!list) return FALSE;
    glNewList(list, GL_COMPILE);
    draw_triangle();
    glEndList();
    glCallList(list);
    glDeleteLists(list, 1);
    return TRUE;
}

static BOOL read_pixel(int red, int green)
{
    GLubyte pixel[4] = {0};
    glReadBuffer(GL_BACK);
    glReadPixels(80, 80, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
    printf("pixel=%u,%u,%u,%u\n", pixel[0], pixel[1], pixel[2], pixel[3]);
    return pixel[0] == red && pixel[1] == green && pixel[2] == 0 && glGetError() == GL_NO_ERROR;
}

static BOOL late_attribute_changes(void)
{
    GLfloat current[4] = {0};
    glClear(GL_COLOR_BUFFER_BIT);
    glShadeModel(GL_FLAT);
    glColor3f(1, 0, 0);
    glBegin(GL_TRIANGLES);
    glVertex3f(-0.8f, -0.8f, 0.0f);
    glVertex3f(0.8f, -0.8f, 0.0f);
    glColor3f(0, 1, 0);
    glVertex3f(0.0f, 0.8f, 0.0f);
    glColor3f(0, 0, 1);
    glEnd();
    glGetFloatv(GL_CURRENT_COLOR, current);
    return current[0] == 0 && current[1] == 0 && current[2] == 1 && read_pixel(0, 255);
}

static BOOL mutable_client_array(void)
{
    GLfloat vertices[] = {
        -0.8f, -0.8f, 0, 0.8f, -0.8f, 0, 0, 0.8f, 0,
        -0.8f, -0.8f, 0, 0.8f, -0.8f, 0, 0, 0.8f, 0
    };
    GLfloat original[sizeof(vertices) / sizeof(vertices[0])];
    memcpy(original, vertices, sizeof(vertices));
    glColor3f(1, 0, 0);
    glEnableClientState(GL_VERTEX_ARRAY);
    glVertexPointer(3, GL_FLOAT, 0, vertices);
    for (int pass = 0; pass < 4; ++pass)
    {
        if (pass == 2)
        {
            for (size_t i = 0; i < sizeof(vertices) / sizeof(vertices[0]); i += 3)
                vertices[i] += 2.0f;
        }
        if (pass == 3)
            memcpy(vertices, original, sizeof(vertices));
        glClear(GL_COLOR_BUFFER_BIT);
        glDrawArrays(GL_TRIANGLES, 0, 6);
        if (!read_pixel(pass == 2 ? 0 : 255, 0)) return FALSE;
    }
    glDisableClientState(GL_VERTEX_ARRAY);
    return TRUE;
}

int main(void)
{
    WNDCLASSW window_class = {.style = CS_OWNDC, .lpfnWndProc = DefWindowProcW,
                              .hInstance = GetModuleHandleW(NULL), .lpszClassName = L"SWV3GLFixture"};
    if (!RegisterClassW(&window_class)) return 2;
    HWND window = CreateWindowW(window_class.lpszClassName, L"SWV3 WGL fixture",
                                WS_OVERLAPPEDWINDOW | WS_VISIBLE, CW_USEDEFAULT, CW_USEDEFAULT,
                                240, 240, NULL, NULL, window_class.hInstance, NULL);
    if (!window) return 3;
    HDC dc = GetDC(window);
    PIXELFORMATDESCRIPTOR format = {.nSize = sizeof(format), .nVersion = 1,
        .dwFlags = PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER,
        .iPixelType = PFD_TYPE_RGBA, .cColorBits = 24, .cDepthBits = 24, .iLayerType = PFD_MAIN_PLANE};
    int index = ChoosePixelFormat(dc, &format);
    if (!index || !SetPixelFormat(dc, index, &format))
    {
        printf("PIXEL_FORMAT_FAILURE choose=%d error=%lu\n", index, (unsigned long)GetLastError());
        return 4;
    }
    HGLRC first = wglCreateContext(dc);
    HGLRC second = wglCreateContext(dc);
    if (!first || !second || !wglMakeCurrent(dc, first)) return 5;
    printf("GL_VENDOR=%s\nGL_RENDERER=%s\nGL_VERSION=%s\n",
            glGetString(GL_VENDOR), glGetString(GL_RENDERER), glGetString(GL_VERSION));
    glViewport(0, 0, 160, 160);
    if (!draw(1, 0, FALSE) || !read_pixel(255, 0) || !SwapBuffers(dc)) return 6;
    glEnable(0xffffffff);
    if (glGetError() != GL_INVALID_ENUM || glGetError() != GL_NO_ERROR) return 7;
    if (!wglMakeCurrent(dc, second)) return 8;
    glViewport(0, 0, 160, 160);
    if (!draw(0, 1, TRUE) || !read_pixel(0, 255) || !SwapBuffers(dc)) return 9;
    if (!wglMakeCurrent(dc, first)) return 10;
    GLfloat color[4] = {0};
    glGetFloatv(GL_CURRENT_COLOR, color);
    if (color[0] != 1 || color[1] != 0) return 11;
    if (!late_attribute_changes()) return 12;
    /* Returning to a packed position-only draw must clear the previous
     * draw's varying color array on the same private VAO. */
    if (!draw(1, 0, FALSE) || !read_pixel(255, 0)) return 13;
    if (!mutable_client_array()) return 14;
    PROC proc = wglGetProcAddress("wglCreateContextAttribsARB");
    if ((UINT_PTR)proc > 3 && (UINT_PTR)proc != (UINT_PTR)-1)
    {
        create_context_fn create = NULL;
        memcpy(&create, &proc, sizeof(create));
        int attrs[] = {0x2091, 4, 0x2092, 5, 0x9126, 1, 0};
        HGLRC core = create(dc, NULL, attrs);
        if (core && wglMakeCurrent(dc, core))
            printf("WGL 4.5 core: %s\n", glGetString(GL_VERSION));
        else
            printf("WGL 4.5 core unavailable (Win32 error %lu)\n", (unsigned long)GetLastError());
        wglMakeCurrent(dc, NULL);
        if (core) wglDeleteContext(core);
    }
    else
    {
        puts("WGL_ARB_create_context unavailable");
        wglMakeCurrent(dc, NULL);
    }
    wglDeleteContext(second);
    wglDeleteContext(first);
    ReleaseDC(window, dc);
    DestroyWindow(window);
    puts("PASS WGL pixel, error ordering, and context isolation");
    return 0;
}
