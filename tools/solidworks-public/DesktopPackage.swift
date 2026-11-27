import Foundation

struct WineRuntime: Sendable {
    let root: URL
    let loader: URL
    let server: URL
    let crossOverLayout: Bool

    init(root: URL, files: FileManager = .default) throws {
        self.root = root.resolvingSymlinksInPath()
        let crossOver = self.root.appendingPathComponent("lib/wine/x86_64-unix/wine")
        crossOverLayout = files.isExecutableFile(atPath: crossOver.path)
        loader = crossOverLayout ? crossOver : self.root.appendingPathComponent("bin/wine")
        server = self.root.appendingPathComponent("bin/wineserver")
        guard files.isExecutableFile(atPath: loader.path),
              files.isExecutableFile(atPath: server.path) else {
            throw SetupError("Choose a Wine directory with executable wine and wineserver programs.")
        }
    }

    func environment(prefix: URL) -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["WINEPREFIX"] = prefix.path
        env["WINEDEBUG"] = "-all"
        if crossOverLayout { env["CX_ROOT"] = root.path }
        env["PATH"] = root.appendingPathComponent("bin").path + ":" + (env["PATH"] ?? "/usr/bin:/bin")
        return env
    }

    func waitForIdle(prefix: URL, timeout: TimeInterval = 90) throws {
        let process = Process()
        process.executableURL = server
        process.arguments = ["-w"]
        process.environment = environment(prefix: prefix)
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        let completed = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in completed.signal() }
        try process.run()
        guard completed.wait(timeout: .now() + timeout) == .success else {
            process.terminate() // The waiting process only. The installer is left running.
            throw SetupError("The installer is still running. Wait for it to finish, then choose Build Mac App again.")
        }
        guard process.terminationStatus == 0 else {
            throw SetupError("Could not verify that the Wine installer finished.")
        }
    }
}

struct SetupError: LocalizedError {
    let errorDescription: String?
    init(_ message: String) { errorDescription = message }
}

enum DesktopPackage {
    static func programPath(_ file: URL, in prefix: URL) -> String? {
        let drive = prefix.appendingPathComponent("drive_c").resolvingSymlinksInPath().path + "/"
        let program = file.resolvingSymlinksInPath()
        guard program.path.hasPrefix(drive), !program.path.contains("\n"),
              program.lastPathComponent.caseInsensitiveCompare("SLDWORKS.exe") == .orderedSame,
              (try? program.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true,
              FileManager.default.isReadableFile(atPath: program.path) else { return nil }
        return String(program.path.dropFirst(drive.count))
    }

    static func hasPreparedMetal(_ runtime: WineRuntime, program: URL) -> Bool {
        let files = FileManager.default
        let unix = runtime.root.appendingPathComponent("lib/wine/x86_64-unix")
        let pe = runtime.root.appendingPathComponent("lib/wine/x86_64-windows/winemetalgl.dll")
        let local = program.deletingLastPathComponent()
        guard runtime.crossOverLayout,
              files.isReadableFile(atPath: pe.path),
              files.contentsEqual(atPath: pe.path, andPath: local.appendingPathComponent("winemetalgl.dll").path),
              ["winemetalgl.so", "libwinemetalgl.dylib"].allSatisfy({
                  files.isReadableFile(atPath: unix.appendingPathComponent($0).path)
              }) else { return false }
        let forwarder = try? Data(contentsOf: local.appendingPathComponent("opengl32.dll"), options: .mappedIfSafe)
        let driver = try? Data(contentsOf: unix.appendingPathComponent("winemac.so"), options: .mappedIfSafe)
        return forwarder?.range(of: Data("winemetalgl.wglCreateContext".utf8)) != nil
            && driver?.range(of: Data("swv3_metal_surfaces".utf8)) != nil
    }

    static func assemble(template: URL, runtime: WineRuntime, prefix: URL,
                         program: URL, destination: URL, bridge: URL?, useMetal: Bool = false) throws {
        let files = FileManager.default
        let output = destination.path
        let parent = destination.deletingLastPathComponent().resolvingSymlinksInPath()
        guard destination.pathExtension == "app",
              !files.fileExists(atPath: output), (try? files.destinationOfSymbolicLink(atPath: output)) == nil else {
            throw SetupError("Choose a folder that does not already contain SOLIDWORKS 2025.app.")
        }
        guard let relative = programPath(program, in: prefix),
              files.fileExists(atPath: prefix.appendingPathComponent("system.reg").path) else {
            throw SetupError("This Wine prefix does not contain a complete SOLIDWORKS installation.")
        }
        if useMetal && !hasPreparedMetal(runtime, program: program) {
            throw SetupError("The selected runtime and installation do not contain matching WineMetalGL files. See the setup guide.")
        }
        for input in [runtime.root, prefix.resolvingSymlinksInPath()] {
            guard parent.path != input.path, !parent.path.hasPrefix(input.path + "/") else {
                throw SetupError("Choose a destination outside the Wine directories.")
            }
        }

        let staging = parent.appendingPathComponent(".swv3-\(UUID().uuidString)", isDirectory: true)
        try files.createDirectory(at: staging, withIntermediateDirectories: false,
                                  attributes: [.posixPermissions: 0o700])
        defer { try? files.removeItem(at: staging) }
        let app = staging.appendingPathComponent(destination.lastPathComponent)
        try files.copyItem(at: template, to: app)
        let resources = app.appendingPathComponent("Contents/Resources")
        let bundledRuntime = resources.appendingPathComponent("runtime")
        let seed = resources.appendingPathComponent("prefix-seed")
        try copyTree(runtime.root, to: bundledRuntime)
        try copyTree(prefix, to: seed)
        for name in ["z:", "w:"] {
            let drive = seed.appendingPathComponent("dosdevices/\(name)")
            if (try? files.destinationOfSymbolicLink(atPath: drive.path)) != nil {
                try files.removeItem(at: drive)
            }
        }
        try verifyLinks(in: bundledRuntime, removeUserFolderLinks: false)
        try verifyLinks(in: seed, removeUserFolderLinks: true)
        try relocateFonts(from: runtime.root, into: seed)
        if let bridge {
            let directory = seed.appendingPathComponent("drive_c/sw-v3")
            try files.createDirectory(at: directory, withIntermediateDirectories: true)
            let destination = directory.appendingPathComponent("file-bridge.exe")
            if files.fileExists(atPath: destination.path) { try files.removeItem(at: destination) }
            try files.copyItem(at: bridge, to: destination)
        }
        try (relative + "\n").write(to: resources.appendingPathComponent("program-path.txt"),
                                      atomically: true, encoding: .utf8)
        if useMetal {
            try Data().write(to: resources.appendingPathComponent("graphics-metal"))
        }
        try run("/usr/bin/codesign", ["--sign", "-", app.path])
        try run("/usr/bin/codesign", ["--verify", "--strict", app.path])
        try files.moveItem(at: app, to: destination)
    }

    private static func copyTree(_ source: URL, to destination: URL) throws {
        do {
            try run("/bin/cp", ["-cR", source.path, destination.path])
        } catch {
            if FileManager.default.fileExists(atPath: destination.path) {
                try FileManager.default.removeItem(at: destination)
            }
            try run("/bin/cp", ["-R", source.path, destination.path])
        }
    }

    private static func relocateFonts(from runtime: URL, into prefix: URL) throws {
        let files = FileManager.default
        let fonts = runtime.appendingPathComponent("share/wine/fonts")
        let windowsPath = "Z:" + fonts.path.replacingOccurrences(of: "/", with: "\\\\") + "\\\\"
        let pattern = "(?m)^(\\\"[^\\r\\n]+\\\"=\\\")"
            + NSRegularExpression.escapedPattern(for: windowsPath) + "([A-Za-z0-9_@.-]+)\\\"$"
        let expression = try NSRegularExpression(pattern: pattern)
        let windowsFonts = prefix.appendingPathComponent("drive_c/windows/Fonts")
        for name in ["system.reg", "user.reg"] {
            let registry = prefix.appendingPathComponent(name)
            guard files.fileExists(atPath: registry.path) else { continue }
            let contents = try String(contentsOf: registry, encoding: .utf8)
            let updated = NSMutableString(string: contents)
            let range = NSRange(contents.startIndex..., in: contents)
            let matches = expression.matches(in: contents, range: range)
            guard !matches.isEmpty else { continue }
            try files.createDirectory(at: windowsFonts, withIntermediateDirectories: true)
            for match in matches.reversed() {
                let name = updated.substring(with: match.range(at: 2))
                guard name != ".", name != ".." else { throw SetupError("Invalid Wine font name.") }
                let source = fonts.appendingPathComponent(name)
                let target = windowsFonts.appendingPathComponent("swv3-\(name)")
                if files.fileExists(atPath: target.path) {
                    guard files.contentsEqual(atPath: source.path, andPath: target.path) else {
                        throw SetupError("A Wine font already uses this name.")
                    }
                } else {
                    try files.copyItem(at: source, to: target)
                }
                let key = updated.substring(with: match.range(at: 1))
                updated.replaceCharacters(in: match.range, with: key + target.lastPathComponent + "\"")
            }
            try (updated as String).write(to: registry, atomically: true, encoding: .utf8)
        }
    }

    private static func verifyLinks(in root: URL, removeUserFolderLinks: Bool) throws {
        let files = FileManager.default
        let resolved = root.resolvingSymlinksInPath().path + "/"
        guard let entries = files.enumerator(at: root, includingPropertiesForKeys: [.isSymbolicLinkKey]) else {
            throw SetupError("Could not verify the app's input files.")
        }
        for case let entry as URL in entries {
            guard try entry.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink == true else { continue }
            let relative = String(entry.path.dropFirst(root.path.count + 1))
            let link = try files.destinationOfSymbolicLink(atPath: entry.path)
            if !link.hasPrefix("/"), entry.resolvingSymlinksInPath().path.hasPrefix(resolved) { continue }
            let parts = relative.split(separator: "/")
            if removeUserFolderLinks, parts.count == 4, parts[0] == "drive_c", parts[1] == "users",
               ["Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos"].contains(String(parts[3])) {
                try files.removeItem(at: entry)
                try files.createDirectory(at: entry, withIntermediateDirectories: false)
                continue
            }
            throw SetupError("The Wine runtime must be self-contained. Found an external symbolic link at \(relative).")
        }
    }

    private static func run(_ executable: String, _ args: [String]) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = args
        process.standardOutput = FileHandle.nullDevice
        let log = Pipe()
        process.standardError = log
        try process.run()
        let detail = String(data: log.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            throw SetupError("Command failed: \(URL(fileURLWithPath: executable).lastPathComponent) (\(process.terminationStatus)). \(detail)")
        }
    }
}
