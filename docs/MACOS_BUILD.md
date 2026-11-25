# macOS build and packaging

The setup launcher and Finder extensions build on Apple Silicon with macOS 14
or later. The Wine modules below target the x86-64 macOS CrossOver 26.3.0
runtime. Their host code runs through Rosetta on Apple Silicon.

## Build the setup launcher

On Apple Silicon, install Xcode Command Line Tools, Python 3.11 or newer and
MinGW-w64. From the repository root, run:

```sh
bash tools/solidworks-public/build.sh "$PWD/build/launcher"
bash tools/solidworks-public/test-package.sh "$PWD/build/launcher/SOLIDWORKS V3 Launcher.app"
```

The launcher includes a desktop bundle template, Quick Look extensions and the
Windows file-operation bridge. Each user supplies a compatible Wine runtime, the
official SOLIDWORKS installer and a license. After installation, the launcher
can copy that runtime and the completed installation into one private desktop
app. The test validates assembly against a synthetic installation. Activation
and compatibility with a particular Wine distribution require a separate host
test.

## Build the compatibility modules

1. Download the [CrossOver 26.3.0 FOSS source archive](https://www.codeweavers.com/crossover/source).
2. Prepare Python 3.11 or later, Git, Xcode command line tools, Rosetta, GNU
   Bison 3 or later, Flex and MinGW-w64. On Homebrew, put
   `$(brew --prefix bison)/bin` first in your build PATH.
3. Prepare a fresh tree and compile the modules.

```sh
export PATH="$(brew --prefix bison)/bin:$PATH"
mkdir -p build
python3 tools/solidworks-wine/prepare.py /path/to/crossover-sources-26.3.0.tar.gz build/wine-src
bash tools/solidworks-wine/build-modules.sh build/wine-src build/wine
```

Preparation checks the archive SHA-256, extracts the Wine subtree and applies
[`v3.series`](patches/v3.series). The build includes the WMI compatibility fix.
The separate diagnostic WMI patch is retained for historical debugging.
`BUILD_JOBS` controls build parallelism and defaults to four.

The three modules are under
`build/wine/dlls/{win32u,winemac.drv,wbemprox}`. They require the matching
runtime and do not constitute a complete Wine distribution. Validate ABI and
runtime behavior before putting rebuilt modules into service.

## Package your existing installation

The private packaging command consumes a closed, existing Wine prefix and its
compatible runtime. It requires the tools above and builds the file-operation
bridge and Quick Look extensions from this repository. The normal installer
and license prompts remain in SOLIDWORKS.

```sh
python3 tools/solidworks-macos/assemble-local.py \
  --runtime /path/to/runtime/CrossOver \
  --prefix /path/to/closed/prefix \
  --output "$PWD/build/SOLIDWORKS 2025.app"
```

The package includes an original icon, document metadata and a copy of the
supplied runtime. The launcher initializes its private writable prefix in
Application Support from the bundled seed. The initial copy is staged under a
launch lock. A subsequent launch reuses the working prefix. The packaging command
copies bundled Wine fonts into the Windows Fonts directory when their registry
paths refer to the input runtime. Successful packaging leaves the inputs intact.

The resulting `.app` is ad hoc signed for local use and contains your installation
data. Keep it private. Put it in Applications on the licensed machine and retain
the old package until the migrated session has opened and saved a test document.
The complete app is distinct from the small public setup assistant.

## Repository build artifacts

The [macOS workflow](../.github/workflows/macos-package.yml) compiles the setup
launcher and Quick Look extensions and stores ZIP archives with checksums.
Its optional Wine job builds from the pinned CodeWeavers source. Neither job
uses or requests a SOLIDWORKS license or installer.

For a distribution build, check the exact runtime and installer combination
on a separate Mac and use the applicable Apple signing and notarization.
[Apple notarization guide](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
