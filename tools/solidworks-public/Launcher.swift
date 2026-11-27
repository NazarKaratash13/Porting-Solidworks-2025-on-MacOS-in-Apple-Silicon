import AppKit
import Darwin
import UniformTypeIdentifiers

final class Launcher: NSObject, NSApplicationDelegate {
    private let files = FileManager.default
    private let preferences = UserDefaults.standard
    private let label = "SOLIDWORKS V3"
    private var child: Process?
    private var busy = false
    private var window: NSWindow!
    private var status: NSTextField!
    private var action: NSButton!
    private var progress: NSProgressIndicator!
    private var stage: NSTextField!
    private var runtimeButton: NSButton!
    private var projectsButton: NSButton!
    private var metalOption: NSButton!

    private var support: URL { files.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0] }
    private var state: URL { support.appendingPathComponent("org.swv3.launcher", isDirectory: true) }
    private var prefix: URL { state.appendingPathComponent("prefix", isDirectory: true) }
    private var driveC: URL { prefix.appendingPathComponent("drive_c", isDirectory: true) }

    func applicationDidFinishLaunching(_ notification: Notification) {
        configureMenu()
        configureWindow()
        refresh()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil)
        return true
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard busy else { return .terminateNow }
        message("Installation or packaging in progress", "Wait for the task to finish in the SOLIDWORKS V3 window.")
        return .terminateCancel
    }

    private func configureMenu() {
        let menu = NSMenu()
        let root = NSMenuItem()
        let items = NSMenu(title: label)
        for (title, selector) in [
            ("Select Official setup.exe…", #selector(install)),
            ("Build Mac App…", #selector(assemble)),
            ("Choose Wine Runtime…", #selector(chooseRuntime)),
            ("Choose Projects Folder…", #selector(chooseWorkspace)),
            ("Open Setup Guide", #selector(openGuide)),
        ] {
            items.addItem(withTitle: title, action: selector, keyEquivalent: "").target = self
        }
        items.addItem(.separator())
        items.addItem(withTitle: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        root.submenu = items
        menu.addItem(root)
        NSApp.mainMenu = menu
    }

    private func configureWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 565, height: 390),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = label
        window.isReleasedWhenClosed = false
        window.center()

        let header = NSTextField(labelWithString: "SOLIDWORKS 2025")
        header.font = .systemFont(ofSize: 26, weight: .semibold)
        let detail = NSTextField(wrappingLabelWithString:
            "Build a Mac app from your official SOLIDWORKS installer and a compatible Wine runtime.")
        stage = NSTextField(labelWithString: "")
        stage.font = .systemFont(ofSize: 16, weight: .semibold)
        status = NSTextField(wrappingLabelWithString: "")
        status.textColor = .secondaryLabelColor
        progress = NSProgressIndicator()
        progress.style = .bar
        progress.isIndeterminate = true
        progress.isDisplayedWhenStopped = false
        progress.controlSize = .small
        action = NSButton(title: "", target: self, action: #selector(primary))
        action.bezelStyle = .rounded
        action.keyEquivalent = "\r"
        runtimeButton = NSButton(title: "Change Wine Runtime…", target: self, action: #selector(chooseRuntime))
        projectsButton = NSButton(title: "Projects Folder…", target: self, action: #selector(chooseWorkspace))
        let guide = NSButton(title: "Setup Guide", target: self, action: #selector(openGuide))
        let buttons = NSStackView(views: [runtimeButton, projectsButton, guide])
        buttons.spacing = 8
        metalOption = NSButton(checkboxWithTitle: "Use WineMetalGL when building the app",
                               target: self, action: #selector(changeGraphics))
        metalOption.toolTip = "Available when the runtime and SOLIDWORKS folder contain matching V3 graphics modules."

        let stack = NSStackView(views: [header, detail, stage, status, metalOption, progress, action, buttons])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        let content = window.contentView!
        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -28),
            stack.centerYAnchor.constraint(equalTo: content.centerYAnchor),
            detail.widthAnchor.constraint(equalTo: stack.widthAnchor),
            status.widthAnchor.constraint(equalTo: stack.widthAnchor),
            progress.widthAnchor.constraint(equalTo: stack.widthAnchor),
        ])
    }

    private func refresh() {
        action.isEnabled = !busy
        runtimeButton.isEnabled = !busy
        projectsButton.isEnabled = !busy
        guard !busy else {
            metalOption.isEnabled = false
            stage.stringValue = "Working…"
            progress.startAnimation(nil)
            return
        }
        progress.stopAnimation(nil)
        let runtime = savedRuntime()
        let program = installedProgram()
        let built = installedApp()
        let prepared = runtime.flatMap { wine in program.map { DesktopPackage.hasPreparedMetal(wine, program: $0) } } ?? false
        metalOption.isHidden = built != nil || program == nil || !prepared
        metalOption.isEnabled = prepared
        metalOption.state = preferences.object(forKey: "useMetal") as? Bool == false ? .off : .on
        runtimeButton.isHidden = runtime == nil
        if let built {
            stage.stringValue = "Ready to open"
            status.stringValue = "Your Mac app is saved in \(built.deletingLastPathComponent().path). Complete license activation in SOLIDWORKS if prompted."
            action.title = "Open SOLIDWORKS"
        } else if runtime == nil {
            stage.stringValue = "1 of 3 · Choose a Wine runtime"
            status.stringValue = "Select a compatible Wine folder. The setup guide shows which layout the launcher accepts."
            action.title = "Choose Wine Runtime…"
        } else if program == nil {
            stage.stringValue = "2 of 3 · Install SOLIDWORKS"
            status.stringValue = "Select setup.exe from your extracted official installation media, then finish in the Windows installer."
            action.title = "Select Setup.exe…"
        } else {
            stage.stringValue = "3 of 3 · Build your Mac app"
            status.stringValue = prepared
                ? "The prepared WineMetalGL runtime is available. Choose where to save your app."
                : "The selected runtime will use Wine’s OpenGL. Choose where to save your app."
            action.title = "Build Mac App…"
        }
    }

    @objc private func openGuide() {
        guard let url = URL(string: "https://github.com/NazarKaratash13/Porting-Solidworks-2025-on-MacOS-in-Apple-Silicon/blob/v0.3.0/docs/SETUP.md") else { return }
        NSWorkspace.shared.open(url)
    }

    @objc private func changeGraphics() {
        preferences.set(metalOption.state == .on, forKey: "useMetal")
    }

    private func installedApp() -> URL? {
        guard let url = preferences.url(forKey: "desktopApp"),
              files.isExecutableFile(atPath: url.appendingPathComponent("Contents/MacOS/SOLIDWORKS").path) else {
            return nil
        }
        return url
    }

    private func installedProgram() -> URL? {
        let defaults = [
            driveC.appendingPathComponent("Program Files/SOLIDWORKS Corp/SOLIDWORKS/SLDWORKS.exe"),
            driveC.appendingPathComponent("Program Files/SOLIDWORKS/SLDWORKS.exe"),
        ]
        let saved = preferences.url(forKey: "installedProgram").map { [$0] } ?? []
        return (saved + defaults).first { DesktopPackage.programPath($0, in: prefix) != nil }
    }

    private func chooseInstalledProgram() -> URL? {
        let panel = NSOpenPanel()
        panel.message = "Choose SLDWORKS.exe on this Wine prefix's C: drive."
        panel.directoryURL = driveC
        panel.allowedContentTypes = [UTType(filenameExtension: "exe") ?? .data]
        guard panel.runModal() == .OK, let url = panel.url else { return nil }
        guard DesktopPackage.programPath(url, in: prefix) != nil else {
            message("SOLIDWORKS path unavailable", "Choose SLDWORKS.exe inside the C: drive for this installation.")
            return nil
        }
        preferences.set(url, forKey: "installedProgram")
        return url
    }

    private func message(_ title: String, _ detail: String) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = detail
        alert.runModal()
    }

    private func directory(_ prompt: String, initial: URL? = nil) -> URL? {
        let panel = NSOpenPanel()
        panel.message = prompt
        panel.directoryURL = initial
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        return panel.runModal() == .OK ? panel.url : nil
    }

    private func savedRuntime() -> WineRuntime? {
        preferences.url(forKey: "wineRoot").flatMap { try? WineRuntime(root: $0) }
    }

    private func selectedRuntime() -> WineRuntime? {
        savedRuntime() ?? selectRuntime()
    }

    private func selectRuntime() -> WineRuntime? {
        guard !busy, let folder = directory("Choose a self-contained Wine folder with wine and wineserver.") else {
            return nil
        }
        do {
            let runtime = try WineRuntime(root: folder)
            preferences.set(folder, forKey: "wineRoot")
            return runtime
        } catch {
            message("Wine unavailable", error.localizedDescription)
            return nil
        }
    }

    @objc private func chooseRuntime() {
        guard selectRuntime() != nil else { return }
        refresh()
    }

    @objc private func chooseWorkspace() {
        guard !busy, let folder = directory("Choose the folder to expose to Wine as drive W:.") else { return }
        do {
            try mountWorkspace(folder)
            preferences.set(folder, forKey: "workspace")
        } catch {
            message("Projects folder unavailable", error.localizedDescription)
        }
    }

    private func mountWorkspace(_ folder: URL) throws {
        let drives = prefix.appendingPathComponent("dosdevices")
        try files.createDirectory(at: drives, withIntermediateDirectories: true)
        let drive = drives.appendingPathComponent("w:")
        if let existing = try? files.destinationOfSymbolicLink(atPath: drive.path) {
            if existing == folder.path { return }
            guard existing == preferences.url(forKey: "workspace")?.path else {
                throw CocoaError(.fileWriteFileExists)
            }
            let staged = drives.appendingPathComponent(UUID().uuidString)
            try files.createSymbolicLink(atPath: staged.path, withDestinationPath: folder.path)
            defer { try? files.removeItem(at: staged) }
            guard rename(staged.path, drive.path) == 0 else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
            }
        } else {
            try files.createSymbolicLink(atPath: drive.path, withDestinationPath: folder.path)
        }
    }

    @objc private func primary() {
        guard !busy else { return }
        if let url = installedApp() {
            NSWorkspace.shared.openApplication(at: url, configuration: .init()) { [weak self] _, error in
                guard let error else { return }
                DispatchQueue.main.async { self?.message("Could not open SOLIDWORKS", error.localizedDescription) }
            }
        } else if savedRuntime() == nil {
            chooseRuntime()
        } else if installedProgram() != nil {
            assemble()
        } else {
            install()
        }
    }

    @objc private func install() {
        guard !busy, let runtime = selectedRuntime() else { return }
        let panel = NSOpenPanel()
        panel.message = "Choose setup.exe from the official SOLIDWORKS installation media."
        panel.allowedContentTypes = [UTType(filenameExtension: "exe") ?? .data]
        guard panel.runModal() == .OK, let installer = panel.url else { return }
        guard installer.lastPathComponent.caseInsensitiveCompare("setup.exe") == .orderedSame else {
            message("Choose setup.exe", "Select the file from your extracted official installation media.")
            return
        }

        do {
            try files.createDirectory(at: state, withIntermediateDirectories: true,
                                      attributes: [.posixPermissions: 0o700])
            let process = Process()
            process.executableURL = runtime.loader
            process.arguments = [installer.path]
            process.currentDirectoryURL = installer.deletingLastPathComponent()
            process.environment = runtime.environment(prefix: prefix)
            process.terminationHandler = { [weak self] finished in
                let code = finished.terminationStatus
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.child = nil
                    if code == 0 {
                        self.waitForInstaller(runtime, build: false)
                    } else {
                        self.busy = false
                        self.refresh()
                        self.message("Installer exited with code \(code)",
                                     "Check the installer window. Once it finishes, choose Build Mac App.")
                    }
                }
            }
            try process.run()
            child = process
            busy = true
            status.stringValue = "Finish installing in the SOLIDWORKS installer window. The launcher will check the installation when the installer closes."
            refresh()
        } catch {
            message("Could not start the installer", error.localizedDescription)
        }
    }

    @objc private func assemble() {
        guard !busy, let runtime = selectedRuntime() else { return }
        waitForInstaller(runtime, build: true)
    }

    private func waitForInstaller(_ runtime: WineRuntime, build: Bool) {
        busy = true
        status.stringValue = "Checking whether the Wine installer finished…"
        refresh()
        let winePrefix = prefix
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result = Result { try runtime.waitForIdle(prefix: winePrefix) }
            DispatchQueue.main.async {
                guard let self else { return }
                self.busy = false
                self.refresh()
                switch result {
                case .success:
                    if build { self.package(runtime) }
                    else if self.installedProgram() == nil {
                        self.message("SOLIDWORKS was not found", "If installation completed, choose Build Mac App from the menu to locate SLDWORKS.exe.")
                    }
                case .failure(let error): self.message("Wine is still busy", error.localizedDescription)
                }
            }
        }
    }

    private func package(_ runtime: WineRuntime) {
        guard let program = installedProgram() ?? chooseInstalledProgram(),
              let resources = Bundle.main.resourceURL else { return }
        let systemApplications = URL(fileURLWithPath: "/Applications")
        guard let folder = directory("Choose where to save SOLIDWORKS 2025.app.", initial: systemApplications)
        else { return }
        let destination = folder.appendingPathComponent("SOLIDWORKS 2025.app")
        let template = resources.appendingPathComponent("DesktopTemplate")
        let bridgeFile = resources.appendingPathComponent("file-bridge.exe")
        let bridge = files.fileExists(atPath: bridgeFile.path) ? bridgeFile : nil
        let winePrefix = prefix
        let workspace = preferences.url(forKey: "workspace")
        let useMetal = DesktopPackage.hasPreparedMetal(runtime, program: program) &&
            preferences.object(forKey: "useMetal") as? Bool != false
        let desktop = support.appendingPathComponent("org.swv3.desktop")
        let desktopState = useMetal ? desktop.appendingPathComponent("metal") : desktop
        busy = true
        status.stringValue = "Building and verifying SOLIDWORKS 2025.app…"
        refresh()
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result = Result {
                try DesktopPackage.assemble(template: template, runtime: runtime, prefix: winePrefix,
                                            program: program, destination: destination, bridge: bridge, useMetal: useMetal)
                if let workspace, !workspace.path.contains("\n") {
                    try? FileManager.default.createDirectory(at: desktopState, withIntermediateDirectories: true,
                                                            attributes: [.posixPermissions: 0o700])
                    try? (workspace.path + "\n").write(to: desktopState.appendingPathComponent("workspace-path"),
                                                       atomically: true, encoding: .utf8)
                }
            }
            DispatchQueue.main.async {
                guard let self else { return }
                self.busy = false
                if case .success = result { self.preferences.set(destination, forKey: "desktopApp") }
                self.refresh()
                if case .failure(let error) = result {
                    self.message("Could not build the app", error.localizedDescription)
                }
            }
        }
    }
}

@main
struct LauncherMain {
    static func main() {
        let app = NSApplication.shared
        let delegate = Launcher()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        app.run()
    }
}
