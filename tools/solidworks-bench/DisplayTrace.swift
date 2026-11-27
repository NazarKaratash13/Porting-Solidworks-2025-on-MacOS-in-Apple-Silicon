import AppKit
import CoreGraphics
import CoreImage
import CoreMedia
import CoreVideo
import Foundation
import ImageIO
import ScreenCaptureKit
import UniformTypeIdentifiers

final class Capture: NSObject, SCStreamOutput {
    private let file: FileHandle
    private let evidenceDirectory: URL?
    private let imageContext: CIContext?
    private var previous: UInt64?
    private var lastEvidenceStamp: UInt64 = 0
    private var timebase = mach_timebase_info_data_t()

    init(file: FileHandle, evidenceDirectory: URL?) {
        self.file = file
        self.evidenceDirectory = evidenceDirectory
        imageContext = evidenceDirectory.map { _ in CIContext(options: [.useSoftwareRenderer: true]) }
        mach_timebase_info(&timebase)
    }

    private func saveEvidence(_ pixels: CVPixelBuffer, at stamp: UInt64) {
        guard stamp > lastEvidenceStamp + 400_000_000,
              let evidenceDirectory, let imageContext else { return }
        lastEvidenceStamp = stamp
        let source = CIImage(cvPixelBuffer: pixels)
        let file = evidenceDirectory.appendingPathComponent("\(stamp).png")
        guard let image = imageContext.createCGImage(source, from: source.extent),
              let output = CGImageDestinationCreateWithURL(file as CFURL, UTType.png.identifier as CFString,
                                                           1, nil) else { return }
        CGImageDestinationAddImage(output, image, nil)
        CGImageDestinationFinalize(output)
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer,
                of type: SCStreamOutputType) {
        guard type == .screen,
              let frames = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: false)
                as? [[SCStreamFrameInfo: Any]], let frame = frames.first,
              let status = frame[.status] as? Int,
              status == SCFrameStatus.complete.rawValue,
              let display = frame[.displayTime] as? NSNumber,
              let pixels = sample.imageBuffer,
              CVPixelBufferLockBaseAddress(pixels, .readOnly) == kCVReturnSuccess
        else { return }
        defer { CVPixelBufferUnlockBaseAddress(pixels, .readOnly) }
        guard let raw = CVPixelBufferGetBaseAddress(pixels) else { return }
        let width = CVPixelBufferGetWidth(pixels)
        let height = CVPixelBufferGetHeight(pixels)
        let stride = CVPixelBufferGetBytesPerRow(pixels)
        var hash: UInt64 = 0xcbf29ce484222325
        for y in Swift.stride(from: height / 5, to: height * 4 / 5, by: 5) {
            for x in Swift.stride(from: width / 5, to: width * 4 / 5, by: 5) {
                let pixel = raw.load(fromByteOffset: y * stride + 4 * x, as: UInt32.self)
                hash = (hash ^ UInt64(pixel & 0x00fcfcfc)) &* 0x100000001b3
            }
        }
        guard hash != previous else { return }
        previous = hash
        guard timebase.denom > 0 else { return }
        let displayNs = display.uint64Value.multipliedFullWidth(by: UInt64(timebase.numer))
        let absoluteNs = UInt64(timebase.denom).dividingFullWidth(displayNs).quotient
        let continuous = clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW)
        let uptime = clock_gettime_nsec_np(CLOCK_UPTIME_RAW)
        if continuous >= uptime {
            let stamp = absoluteNs + continuous - uptime
            file.write(Data("\(stamp)\n".utf8))
            saveEvidence(pixels, at: stamp)
        }
    }
}

@main struct DisplayTrace {
    @MainActor static func main() async throws {
        let args = CommandLine.arguments
        guard args.count == 4 || (args.count == 6 && args[4] == "--evidence"),
              let pid = pid_t(args[1]), let seconds = Int(args[2]),
              (1...600).contains(seconds) else {
            FileHandle.standardError.write(Data("Usage: display-trace PID SECONDS NEW-TRACE [--evidence DIRECTORY]\n".utf8))
            exit(2)
        }
        let evidenceDirectory = args.count == 6 ? URL(fileURLWithPath: args[5], isDirectory: true) : nil
        if let evidenceDirectory {
            try FileManager.default.createDirectory(at: evidenceDirectory, withIntermediateDirectories: false)
        }
        NSApplication.shared.setActivationPolicy(.prohibited)
        _ = CGMainDisplayID()
        guard CGPreflightScreenCaptureAccess() else { exit(5) }
        let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: false)
        let area = { (window: SCWindow) in window.frame.width * window.frame.height }
        guard let window = content.windows.filter({ $0.owningApplication?.processID == pid && $0.windowLayer == 0 })
            .max(by: { area($0) < area($1) }) else { exit(3) }
        let fd = open(args[3], O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0o600)
        guard fd >= 0 else { exit(4) }
        let file = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        let recorder = Capture(file: file, evidenceDirectory: evidenceDirectory)
        let config = SCStreamConfiguration()
        config.width = evidenceDirectory == nil ? 640 : 1280
        config.height = max(2, Int(Double(config.width) * window.frame.height / window.frame.width) / 2 * 2)
        config.minimumFrameInterval = CMTime(value: 1, timescale: 60)
        config.pixelFormat = kCVPixelFormatType_32BGRA
        config.showsCursor = false
        config.queueDepth = 3
        let stream = SCStream(filter: SCContentFilter(desktopIndependentWindow: window),
                              configuration: config, delegate: nil)
        try stream.addStreamOutput(recorder, type: .screen,
                                   sampleHandlerQueue: DispatchQueue(label: "org.swv3.display-trace"))
        try await stream.startCapture()
        print("Recording changed window frames for PID \(pid).")
        try await Task.sleep(nanoseconds: UInt64(seconds) * 1_000_000_000)
        try await stream.stopCapture()
    }
}
