import AppKit
import UniformTypeIdentifiers

@main
struct SolidworksV3Defaults {
    static func main() async {
        let arguments = CommandLine.arguments.dropFirst()
        guard let appPath = arguments.first, arguments.count <= 2 else {
            print("Usage: set-solidworks-v3-defaults /path/to/SOLIDWORKS.app [--check]")
            exit(2)
        }
        let app = URL(fileURLWithPath: appPath).standardizedFileURL
        guard Bundle(url: app)?.bundleIdentifier == "local.solidworks2025.v3resize" else {
            print("Expected the SOLIDWORKS 2025 V3 bundle.")
            exit(2)
        }
        let checkOnly = arguments.last == "--check"
        var failed = false
        for suffix in ["sldprt", "sldasm", "slddrw"] {
            guard let type = UTType(filenameExtension: suffix), !type.isDynamic else {
                print(".\(suffix): LaunchServices has no registered content type.")
                failed = true
                continue
            }
            do {
                let workspace = NSWorkspace.shared
                if !checkOnly, workspace.urlForApplication(toOpen: type)?.standardizedFileURL != app {
                    try await workspace.setDefaultApplication(at: app, toOpen: type)
                }
                let selected = workspace.urlForApplication(toOpen: type)?.standardizedFileURL
                print(".\(suffix): \(selected?.path ?? "no default application")")
                failed = failed || selected != app
            } catch {
                print(".\(suffix): \(error.localizedDescription)")
                failed = true
            }
        }
        exit(failed ? 1 : 0)
    }
}
