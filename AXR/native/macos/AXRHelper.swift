// SPDX-License-Identifier: AGPL-3.0-only
// Generic AX broker. Application-specific selectors and parsing belong to integrators.
import Foundation
import AppKit
import ApplicationServices
import LocalAuthentication

func attr(_ node: AXUIElement, _ key: String) -> Any? {
    var result: CFTypeRef?
    guard AXUIElementCopyAttributeValue(node, key as CFString, &result) == .success else { return nil }
    return result
}
func children(_ node: AXUIElement) -> [AXUIElement] {
    return attr(node, kAXChildrenAttribute) as? [AXUIElement] ?? []
}
func string(_ node: AXUIElement, _ key: String) -> String { return attr(node, key) as? String ?? "" }
func value(_ node: AXUIElement) -> String {
    for key in [kAXValueAttribute, kAXTitleAttribute, kAXDescriptionAttribute] {
        let v = string(node, key)
        if !v.isEmpty { return v }
    }
    return ""
}
func path(_ root: AXUIElement, _ parts: [Int]) throws -> AXUIElement {
    var node = root
    for index in parts {
        let c = children(node)
        guard index >= 0 && index < c.count else { throw Failure("selector_changed") }
        node = c[index]
    }
    return node
}
struct Failure: Error { let code: String; init(_ code: String) { self.code = code } }
func output(_ object: [String:Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]),
       let text = String(data: data, encoding: .utf8) { print(text) }
}
func main() throws -> [String:Any] {
    guard let line = readLine(), line.utf8.count <= 524288,
          let req = try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String:Any],
          let op = req["op"] as? String else { throw Failure("bad_request") }
    if op == "owner_auth" {
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            throw Failure("owner_auth_unavailable")
        }
        let semaphore = DispatchSemaphore(value: 0)
        var verified = false
        context.evaluatePolicy(.deviceOwnerAuthentication,
            localizedReason: "Authorize the exact AXR operation shown in your local owner terminal.") { success, _ in
            verified = success
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now()+60) == .success, verified else { throw Failure("owner_auth_denied") }
        return ["verified":true]
    }
    guard let bundle = req["bundle"] as? String, !bundle.isEmpty else { throw Failure("bundle_required") }
    let apps = NSRunningApplication.runningApplications(withBundleIdentifier: bundle)
    if op == "status" {
        return ["accessibility":AXIsProcessTrusted(), "running":apps.count == 1,
                "ambiguous_process":apps.count > 1, "pid":apps.first?.processIdentifier ?? 0]
    }
    guard AXIsProcessTrusted() else { throw Failure("accessibility_permission_required") }
    guard apps.count == 1 else { throw Failure("application_missing_or_ambiguous") }
    let app = apps[0], root = AXUIElementCreateApplication(app.processIdentifier)
    AXUIElementSetMessagingTimeout(root, 3)
    if let expectedPID = req["expected_pid"] as? Int, expectedPID != Int(app.processIdentifier) {
        throw Failure("application_epoch_changed")
    }
    if op == "enable_accessibility" {
        let enhanced = AXUIElementSetAttributeValue(root,"AXEnhancedUserInterface" as CFString,kCFBooleanTrue)
        let manual = AXUIElementSetAttributeValue(root,"AXManualAccessibility" as CFString,kCFBooleanTrue)
        return ["enhanced_result":enhanced.rawValue,"manual_result":manual.rawValue]
    }
    if op == "debug_capability" {
        // Capability probe only, no memory reads. Never disable platform protections.
        var task: mach_port_t = 0
        let code = task_for_pid(mach_task_self_, app.processIdentifier, &task)
        if code == KERN_SUCCESS { mach_port_deallocate(mach_task_self_,task) }
        return ["debug_access":code == KERN_SUCCESS,"kernel_result":code,"memory_read":false]
    }
    if op == "structure" {
        // No general UI text dump: exact owner-authorized labels only.
        let labels = Set(req["allow_labels"] as? [String] ?? [])
        var records: [[String:Any]] = []
        func walk(_ n: AXUIElement, _ p: [Int], _ depth: Int) {
            guard records.count < 1500, depth <= 16 else { return }
            let c = children(n), v = value(n)
            var item: [String:Any] = ["path":p, "role":string(n,kAXRoleAttribute), "children":c.count,
                "identifier":string(n,kAXIdentifierAttribute)]
            if labels.contains(v) { item["authorized_label"] = v }
            records.append(item)
            for (i,ch) in c.enumerated() { walk(ch,p+[i],depth+1) }
        }
        walk(root,[],0)
        return ["nodes":records, "pid":app.processIdentifier, "text_redacted":true]
    }
    guard let headerPath = req["header_path"] as? [Int], let expected = req["expected_title"] as? String,
          !expected.isEmpty, let targetPath = req["path"] as? [Int] else { throw Failure("scope_required") }
    func verify() throws {
        let header = try path(root,headerPath)
        guard value(header) == expected else { throw Failure("target_identity_changed") }
        if op == "send_text" || op == "read" {
            guard let accountPath = req["account_path"] as? [Int],
                  let identityPath = req["identity_path"] as? [Int],
                  let account = req["expected_account"] as? String,
                  let identity = req["expected_identity"] as? String,
                  !account.isEmpty, !identity.isEmpty,
                  value(try path(root,accountPath)) == account,
                  value(try path(root,identityPath)) == identity else {
                throw Failure("stable_identity_unavailable_or_changed")
            }
        }
    }
    try verify()
    let target = try path(root,targetPath)
    if op == "send_text" {
        guard let text = req["text"] as? String, !text.isEmpty, text.count <= 16000,
              let sendPath = req["send_path"] as? [Int],
              let messagesPath = req["messages_path"] as? [Int] else { throw Failure("send_parameters_required") }
        guard value(target).isEmpty else { throw Failure("existing_draft_denied") }
        func matches(_ node: AXUIElement, _ depth: Int) -> Int {
            if depth>12 { return 0 }
            return (value(node)==text ? 1 : 0) + children(node).prefix(500).reduce(0) { $0+matches($1,depth+1) }
        }
        let before = matches(try path(root,messagesPath),0)
        try verify()
        guard AXUIElementSetAttributeValue(target,kAXValueAttribute as CFString,text as CFString) == .success,
              value(target) == text else { throw Failure("draft_prepare_failed") }
        try verify()
        let send = try path(root,sendPath)
        guard AXUIElementPerformAction(send,kAXPressAction as CFString) == .success else {
            throw Failure("send_action_unavailable")
        }
        let deadline=Date().addingTimeInterval(2)
        while Date()<deadline {
            try verify()
            let messages = try path(root,messagesPath)
            if value(target).isEmpty && matches(messages,0)>before {
                return ["verified":true,"witness":"new_client_bubble_and_empty_draft","delivery_confirmed":false]
            }
            RunLoop.current.run(until:Date().addingTimeInterval(0.05))
        }
        return ["verified":false,"invoked":true,"delivery_confirmed":false]
    }
    if op == "read" {
        var records: [[String:Any]] = []
        func walk(_ n: AXUIElement, _ p: [Int], _ depth: Int) {
            guard records.count < 500, depth <= 12 else { return }
            records.append(["path":p, "role":string(n,kAXRoleAttribute), "value":String(value(n).prefix(16000)),
                "identifier":string(n,kAXIdentifierAttribute), "description":string(n,kAXDescriptionAttribute)])
            for (i,ch) in children(n).enumerated() { walk(ch,p+[i],depth+1) }
        }
        walk(target,targetPath,0)
        try verify()
        return ["nodes":records, "pid":app.processIdentifier,
                "foreground":NSWorkspace.shared.frontmostApplication?.processIdentifier == app.processIdentifier]
    }
    if op == "set_value" {
        guard let text = req["text"] as? String, text.count <= 16000 else { throw Failure("text_required") }
        guard value(target).isEmpty else { throw Failure("existing_draft_denied") }
        try verify()
        guard AXUIElementSetAttributeValue(target,kAXValueAttribute as CFString,text as CFString) == .success else {
            throw Failure("value_not_settable")
        }
        try verify()
        return ["prepared":true, "sent":false]
    }
    if op == "press" {
        // Integrator must provide stable-identity proof, approval and draft checks before this commit.
        try verify()
        guard AXUIElementPerformAction(target,kAXPressAction as CFString) == .success else {
            throw Failure("action_unavailable")
        }
        try verify()
        return ["invoked":true, "delivery_confirmed":false]
    }
    throw Failure("unknown_operation")
}
do { output(try main()) } catch let failure as Failure { output(["error":failure.code]) }
catch { output(["error":"native_helper_failed"]) }
