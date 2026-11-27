import Foundation

private func expect(_ condition: @autoclosure () -> Bool, _ label: String) throws {
    guard condition() else { throw SetupError("Package check failed: \(label)") }
}

@main
struct PackageChecks {
    static func main() throws {
        let files = FileManager.default
        let work = files.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try files.createDirectory(at: work, withIntermediateDirectories: false)
        defer { try? files.removeItem(at: work) }
        let runtime = work.appendingPathComponent("Test Runtime")
        let bin = runtime.appendingPathComponent("bin")
        let fonts = runtime.appendingPathComponent("share/wine/fonts")
        try files.createDirectory(at: bin, withIntermediateDirectories: true)
        try files.createDirectory(at: fonts, withIntermediateDirectories: true)
        try Data("test font".utf8).write(to: fonts.appendingPathComponent("test.ttf"))
        for name in ["wine", "wineserver"] {
            let executable = bin.appendingPathComponent(name)
            try "#!/bin/sh\nexit 0\n".write(to: executable, atomically: true, encoding: .utf8)
            try files.setAttributes([.posixPermissions: 0o755], ofItemAtPath: executable.path)
        }

        let prefix = work.appendingPathComponent("prefix")
        let drive = prefix.appendingPathComponent("drive_c")
        let program = drive.appendingPathComponent("Program Files/Custom CAD/SLDWORKS.exe")
        let dosdevices = prefix.appendingPathComponent("dosdevices")
        try files.createDirectory(at: program.deletingLastPathComponent(), withIntermediateDirectories: true)
        try files.createDirectory(at: dosdevices, withIntermediateDirectories: true)
        try files.createSymbolicLink(atPath: dosdevices.appendingPathComponent("c:").path,
                                     withDestinationPath: "../drive_c")
        try files.createSymbolicLink(atPath: dosdevices.appendingPathComponent("z:").path,
                                     withDestinationPath: "/")
        try files.createSymbolicLink(atPath: dosdevices.appendingPathComponent("w:").path,
                                     withDestinationPath: work.path)
        try Data("MZ synthetic executable marker".utf8).write(to: program)
        let win = "Z:" + fonts.path.replacingOccurrences(of: "/", with: "\\\\") + "\\\\test.ttf"
        let original = "\"Font\"=\"\(win)\"\n\"Unrelated\"=\"keep\"\n"
        let registry = prefix.appendingPathComponent("system.reg")
        try original.write(to: registry, atomically: true, encoding: .utf8)

        let resources = URL(fileURLWithPath: CommandLine.arguments[1])
        let template = resources.appendingPathComponent("DesktopTemplate")
        let bridge = resources.appendingPathComponent("file-bridge.exe")
        let app = work.appendingPathComponent("SOLIDWORKS 2025.app")
        let selected = try WineRuntime(root: runtime)
        try selected.waitForIdle(prefix: prefix, timeout: 2)
        try DesktopPackage.assemble(template: template, runtime: selected, prefix: prefix,
                                    program: program, destination: app, bridge: bridge)
        let seed = app.appendingPathComponent("Contents/Resources/prefix-seed")
        let configuration = try String(contentsOf: app.appendingPathComponent("Contents/Resources/program-path.txt"),
                                       encoding: .utf8)
        let source = try String(contentsOf: registry, encoding: .utf8)
        let bundled = try String(contentsOf: seed.appendingPathComponent("system.reg"), encoding: .utf8)
        try expect(configuration == "Program Files/Custom CAD/SLDWORKS.exe\n", "custom installation path")
        try expect(source == original, "source prefix left intact")
        try expect(bundled == "\"Font\"=\"swv3-test.ttf\"\n\"Unrelated\"=\"keep\"\n", "font relocation")
        try expect(files.fileExists(atPath: seed.appendingPathComponent("drive_c/sw-v3/file-bridge.exe").path),
                   "file bridge attached")
        for alias in ["z:", "w:"] {
            try expect((try? files.destinationOfSymbolicLink(atPath: seed.appendingPathComponent("dosdevices/\(alias)").path)) == nil,
                       "external disk alias excluded")
        }
        do {
            try DesktopPackage.assemble(template: template, runtime: selected, prefix: prefix,
                                        program: program, destination: app, bridge: bridge)
            throw CocoaError(.fileWriteFileExists)
        } catch is SetupError {
            print("PASS existing destination rejected")
        }
        let outside = work.appendingPathComponent("SLDWORKS.exe")
        try Data("MZ outside".utf8).write(to: outside)
        try expect(DesktopPackage.programPath(outside, in: prefix) == nil, "outside executable rejected")
        try expect(!files.fileExists(atPath: app.appendingPathComponent("Contents/Resources/graphics-metal").path),
                   "stock runtime keeps the normal OpenGL profile")
        let metalApp = work.appendingPathComponent("Metal SOLIDWORKS.app")
        do {
            try DesktopPackage.assemble(template: template, runtime: selected, prefix: prefix,
                                        program: program, destination: metalApp, bridge: bridge, useMetal: true)
            throw CocoaError(.fileWriteFileExists)
        } catch is SetupError {
            try expect(!files.fileExists(atPath: metalApp.path), "incomplete Metal runtime leaves no package")
        }

        let unix = runtime.appendingPathComponent("lib/wine/x86_64-unix")
        let windows = runtime.appendingPathComponent("lib/wine/x86_64-windows")
        try files.createDirectory(at: unix, withIntermediateDirectories: true)
        try files.createDirectory(at: windows, withIntermediateDirectories: true)
        try files.copyItem(at: bin.appendingPathComponent("wine"), to: unix.appendingPathComponent("wine"))
        for name in ["winemetalgl.so", "libwinemetalgl.dylib"] {
            try Data("synthetic Metal host module".utf8).write(to: unix.appendingPathComponent(name))
        }
        try Data("swv3_metal_surfaces".utf8).write(to: unix.appendingPathComponent("winemac.so"))
        let pe = windows.appendingPathComponent("winemetalgl.dll")
        try Data("MZ synthetic WineMetalGL".utf8).write(to: pe)
        let local = program.deletingLastPathComponent()
        try files.copyItem(at: pe, to: local.appendingPathComponent("winemetalgl.dll"))
        try Data("MZ winemetalgl.wglCreateContext".utf8).write(to: local.appendingPathComponent("opengl32.dll"))
        let prepared = try WineRuntime(root: runtime)
        try expect(DesktopPackage.hasPreparedMetal(prepared, program: program), "matching prepared Metal runtime")
        try DesktopPackage.assemble(template: template, runtime: prepared, prefix: prefix,
                                    program: program, destination: metalApp, bridge: bridge, useMetal: true)
        try expect(files.fileExists(atPath: metalApp.appendingPathComponent("Contents/Resources/graphics-metal").path),
                   "prepared runtime receives the baseline Metal profile")
        try Data("MZ different DLL".utf8).write(to: local.appendingPathComponent("winemetalgl.dll"))
        try expect(!DesktopPackage.hasPreparedMetal(prepared, program: program), "mismatched WineMetalGL DLL rejected")
        print("PASS isolated OpenGL and prepared Metal packages assembled and verified")
    }
}
