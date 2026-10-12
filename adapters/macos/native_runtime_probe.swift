// SPDX-License-Identifier: MIT
// Local metadata eligibility only. No memory read, attach, suspend, native call,
// write port, account identifier, screen capture, credentials or authority grant.
import AppKit
import Darwin
import Security

func report(_ value: [String: Any], exitCode: Int32 = 0) -> Never {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
    exit(exitCode)
}

let installedExecutable = "/Applications/WeChat.app/Contents/MacOS/WeChat"
let candidates = NSRunningApplication.runningApplications(withBundleIdentifier: "com.tencent.xinWeChat")
    .filter { $0.executableURL?.path == installedExecutable }
guard candidates.count == 1 else {
    report(["error": "running_process_not_unique"], exitCode: 1)
}
let pid = candidates[0].processIdentifier
var code: SecCode?
let attributes = [kSecGuestAttributePid as String: NSNumber(value: pid)] as CFDictionary
let found = SecCodeCopyGuestWithAttributes(nil, attributes, [], &code)
var requirement: SecRequirement?
let rule = "anchor apple generic and identifier \"com.tencent.xinWeChat\" and certificate leaf[subject.OU] = \"5A4RE8SF68\""
guard SecRequirementCreateWithString(rule as CFString, [], &requirement) == errSecSuccess,
      found == errSecSuccess, let code = code, let requirement = requirement,
      SecCodeCheckValidity(code, [], requirement) == errSecSuccess else {
    report(["error": "running_vendor_identity_unqualified"], exitCode: 1)
}

// libsystem_kernel exports the read-only port API; Swift's Darwin module does
// not declare it. This signature takes target_task, pid, and task-read-port out.
typealias ReadPort = @convention(c) (mach_port_name_t, Int32, UnsafeMutablePointer<mach_port_name_t>) -> Int32
guard let symbol = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "task_read_for_pid") else {
    report(["error": "read_port_api_unavailable"], exitCode: 1)
}
let acquire = unsafeBitCast(symbol, to: ReadPort.self)
var port: mach_port_name_t = 0
errno = 0
let status = acquire(mach_task_self_, pid, &port)
let apiErrno = errno
// Release immediately even on an unexpected error; never use the port to read.
if port != 0 { mach_port_deallocate(mach_task_self_, port) }
report(["running_vendor_verified": true, "read_port_available": status == 0 && port != 0,
        "api_status": status, "errno": apiErrno,
        "runtime_identity_verified": false, "runtime_recipient_verified": false,
        "memory_read": false, "native_call": false, "native_send_available": false],
       exitCode: status == 0 && port != 0 ? 0 : 1)
