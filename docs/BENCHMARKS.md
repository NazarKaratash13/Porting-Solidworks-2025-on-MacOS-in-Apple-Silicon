# Benchmark results and reproduction

## v0.3.0 stability validation

The baseline WineMetalGL configuration from the local preview.2 hotfix was exercised on an Apple M4 with 16 GiB. MyCNC opened with 733 occurrences and zero LOD, Large Assembly Mode, lightweight components, and automatic Large Assembly Settings. The test opened and applied the Image Quality dialog, followed by three full-detail passes of 12 COM rotation calls each in **1.89, 1.93, and 1.90 seconds**. Process physical footprint stayed around **3.59 GiB** over these three checks. The installed hotfix opened a control part and loaded its own packaged WineMetalGL. These checks do not measure presented FPS or rule out long-session resource leaks.

The displayed FPS figures below describe the earlier Vertex Span lab configuration. The v0.3.0 benchmark defaults to baseline WineMetalGL. See [the graphics guide](GRAPHICS_PREVIEW.md) for opt-in experiment settings. The release asset v0.3.0-validation.json contains the stability results without private files or local paths.


## Graphics preview

The tests used Apple M4, 16 GiB of unified memory, macOS 27.2.1, and SOLIDWORKS 2025 SP05 Student Edition (33.5.0). Each rotation series used 480 mouse input steps with 16 ms pacing and three passes. ScreenCaptureKit counted changed frames. LOD and Large Assembly Settings were disabled, and the API reported zero lightweight occurrences.

| Workload | Vertex Span | Three passes, FPS | Median FPS |
| --- | --- | --- | ---: |
| MyCNC, 733 occurrences | Off | 15.20 / 15.28 / 15.34 | 15.28 |
| MyCNC, 733 occurrences | On, same test package | 15.80 / 16.72 / 16.50 | 16.50 |
| MyCNC, 733 occurrences | On, signed laboratory package | 16.30 / 16.55 / 15.95 | 16.30 |
| Motor, 42 occurrences | Off | 18.34 / 17.98 / 11.12 | 17.98 |
| Motor, 42 occurrences | On, laboratory package | 18.66 / 17.82 / 18.53 | 18.53 |
| Motor, 42 occurrences | On, app assembled from release source | 18.30 / 18.32 / 18.30 | 18.30 |

The signed MyCNC run improved the control median by 6.68%. P95 frame times were 68.53 / 68.56 / 77.54 ms. Mass, volume, STEP entities, and the STL mesh hash matched. An earlier packaged run timed out on the final detail-state check and was excluded. The repeated run completed the check.

The Motor control included one slow pass. The other results overlap with the enabled series, so the data describes performance on an additional model with limited evidence for a speedup. With Vertex Span enabled, Motor opened in 6.80 s, rebuilt in 11.95 s, and peaked at 3.26 GiB of sampled SOLIDWORKS physical footprint. RealView, shadows, and ambient occlusion were off. [Raw measurements](benchmarks/graphics-preview-benchmarks.json).

## SPECapc for SOLIDWORKS 2025

SPECapc 1.0 was installed in an isolated Wine prefix. The NW.js front end failed in its GPU process. The supplied benchmark executable ran directly with CPU tests and FSAA disabled. It started SOLIDWORKS and opened TeapotOIT without reported errors or warnings. The recorded load time was 10.45 s.

The runner then tried to enable RealView and read its state back from SOLIDWORKS. That prerequisite failed. A diagnostic run using a copy of the scenario list without the two RealView modes met the same check. No SPECapc score, result XML, or OIT comparison was produced. The Motor rotation above uses an independent protocol. The CPU suite requires the appropriate Visualize and Simulation components. [SPECapc benchmark run rules](https://gwpg.spec.org/wp-content/uploads/2026/01/SPECapc_Solidworks25_BenchmarkRunRules.pdf).

SpaceShipCrawler loaded for a separate full-detail test in 114.08 s. The input probe failed to capture the viewport, so that attempt provides no FPS. The shipped SPECapc scenario for this model uses Large Design Review.

## Reproduce the rotation test

Build a [private Vertex Span preview](GRAPHICS_PREVIEW.md). Copy the complete assembly folder, its dependencies, and a control part into the fixture directory. For Motor, copy the `Motor` folder from the official SPECapc installation. Grant Screen Recording access for the capture.

```sh
SWV3_WMGL_VERTEX_SPANS=0 python3 tools/solidworks-bench/suite.py \
  --app "$preview_app" --fixture-root "$fixtures" \
  --part Control.SLDPRT --assembly Motor/Montagem1.SLDASM \
  --expected-components 42 --steps 480 --operations 3 --evidence --output "$control_report"

SWV3_WMGL_VERTEX_SPANS=1 python3 tools/solidworks-bench/suite.py \
  --app "$preview_app" --fixture-root "$fixtures" \
  --part Control.SLDPRT --assembly Motor/Montagem1.SLDASM \
  --expected-components 42 --steps 480 --operations 3 --evidence \
  --compare "$control_report/suite.json" --output "$span_report"
```

Run one CAD instance at a time with the same viewport, capture resolution, trajectory, and display effects. Inspect the captured model throughout the orbit. The suite retains driver hashes, model manifests, timings, detail settings, and engineering checks.

## Stable v0.2.0 measurements

Median startup to an open assembly was 27.42 s. Median open, rebuild, and save-copy times were 2.480 / 0.359 / 0.223 s for a part and 3.607 / 0.464 / 0.233 s for the Toolbox test assembly. The combined SOLIDWORKS and Wine server physical footprint rose from 2.60 GiB with two documents open to 4.52 GiB with eleven. [Startup samples](benchmarks/startup.json) · [Document operation samples](benchmarks/operations.csv).
