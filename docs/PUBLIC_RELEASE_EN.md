# SOLIDWORKS 2025 on Apple Silicon

V3 is an independent compatibility project for running the Windows edition of SOLIDWORKS 2025 on Apple Silicon through Wine and Rosetta. It provides a macOS setup launcher, Finder integration, graphics patches, and test tooling.

[Download v0.3.0](https://github.com/NazarKaratash13/Porting-Solidworks-2025-on-MacOS-in-Apple-Silicon/releases/latest) · [Setup guide](SETUP.md) · [Release notes](RELEASE-v0.3.0.md) · [Benchmarks](BENCHMARKS.md)

![SOLIDWORKS assembly with three ISO Toolbox bolts](assets/toolbox-demo.png)

## Get started

1. Download the Apple Silicon DMG or ZIP and move **SOLIDWORKS V3 Launcher** to Applications.
2. Open the launcher and choose a compatible Wine runtime.
3. Select **Setup.exe** from your extracted official SOLIDWORKS media. Complete installation in the Windows installer.
4. Choose **Build Mac App**, then open your private app and complete normal license activation if prompted.

You need Apple Silicon, macOS 14 or later, a compatible Wine runtime, and licensed SOLIDWORKS 2025 media. The public launcher uses an ad hoc signature. [First launch, checksums, and runtime selection](SETUP.md).

## Graphics in v0.3.0

A prepared runtime can use **baseline WineMetalGL**. The release disables the experimental vertex submission paths tested during the freeze investigation. The app also supports an Apple OpenGL fallback. [Prepare WineMetalGL](GRAPHICS_PREVIEW.md).

On an Apple M4 with 16 GiB, the hotfix applied Image Quality settings on **MyCNC with 733 occurrences** and completed three full-detail rotation passes afterward. These were stability checks. The earlier 16 FPS figures belong to the experimental Vertex Span path. [Test results and limitations](BENCHMARKS.md).

## What comes next

The bar for V3 is a daily-use engineering workflow with reliable editing, saving, rebuilding, and exporting. Large assemblies should stay responsive at full detail. There is substantial work ahead.

- Reach **30 displayed FPS** on MyCNC at full detail across repeatable runs. Treat **60 FPS** as a stretch goal.
- Isolate the accelerated vertex-path freeze and test context switches, geometry updates, and GPU memory during long sessions.
- Expand coverage for Toolbox, drawings, multi-document editing, and STEP/STL export.
- Verify RealView through rendering evidence, then revisit SPECapc.
- Improve installation on clean Macs and pursue Developer ID signing and notarization.
- Continue evaluating ARM64 Wine and FEX in the laboratory.

## Source and contribution

- [Launcher and desktop packaging](../tools/solidworks-public)
- [macOS and Wine module builds](MACOS_BUILD.md)
- [Development and architecture](DEVELOPMENT.md)
- [Contribution guide](../CONTRIBUTING.md)
- [Original Russian guide](../README.ru.md)

V3 is independent of Dassault Systèmes. SOLIDWORKS and SPECapc are trademarks of their respective owners. The public packages contain the launcher and integrations. Obtain SOLIDWORKS, its license, and commercial runtimes directly from their providers. V3's own tooling is [MIT licensed](../LICENSE). Driver patches retain their [Wine](../licenses/Wine-LGPL-2.1.txt) and [WineMetalGL](../licenses/WineMetalGL-LGPL-3.0.txt) licenses.
