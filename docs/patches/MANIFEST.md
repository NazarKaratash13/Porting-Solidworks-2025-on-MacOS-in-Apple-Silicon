# Wine compatibility patches

The stable patch series targets the Wine 11.0 source in CrossOver 26.3.0. Its source archive SHA-256 is `ac99c8ca4b3848f3e81784135f023df266b61c2345726ea55a50b3e030dd6872`. The [series file](v3.series) defines the application order. See the [macOS build guide](../MACOS_BUILD.md).

| Patch family | Scope |
| --- | --- |
| Winemac clipping and Dock patches | Window visibility, screen dimensions, resize clipping, and optional Dock snapshot suppression |
| PropertyManager patches | Capture semantics for confirm and cancel, plus manager visibility |
| Task Pane patches | Bounds, splitter and header repaint, docking, tab visibility, and caption clipping |
| Native file and AppKit patches | Finder open events and native Open, Save As, and Pack and Go panels |
| `wbemprox-full.patch` | WMI compatibility for network adapter state and optional diagnostics |

The build places `winemac.so` and `win32u.so` under `lib/wine/x86_64-unix`. The corresponding `wbemprox.dll` is built for both Windows architectures. Use modules with the matching runtime ABI. Linker UUIDs and debug metadata can change between builds. Track the actual hashes of tested artifacts.

## Graphics preview

- [Winemac client surface](winemac-winemetalgl-client-surface.patch) applies after the stable Wine series. It exposes the window-owned client surface and clips the Metal viewport using the window mask.
- [WineMetalGL 4.1.0 Vertex Span](winemetalgl-4.1.0-vertex-span.patch) applies to upstream commit `72df1b5d59ec6d7e4e8eb0514c2f3779a8170321`. It includes client-surface integration, presentation instrumentation, and ordered vertex batching.

[Build the preview](../GRAPHICS_PREVIEW.md). The Wine patches retain Wine's LGPL-2.1-or-later license. The WineMetalGL patch retains the upstream LGPL-3.0 license, with its Unix/PE bridge keeping the applicable Wine notices.
