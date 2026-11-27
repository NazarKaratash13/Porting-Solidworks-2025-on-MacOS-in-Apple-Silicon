# Development and architecture

The desktop port and the ahead-of-time recompiler are separate projects in this repository.

| Area | Source |
| --- | --- |
| macOS launcher, package validation, installer process control | [tools/solidworks-public](../tools/solidworks-public) |
| Private desktop and preview app assembly | [tools/solidworks-macos](../tools/solidworks-macos) |
| Wine window, COM and graphics compatibility | [docs/patches](patches) |
| ScreenCaptureKit frame tracking and isolated CAD automation | [tools/solidworks-bench](../tools/solidworks-bench) |
| x86-64 PE analysis, LLVM IR lifting and ARM64 linking | [recompiler](../recompiler) |

The desktop port runs licensed SOLIDWORKS Windows binaries. Wine implements Windows APIs and Rosetta translates the x86-64 host runtime. WineMetalGL optionally sends OpenGL work to Metal. Winemac owns the window and clips the viewport against surrounding Win32 UI. The recompiler follows a different route that lifts selected PE programs ahead of time and has an independent validation corpus. [Recompiler startup guide](../recompiler/START.md).

## Development checks

```sh
python3 tools/dev.py check
python3 tools/dev.py snapshot
```

Keep the original corpus binaries unchanged. For changes to the lifter, PE loader, guest ABI, or runtime, run `python3 tools/dev.py smoke` on Apple Silicon with the original test corpus available. Use `python3 tools/dev.py native-full` for broader changes. Capture exact versions, checksums, and statuses. A skipped test remains a skipped test.

Run [macOS packaging tests](MACOS_BUILD.md) for launcher changes. For graphics changes, keep the working installation separate and use a new Wine prefix for each comparison. Reuse the same assembly, viewport settings, input trajectory, and image quality. Validate the resulting geometry and keep raw laboratory data local when it contains personal paths, proprietary files or licensed installation data.

## Current research priorities

1. Reduce repeated draw submission and state binding on full-detail assemblies.
2. Validate the ARM64 Wine/FEX graphics bridge with actual CAD documents and trace the loader wait that blocks the current trial.
3. Expand standalone recompiler coverage through differential tests for memory, exception handling, callbacks and threads. Keep this result separate from Wine-hosted CAD.
