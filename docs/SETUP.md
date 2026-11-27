# Set up SOLIDWORKS V3

You need an Apple Silicon Mac with macOS 14 or later, Rosetta, a compatible Wine runtime, and official SOLIDWORKS 2025 media with a valid license.

1. Download the DMG or ZIP and SHA256SUMS.txt from [GitHub Releases](https://github.com/NazarKaratash13/Porting-Solidworks-2025-on-MacOS-in-Apple-Silicon/releases/latest). Compare the package's SHA-256 with the checksum file.
2. Open the DMG or extract the ZIP. Move **SOLIDWORKS V3 Launcher.app** to Applications. The release is ad hoc signed and has no Apple notarization. See the [source build and signing guide](MACOS_BUILD.md).
3. Choose **Wine Runtime**. Select a self-contained runtime directory with `bin/wineserver` and either `lib/wine/x86_64-unix/wine` or `bin/wine`. Obtain commercial runtimes from their providers.
4. Choose **Select Setup.exe**. Select the executable from the extracted official media and finish installing in the Windows installer.
5. Choose **Build Mac App**. Select a destination for `SOLIDWORKS 2025.app`. Use a different destination if an app already exists there.
6. Choose **Open SOLIDWORKS** and complete normal activation if prompted.

**Projects Folder** optionally maps a selected local folder to Windows drive W:. macOS manages local file access.

## Graphics

A standard runtime uses Wine's OpenGL. To use WineMetalGL, [prepare the matching graphics modules](GRAPHICS_PREVIEW.md) and put the matching Windows modules beside `SLDWORKS.exe` in the completed setup prefix. If the launcher detects the prepared files, it offers **Use WineMetalGL when building the app**. This uses baseline WineMetalGL and a separate writable profile.

For a one-time Apple OpenGL launch, quit SOLIDWORKS and run:

```sh
open -a "/Applications/SOLIDWORKS 2025.app" --args --backend=opengl
```

The next ordinary launch uses the package's default.

## Troubleshooting

The setup prefix is at `~/Library/Application Support/org.swv3.launcher/prefix`. Mac apps built in the launcher keep their writable prefix and `launch.log` under `~/Library/Application Support/org.swv3.desktop`. The WineMetalGL profile uses its `metal` subdirectory.

For GitHub reports, include the launcher version, macOS version, runtime, graphics backend, and last successful step. Keep license information, private paths, and CAD files out of public reports.
