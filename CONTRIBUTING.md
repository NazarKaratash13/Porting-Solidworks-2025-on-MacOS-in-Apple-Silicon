# Contributing

Run `python3 tools/dev.py check` before submitting a change. Report skipped tests
with their prerequisites. For a Wine change, include the baseline archive
version, the patch filename and the exact macOS and SOLIDWORKS versions tested.

For an issue, include steps to reproduce, the result you expected, what you
observed, and whether the issue also occurs with a fresh test document. Use a
minimal synthetic CAD model when possible. Remove local paths, serial numbers
and proprietary document contents from attachments and logs.

Follow the [development workflow](docs/DEVELOPMENT.md) for the recompiler
and the [macOS build guide](docs/MACOS_BUILD.md) for packaging and Wine changes.
