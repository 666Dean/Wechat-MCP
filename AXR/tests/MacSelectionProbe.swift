// SPDX-License-Identifier: AGPL-3.0-only
// Owner-operated system picker qualification. Metadata only: no image, OCR,
// message body, credential, stream, network request or automation input.
import AppKit
import ScreenCaptureKit
import Darwin

@available(macOS 15.2, *)
final class SelectionProbe: NSObject, SCContentSharingPickerObserver {
    let bundle: String
    let pid: pid_t
    let picker = SCContentSharingPicker.shared
    var finished = false
    init(bundle: String, pid: pid_t) { self.bundle = bundle; self.pid = pid }
    func finish(_ fields: [String: Any], _ status: Int32 = 0) {
        guard !finished else { return }
        finished = true
        picker.remove(self); picker.isActive = false
        let value = fields.merging(["metadata_only": true, "content_read": false,
                                   "send_available": false]) { first, _ in first }
        if let bytes = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) {
            FileHandle.standardOutput.write(bytes); FileHandle.standardOutput.write(Data([10]))
        }
        exit(status)
    }
    func contentSharingPicker(_ picker: SCContentSharingPicker, didCancelFor stream: SCStream?) {
        finish(["selected": false, "reason": "owner_cancelled"])
    }
    func contentSharingPickerStartDidFailWithError(_ error: Error) {
        finish(["selected": false, "reason": "system_picker_failed", "error_code": (error as NSError).code], 1)
    }
    func contentSharingPicker(_ picker: SCContentSharingPicker, didUpdateWith filter: SCContentFilter, for stream: SCStream?) {
        guard stream == nil, filter.style == .window, filter.includedWindows.count == 1,
              let window = filter.includedWindows.first,
              let application = window.owningApplication,
              application.bundleIdentifier == bundle, application.processID == pid,
              NSRunningApplication(processIdentifier: pid)?.bundleIdentifier == bundle else {
            finish(["selected": false, "reason": "selection_scope_mismatch"], 1); return
        }
        let rows = CGWindowListCopyWindowInfo([.optionIncludingWindow], window.windowID) as? [[String: Any]] ?? []
        let sharing = rows.first?[kCGWindowSharingState as String] as? Int ?? -1
        finish(["selected": true, "single_window": true, "pid": Int(pid),
                "window_id": Int(window.windowID), "legacy_sharing_state": sharing,
                "filter_validated": true])
    }
    func start(timeout: TimeInterval) {
        var configuration = SCContentSharingPickerConfiguration()
        configuration.allowedPickerModes = [.singleWindow]
        configuration.allowsChangingSelectedContent = false
        configuration.excludedBundleIDs = Array(Set(NSWorkspace.shared.runningApplications.compactMap {
            $0.bundleIdentifier == bundle ? nil : $0.bundleIdentifier
        }))
        picker.defaultConfiguration = configuration; picker.maximumStreamCount = 1
        picker.add(self); picker.isActive = true
        Timer.scheduledTimer(withTimeInterval: timeout, repeats: false) { [self] _ in
            finish(["selected": false, "reason": "selection_timeout"], 1)
        }
        picker.present(using: .window)
    }
}

if #available(macOS 15.2, *) {
    let args = Array(CommandLine.arguments.dropFirst())
    guard args.count == 2, !args[0].isEmpty, args[0].utf8.count <= 256,
          let timeout = TimeInterval(args[1]), timeout.isFinite, timeout >= 1, timeout <= 180 else { exit(2) }
    let applications = NSRunningApplication.runningApplications(withBundleIdentifier: args[0])
    guard applications.count == 1, let application = applications.first else { exit(2) }
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    let probe = SelectionProbe(bundle: args[0], pid: application.processIdentifier)
    probe.start(timeout: timeout)
    app.run()
} else { exit(2) }
