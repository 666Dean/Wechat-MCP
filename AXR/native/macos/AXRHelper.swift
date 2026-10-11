// SPDX-License-Identifier: AGPL-3.0-only
// Generic AX broker. Application-specific selectors and parsing belong to integrators.
import Foundation
import AppKit
import ApplicationServices
import LocalAuthentication
import AXRCommit

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
func inputValue(_ node: AXUIElement) throws -> String {
    // Empty AXValue is valid. A title/description is not evidence of a draft.
    guard let text=attr(node,kAXValueAttribute) as? String else { throw Failure("draft_value_unavailable") }
    return text
}
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
        var result: [String:Any] = ["accessibility":AXIsProcessTrusted(), "running":apps.count == 1,
                "ambiguous_process":apps.count > 1, "pid":apps.first?.processIdentifier ?? 0,
                "foreground":apps.count == 1 && apps[0].isActive]
        if apps.count == 1 && AXIsProcessTrusted() {
            let root = AXUIElementCreateApplication(apps[0].processIdentifier)
            AXUIElementSetMessagingTimeout(root, 3)
            if let windows=attr(root,kAXWindowsAttribute) as? [AXUIElement], !windows.isEmpty {
                let flags=windows.compactMap { attr($0,kAXMinimizedAttribute) as? Bool }
                if flags.count==windows.count { result["all_windows_minimized"]=flags.allSatisfy {$0} }
            }
        }
        return result
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
    if op == "capabilities" {
        // Window health excludes menu search fields; never ask for content.
        var visited = 0, editable = 0, text = 0, truncated = false
        var errors: [String:Int] = [:]
        func metadata(_ node: AXUIElement, _ key: String) -> CFTypeRef? {
            var result: CFTypeRef?
            let code = AXUIElementCopyAttributeValue(node,key as CFString,&result)
            if code != .success { errors[String(code.rawValue),default:0] += 1; return nil }
            return result
        }
        func walk(_ node: AXUIElement, _ depth: Int) {
            guard visited < 1500, depth <= 16 else { truncated = true; return }
            visited += 1
            let role = metadata(node,kAXRoleAttribute) as? String ?? ""
            if ["AXTextArea","AXTextField","AXComboBox"].contains(role) { editable += 1 }
            if role == "AXStaticText" { text += 1 }
            let descendants = metadata(node,kAXChildrenAttribute) as? [AXUIElement] ?? []
            for child in descendants { walk(child,depth+1) }
        }
        let windows = metadata(root,kAXWindowsAttribute) as? [AXUIElement]
        if let windows { for window in windows { walk(window,0) } }
        else { truncated = true }
        return ["pid":app.processIdentifier,"nodes_visited":visited,"editable_nodes":editable,
            "text_nodes":text,"window_count":windows?.count ?? 0,"scope":"application_windows",
            "truncated":truncated,"attribute_errors":errors,"content_read":false]
    }
    if op == "structure" {
        // Selector metadata only. Redacting after fetching text is insufficient.
        var records: [[String:Any]] = []
        func walk(_ n: AXUIElement, _ p: [Int], _ depth: Int) {
            guard records.count < 1500, depth <= 16 else { return }
            let c = children(n)
            let item: [String:Any] = ["path":p, "role":string(n,kAXRoleAttribute), "children":c.count,
                "identifier":string(n,kAXIdentifierAttribute)]
            records.append(item)
            for (i,ch) in c.enumerated() { walk(ch,p+[i],depth+1) }
        }
        walk(root,[],0)
        return ["nodes":records, "pid":app.processIdentifier, "text_redacted":true]
    }
    guard let headerPath = req["header_path"] as? [Int], let expected = req["expected_title"] as? String,
          !expected.isEmpty, let targetPath = req["path"] as? [Int] else { throw Failure("scope_required") }
    func verify() throws {
        guard let control=req["guard_context"] as? [String:String],let store=control["store"],let proof=control["proof"],
              store.withCString({ p in proof.withCString({ q in axr_check_commit(p,q) }) })==1 else {
            throw Failure("authority_changed_or_commit_proof_missing")
        }
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
        guard try inputValue(target).isEmpty else { throw Failure("existing_draft_denied") }
        func matches(_ node: AXUIElement, _ depth: Int) -> Int {
            if depth>12 { return 0 }
            return (value(node)==text ? 1 : 0) + children(node).prefix(500).reduce(0) { $0+matches($1,depth+1) }
        }
        let before = matches(try path(root,messagesPath),0)
        try verify()
        guard AXUIElementSetAttributeValue(target,kAXValueAttribute as CFString,text as CFString) == .success,
              try inputValue(target) == text else { throw Failure("draft_prepare_failed") }
        try verify()
        let send = try path(root,sendPath)
        guard AXUIElementPerformAction(send,kAXPressAction as CFString) == .success else {
            throw Failure("send_action_unavailable")
        }
        let deadline=Date().addingTimeInterval(2)
        while Date()<deadline {
            try verify()
            let messages = try path(root,messagesPath)
            if try inputValue(target).isEmpty && matches(messages,0)>before {
                return ["verified":true,"witness":"new_client_bubble_and_empty_draft","delivery_confirmed":false]
            }
            RunLoop.current.run(until:Date().addingTimeInterval(0.05))
        }
        return ["verified":false,"invoked":true,"delivery_confirmed":false]
    }
    if op == "read" {
        var records: [[String:Any]] = []
        var remaining=64000
        func walk(_ n: AXUIElement, _ p: [Int], _ depth: Int) {
            guard records.count < 500, depth <= 12 else { return }
            let raw=value(n),text=String(raw.prefix(min(4000,remaining)))
            remaining-=text.count
            records.append(["path":p, "role":String(string(n,kAXRoleAttribute).prefix(512)), "value":text,
                "identifier":String(string(n,kAXIdentifierAttribute).prefix(512)), "truncated":text != raw])
            for (i,ch) in children(n).enumerated() { walk(ch,p+[i],depth+1) }
        }
        walk(target,targetPath,0)
        try verify()
        return ["nodes":records, "pid":app.processIdentifier,
                "foreground":NSWorkspace.shared.frontmostApplication?.processIdentifier == app.processIdentifier]
    }
    if op == "set_value" {
        guard let text = req["text"] as? String, text.count <= 16000 else { throw Failure("text_required") }
        guard try inputValue(target).isEmpty else { throw Failure("existing_draft_denied") }
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
