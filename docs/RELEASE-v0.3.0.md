# SOLIDWORKS V3 v0.3.0

The full v0.3.0 release brings a step-by-step English Mac setup launcher and the baseline WineMetalGL configuration tested after the Vertex Span preview freezes.

## Downloads

| Asset | Use |
| --- | --- |
| SOLIDWORKS-V3-Launcher-macOS-arm64.dmg | Setup launcher with an Applications shortcut |
| SOLIDWORKS-V3-Launcher-macOS-arm64.zip | The setup launcher in ZIP format |
| v0.3.0-validation.json | Hardware and stability test results |
| SHA256SUMS.txt | SHA-256 checksums for the downloads |

The launcher is ad hoc signed and has no Apple notarization. Use your compatible runtime, official SOLIDWORKS media, and valid license to build a private Mac app. [Setup guide](https://github.com/NazarKaratash13/Porting-Solidworks-2025-on-MacOS-in-Apple-Silicon/blob/v0.3.0/docs/SETUP.md).

## Changes and verification

- The English launcher identifies the current setup step, guides the user to the official installer, verifies the app bundle, and shows where the built app was saved.
- The launcher detects compatible prepared WineMetalGL files. WineMetalGL apps use a separate working profile and have an Apple OpenGL fallback. The release leaves four experimental vertex submission paths disabled.
- The macOS file bridge and Finder Quick Look extensions are included.
- On an Apple M4 with 16 GiB, the baseline WineMetalGL hotfix opened MyCNC with 733 occurrences at full detail. Applying the Image Quality dialog was followed by three completed rotation passes. The installed hotfix also opened a control part and loaded its own WineMetalGL library.
- The earlier Vertex Span FPS figures describe the experiment. New displayed FPS and long-session stability remain unmeasured. SPECapc stopped at the RealView prerequisite. [Validation details](https://github.com/NazarKaratash13/Porting-Solidworks-2025-on-MacOS-in-Apple-Silicon/blob/v0.3.0/docs/BENCHMARKS.md).

## What remains

V3 aims to become a dependable everyday CAD environment on Apple Silicon. There is substantial work ahead. Our next performance target is **30 displayed FPS in every full-detail MyCNC run**, with **60 FPS** as a stretch goal. The stability work includes isolating the vertex-path freeze, testing GPU resource lifetimes during long sessions, and expanding coverage of editing, rebuilding, and export. RealView verification, more clean-Mac installations, and Apple notarization are also open.
