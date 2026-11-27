# Vertex Span graphics preview

The measured preview runs SOLIDWORKS 2025 SP05 through an x86-64 CrossOver 26.3.0-style Wine runtime and WineMetalGL on Rosetta. Vertex Span groups contiguous `glVertex3fv` records already copied into a Unix-side command batch. It preserves vertex order and uses the original path when the context or record layout is incompatible.

## Prepare the runtime

Use a separate copy of your V3-compatible CrossOver runtime and a closed copy of a licensed SOLIDWORKS prefix. The public release provides source patches and the setup launcher. Obtain the compatible runtime, Wine headers, and SOLIDWORKS installation independently.

1. Prepare the matching Wine 11 source from the pinned CodeWeavers archive following the [macOS build guide](MACOS_BUILD.md). Apply [the Winemac client-surface patch](patches/winemac-winemetalgl-client-surface.patch) after the V3 series and rebuild the Winemac module against the matching Wine tree. The shared client surface keeps the Metal viewport aligned with the Win32 window mask.
2. Check out upstream [WineMetalGL 4.1.0](https://github.com/MetalSharp/WineMetalGL/commit/72df1b5d59ec6d7e4e8eb0514c2f3779a8170321), then apply [the cumulative Vertex Span patch](patches/winemetalgl-4.1.0-vertex-span.patch). Use Xcode Command Line Tools, CMake, Python 3 and llvm-mingw. Keep the WineMetalGL source, Wine headers and module build directories at paths without spaces for the upstream shell builder.

```sh
git -C "$wmgl_source" checkout --detach 72df1b5d59ec6d7e4e8eb0514c2f3779a8170321
git -C "$wmgl_source" apply --check "$release_source/docs/patches/winemetalgl-4.1.0-vertex-span.patch"
git -C "$wmgl_source" apply "$release_source/docs/patches/winemetalgl-4.1.0-vertex-span.patch"
cmake -S "$wmgl_source" -B "$core_build" -DWMGL_HOST_ONLY=ON \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=x86_64
cmake --build "$core_build" --target winemetalgl_core --parallel 2
sh "$wmgl_source/scripts/build-wine-module.sh" "$wine_headers" "$bridge_build"
```

3. Copy `winemetalgl.so` and `libwinemetalgl.dylib` into the experimental runtime's `lib/wine/x86_64-unix`. Install the rebuilt `winemetalgl.dll` in `lib/wine/x86_64-windows`. Place matching `winemetalgl.dll` and the rebuilt `opengl32.dll` forwarder beside `SLDWORKS.exe` in the experimental prefix. Keep Wine's system OpenGL DLL intact. In this prefix, set the application-specific Wine DLL override `HKCU\Software\Wine\AppDefaults\SLDWORKS.exe\DllOverrides\opengl32` to the string `native,builtin`.
4. The measured M4 profile used `Workarounds=0x04000000` at `HKCU\Software\SolidWorks\AllowList\WineMetalGL\M4 (WineMetalGL)`. Apply that test setting only after the WGL fixture confirms the exact vendor and renderer. This setting changes the graphics path and leaves RealView unavailable in the measured configuration.

## Package and verify

```sh
python3 tools/solidworks-macos/assemble-local.py \
  --runtime "$lab_runtime" --prefix "$lab_prefix" --graphics-lab "$wmgl_source" \
  --output "$build_dir/SOLIDWORKS V3 Vertex Span Preview.app"
codesign --verify --strict "$build_dir/SOLIDWORKS V3 Vertex Span Preview.app"
```

The packager checks that the WineMetalGL PE copies match and that both Unix modules carry the Vertex Span entry point. The preview stores its working profile under `~/Library/Application Support/local.solidworks2025.v3vertexspanpreview`. Leave the existing V3 installation in place.

Close the running SOLIDWORKS session normally before opening the preview. To launch the same private preview with Apple OpenGL, use `open -a "$preview_app" --args --backend=opengl`. For a controlled WineMetalGL A/B test, explicitly set `SWV3_WMGL_VERTEX_SPANS=0` or `1` on the [benchmark suite](BENCHMARKS.md).

ARM64 Wine/FEX is separate research. The rebuilt ARM64X bridge and ARM64 WineMetalGL passed the x86-64 WGL fixture. The SOLIDWORKS control part timed out during COM readiness, and MyCNC measurements use the Rosetta configuration above.
