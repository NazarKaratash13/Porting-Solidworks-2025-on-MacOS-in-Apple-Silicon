# SOLIDWORKS V3 v0.3.0-preview.1

This experimental release brings the Vertex Span graphics changes, an English macOS setup launcher, and reproducible benchmark tooling. v0.2.0 remains the stable launcher release.

## Downloads

| Asset | Purpose |
| --- | --- |
| `SOLIDWORKS-V3-Launcher-macOS-arm64.dmg` | Setup launcher with a shortcut to Applications |
| `SOLIDWORKS-V3-Launcher-macOS-arm64.zip` | The same launcher in ZIP format |
| `graphics-preview-benchmarks.json` | Selected raw measurements and their test settings |
| `SHA256SUMS.txt` | Integrity checks for the release assets |

The launcher is ad hoc signed. Install from your official SOLIDWORKS media using a compatible runtime and valid license. The WineMetalGL preview is assembled separately from your own installation. [Installation and build instructions](https://github.com/NazarKaratash13/Porting-Solidworks-2025-on-MacOS-in-Apple-Silicon/tree/v0.3.0-preview.1#readme).

## Results

- **MyCNC** with 733 occurrences and full detail ran at **16.30 / 16.55 / 15.95 FPS** on Apple M4 with 16 GiB. Median throughput improved **6.68%** over the control for the signed laboratory package. Mass, volume, STEP structure, and the STL mesh matched.
- **Motor** from SPECapc with 42 occurrences ran at a median **18.53 FPS** in the independent full-detail rotation benchmark. A new app built with the release packager repeated the result at a median 18.30 FPS.
- **SPECapc 2025** opened TeapotOIT and stopped at its RealView check. No SPEC score was generated.
- **ARM64 Wine/FEX** passed the standalone WGL fixture. The SOLIDWORKS launch reached the graphics driver and timed out on COM readiness.

The MyCNC 30 FPS target remains open. The graphics preview keeps its own profile and supports the stock OpenGL fallback. [Benchmark details and reproducibility](https://github.com/NazarKaratash13/Porting-Solidworks-2025-on-MacOS-in-Apple-Silicon/blob/v0.3.0-preview.1/docs/BENCHMARKS.md).
