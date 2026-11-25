# Instructions for development agents

This is a research recompiler, not a finished native Windows compatibility layer.
The objective is a **measured, Wine-independent path** for supported Windows x86-64
programs on macOS ARM64. Do not imply general SOLIDWORKS support.

Read `docs/DEV_WORKFLOW_RU.md`, `docs/ARCHITECTURE_RU.md` and
`docs/ROADMAP_NO_WINE_RU.md` before implementing a feature.

Rules:

1. Preserve the immutable test corpus (`work/corpus/*.exe`). Never regenerate or
   replace these files implicitly. Use `tools/dev.py snapshot` to record their hashes.
2. Each change must explain the guest instruction/API behavior it implements,
   how it handles failures/edge cases, and which test detects regressions.
3. Run `python3 tools/dev.py check` for every patch. On Apple Silicon, run
   `python3 tools/dev.py smoke` after changing lifting, ABI, PE load or runtime.
   For large changes use `python3 tools/dev.py native-full`.
4. A `SKIP` is not `PASS`. GUI fixtures in `recompiler/fixtures/gui` currently
   depend on a Wine-hosted stack. Never call them Wine-free tests.
5. Do not alter expected outputs to conceal failures. Record measured vs claimed
   behavior, and use actual timing/RSS baselines, not the README's old benchmarks.
6. Keep guest x86-64 calling conventions separate from ARM64 host ABI. Verify
   sign/zero extension, stack alignment, SEH/TLS, callback lifetime and threads.
7. Never silently enable JIT, Wine, Rosetta, or network downloads in the no-Wine
   test path. AOT, x86 interpreter fallback, and hosted execution are distinct.
8. Avoid monolithic refactors in `console_runtime.c` / `console_lift.py` without
   focused regression fixtures. Extract modules in small reviewable steps.
9. Changes to syscall stubs, memory protection, COM, native GUI, or networking
   require negative and boundary tests. No 'success' stubs without semantics.
10. Treat PE files as untrusted input; static inspection should never execute
    them. Do not bypass licensing/DRM or incorporate proprietary code into repo.

Before reporting a feature as complete, state: files changed, test command,
actual result on the tested OS/architecture, known failures, next smallest step.
