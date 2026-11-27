# Prepare WineMetalGL

The tested release configuration runs SOLIDWORKS 2025 SP05 through an x86-64 CrossOver 26.3.0-style Wine runtime and WineMetalGL on Rosetta. Vertex Span groups contiguous `glVertex3fv` records already copied into a Unix-side command batch. It preserves vertex order and uses the original path when the context or record layout is incompatible.

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

To use the launcher, run the official installer first. The launcher keeps the completed prefix in `~/Library/Application Support/org.swv3.launcher/prefix`. Apply the matching Windows modules in that completed prefix, reopen the launcher, and select **Use WineMetalGL when building the app**.

For an existing licensed installation, use the command-line packager:

```sh
python3 tools/solidworks-macos/assemble-local.py \
  --runtime "$lab_runtime" --prefix "$lab_prefix" --metal-source "$wmgl_source" \
  --output "$build_dir/SOLIDWORKS 2025.app"
codesign --verify --strict "$build_dir/SOLIDWORKS 2025.app"
```

Both release build paths keep the baseline vertex submission settings and can start with Apple OpenGL using `--backend=opengl`. For isolated experiments, build with `--graphics-lab` in place of `--metal-source`. To repeat the earlier Vertex Span measurements, set `SWV3_WMGL_BATCH_VERTEX3FV=1`, `SWV3_WMGL_COMPACT_IMMEDIATE=1`, `SWV3_WMGL_CONTEXT_LOCAL_VERTICES=1`, and `SWV3_WMGL_VERTEX_SPANS=1` explicitly when invoking the lab launcher or [benchmark suite](BENCHMARKS.md).

ARM64 Wine/FEX is separate research. The rebuilt ARM64X bridge and ARM64 WineMetalGL passed the x86-64 WGL fixture. The SOLIDWORKS control part timed out during COM readiness. The tested release uses Rosetta.
