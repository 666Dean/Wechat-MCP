// SPDX-License-Identifier: AGPL-3.0-only
// Generic AX broker. Application-specific selectors and parsing belong to integrators.
import Foundation
import AppKit
import ApplicationServices
import LocalAuthentication
import AXRCommit
import Vision
import ScreenCaptureKit

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
func containingWindow(_ node: AXUIElement) throws -> AXUIElement {
    if string(node,kAXRoleAttribute)=="AXWindow" { return node }
    guard let window=attr(node,kAXWindowAttribute) as CFTypeRef?, CFGetTypeID(window)==AXUIElementGetTypeID() else {
        throw Failure("control_window_unavailable")
    }
    return window as! AXUIElement
}
func sameWindow(_ nodes: [AXUIElement]) throws {
    guard let first=nodes.first else { throw Failure("control_window_unavailable") }
    let window=try containingWindow(first)
    for node in nodes.dropFirst() {
        guard CFEqual(try containingWindow(node),window) else { throw Failure("cross_window_scope_denied") }
    }
}
func windowBounds(_ window:AXUIElement) -> CGRect? {
    guard let rawPosition=attr(window,kAXPositionAttribute) as CFTypeRef?, let rawSize=attr(window,kAXSizeAttribute) as CFTypeRef?,
          CFGetTypeID(rawPosition)==AXValueGetTypeID(), CFGetTypeID(rawSize)==AXValueGetTypeID() else { return nil }
    var position=CGPoint.zero,size=CGSize.zero
    guard AXValueGetValue(rawPosition as! AXValue,.cgPoint,&position),AXValueGetValue(rawSize as! AXValue,.cgSize,&size) else { return nil }
    return CGRect(origin:position,size:size)
}
func output(_ object: [String:Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]),
       let text = String(data: data, encoding: .utf8) { print(text) }
}
func verifyCommit(_ req: [String:Any], operations: [String], text: String? = nil) throws {
    guard let control=req["guard_context"] as? [String:String], let store=control["store"], let proof=control["proof"],
          let platform=req["expected_platform"] as? String, let account=req["expected_account"] as? String,
          let identity=req["expected_identity"] as? String, !platform.isEmpty, !account.isEmpty, !identity.isEmpty else {
        throw Failure("scoped_commit_proof_required")
    }
    var scope: [String:Any] = ["operations":operations,
        "resource":["platform":platform,"account_id":account,"conversation_id":identity]]
    if let text { scope["text"]=text }
    if req["op"] as? String == "read_ocr" { scope["visual_binding"]=req["visual_binding"] }
    let data=try JSONSerialization.data(withJSONObject:scope)
    let encoded=String(decoding:data,as:UTF8.self)
    guard store.withCString({ p in proof.withCString({ q in encoded.withCString({ s in axr_check_scoped_commit(p,q,s) }) }) })==1 else {
        throw Failure("authority_or_requested_scope_changed")
    }
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
    if op == "visual_capabilities" { return visualCapabilities(pid: app.processIdentifier) }
    if op == "read_ocr" {
        try verifyCommit(req,operations:["messages.read","messages.search"])
        return try localOCR(req,app:app)
    }
    guard op == "read" || op == "send_text" else { throw Failure("unknown_operation") }
    guard let headerPath = req["header_path"] as? [Int], let expected = req["expected_title"] as? String,
          !expected.isEmpty, let targetPath = req["path"] as? [Int] else { throw Failure("scope_required") }
    var boundTarget:AXUIElement?
    func verify() throws {
        try verifyCommit(req,operations:op == "send_text" ? ["messages.send"] : ["messages.read","messages.search"],
            text:op == "send_text" ? req["text"] as? String : nil)
        let current=NSRunningApplication.runningApplications(withBundleIdentifier:bundle)
        guard !app.isTerminated, current.count == 1, current[0].processIdentifier == app.processIdentifier else {
            throw Failure("application_epoch_changed")
        }
        let header = try path(root,headerPath)
        if op == "send_text" || op == "read" {
            guard let accountPath = req["account_path"] as? [Int],
                  let identityPath = req["identity_path"] as? [Int],
                  let account = req["expected_account"] as? String,
                  let identity = req["expected_identity"] as? String,
                  !account.isEmpty, !identity.isEmpty else {
                throw Failure("stable_identity_unavailable_or_changed")
            }
            let currentTarget=try path(root,targetPath)
            if let boundTarget, !CFEqual(boundTarget,currentTarget) { throw Failure("control_epoch_changed") }
            try sameWindow([currentTarget,path(root,headerPath),path(root,accountPath),path(root,identityPath)])
            if op == "send_text", let messagesPath=req["messages_path"] as? [Int] {
                try sameWindow([currentTarget,path(root,messagesPath)])
            }
            guard value(header)==expected else { throw Failure("target_identity_changed") }
            guard value(try path(root,accountPath))==account,value(try path(root,identityPath))==identity else {
                throw Failure("stable_identity_unavailable_or_changed")
            }
        }
    }
    try verify()
    let target = try path(root,targetPath)
    boundTarget=target
    try verify()
    if op == "send_text" {
        guard let text = req["text"] as? String, !text.isEmpty, text.count <= 16000,
              let messagesPath = req["messages_path"] as? [Int] else { throw Failure("send_parameters_required") }
        let method=req["send_method"] as? String ?? "ax_press"
        guard method == "ax_press" || method == "pid_return" else { throw Failure("send_method_unqualified") }
        if method == "pid_return" {
            // Return-to-send semantics must be qualified in the owner layout.
            guard req["return_sends_message"] as? Bool == true, text.count <= 200,
                  !text.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) || $0.value == 0x2028 || $0.value == 0x2029 }) else {
                throw Failure("return_send_semantics_or_text_unqualified")
            }
        }
        func focusInput() throws {
            guard AXUIElementSetAttributeValue(target,kAXFocusedAttribute as CFString,kCFBooleanTrue) == .success,
                  let focused=attr(root,kAXFocusedUIElementAttribute),CFEqual(focused as CFTypeRef,target) else {
                throw Failure("input_focus_unavailable_or_changed")
            }
        }
        guard try inputValue(target).isEmpty else { throw Failure("existing_draft_denied") }
        if method == "pid_return" { try verify();try focusInput() }
        if method == "ax_press" {
            guard let sendPath=req["send_path"] as? [Int] else { throw Failure("send_parameters_required") }
            try sameWindow([target,path(root,sendPath),path(root,messagesPath)])
        } else {
            try sameWindow([target,path(root,messagesPath)])
        }
        func matches(_ node: AXUIElement) throws -> Int {
            var visited=0
            func walk(_ n:AXUIElement,_ depth:Int) throws -> Int {
                visited+=1
                guard depth<=12,visited<=1500 else { throw Failure("message_witness_budget_exceeded") }
                var count=value(n)==text ? 1 : 0
                for child in children(n) { count += try walk(child,depth+1) }
                return count
            }
            return try walk(node,0)
        }
        let before = try matches(path(root,messagesPath))
        try verify()
        guard AXUIElementSetAttributeValue(target,kAXValueAttribute as CFString,text as CFString) == .success,
              try inputValue(target) == text else { throw Failure("draft_prepare_failed") }
        try verify()
        guard try inputValue(target) == text else { throw Failure("draft_changed_before_commit") }
        if method == "ax_press" {
            guard let sendPath=req["send_path"] as? [Int] else { throw Failure("send_parameters_required") }
            let send = try path(root,sendPath)
            try sameWindow([target,send,path(root,messagesPath)])
            guard AXUIElementPerformAction(send,kAXPressAction as CFString) == .success else {
                throw Failure("send_action_unavailable")
            }
        } else {
            try focusInput()
            let source=CGEventSource(stateID:.privateState)
            guard let down=CGEvent(keyboardEventSource:source,virtualKey:0x24,keyDown:true),
                  let up=CGEvent(keyboardEventSource:source,virtualKey:0x24,keyDown:false) else { throw Failure("input_event_unavailable") }
            down.flags=[];up.flags=[]
            try verify()
            guard try inputValue(target) == text, let finalFocus=attr(root,kAXFocusedUIElementAttribute),
                  CFEqual(finalFocus as CFTypeRef,target) else { throw Failure("draft_or_focus_changed_before_commit") }
            // Never post to the global event tap; never retry after this boundary.
            down.postToPid(app.processIdentifier);up.postToPid(app.processIdentifier)
        }
        let deadline=Date().addingTimeInterval(2)
        while Date()<deadline {
            try verify()
            let messages = try path(root,messagesPath)
            if try inputValue(target).isEmpty && matches(messages)>before {
                return ["verified":true,"witness":"new_client_bubble_and_empty_draft","delivery_confirmed":false,"send_method":method]
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
    throw Failure("unknown_operation")
}

// Local Vision observation. Legacy sharing metadata is not a modern capture
// protection guarantee. The automatic route conservatively requires >0 until
// an independent capture policy has been qualified; no filter fallback.
func visualCapabilities(pid: pid_t) -> [String:Any] {
    let rows=CGWindowListCopyWindowInfo(.optionOnScreenOnly,kCGNullWindowID) as? [[String:Any]] ?? []
    let windows=rows.filter { ($0[kCGWindowOwnerPID as String] as? Int) == Int(pid) && ($0[kCGWindowLayer as String] as? Int) == 0 }
    let legacyNonsharing=windows.filter { ($0[kCGWindowSharingState as String] as? Int ?? 0) == 0 }.count
    return ["pid":pid,"visible_windows":windows.count,"legacy_nonsharing_windows":legacyNonsharing,
        "capture_policy_candidates":windows.count-legacyNonsharing,"sharing_state_is_legacy":true,
        "capture_privacy":"unqualified","screen_capture_permission":CGPreflightScreenCaptureAccess(),
        "content_read":false,"ocr_local":true,"send_available":false]
}

final class OCRCaptureBox: @unchecked Sendable {
    private let lock=NSLock()
    private var result: Result<CGImage,Error>?
    func finish(_ value: Result<CGImage,Error>) { lock.lock();defer {lock.unlock()};if result == nil { result=value } }
    func take() -> Result<CGImage,Error>? { lock.lock();defer {lock.unlock()};return result }
}

func localOCR(_ req: [String:Any],app: NSRunningApplication) throws -> [String:Any] {
    guard #available(macOS 14.0,*), CGPreflightScreenCaptureAccess() else { throw Failure("screen_capture_permission_required") }
    guard let binding=req["visual_binding"] as? [String:Any], let id=binding["window_id"] as? Int,
          id>0, id<=Int(UInt32.max), let expectedBounds=binding["bounds"] as? [Double], expectedBounds.count==4,
          expectedBounds.allSatisfy({$0.isFinite}), let regions=binding["regions"] as? [String:[Double]],
          regions["messages"] != nil, Set(regions.keys).isSubset(of:Set(["account","identity","header","messages"])) else { throw Failure("visual_binding_required") }
    let identityPaths=binding["identity_paths"] as? [String:[Int]]
    if let identityPaths {
        guard Set(identityPaths.keys)==Set(["account","identity","header"]),
              identityPaths.values.allSatisfy({!$0.isEmpty && $0.count<=16 && $0.allSatisfy({$0>=0})}) else { throw Failure("visual_identity_paths_invalid") }
    } else if Set(regions.keys) != Set(["account","identity","header","messages"]) { throw Failure("visual_identity_regions_required") }
    for values in regions.values {
        guard values.count==4, values.allSatisfy({$0.isFinite && $0>=0 && $0<=1}),
              values[2]>0, values[3]>0, values[0]+values[2]<=1, values[1]+values[3]<=1 else {
            throw Failure("ocr_region_invalid")
        }
    }
    let start=Date()
    func verifyWindow() throws -> CGRect {
        try verifyCommit(req,operations:["messages.read","messages.search"])
        guard !app.isTerminated, let bundle=app.bundleIdentifier,
              NSRunningApplication.runningApplications(withBundleIdentifier:bundle).map({$0.processIdentifier}) == [app.processIdentifier],
              Date().timeIntervalSince(start)<30 else { throw Failure("visual_application_epoch_or_budget_changed") }
        let rows=CGWindowListCopyWindowInfo(.optionIncludingWindow,CGWindowID(id)) as? [[String:Any]] ?? []
        guard rows.count==1, let row=rows.first, (row[kCGWindowNumber as String] as? Int)==id,
              (row[kCGWindowOwnerPID as String] as? Int)==Int(app.processIdentifier),
              (row[kCGWindowIsOnscreen as String] as? Bool)==true,
              (row[kCGWindowLayer as String] as? Int)==0 else { throw Failure("visual_window_changed") }
        guard (row[kCGWindowSharingState as String] as? Int ?? 0)>0 else { throw Failure("legacy_window_sharing_unqualified") }
        guard let raw=row[kCGWindowBounds as String] as? [String:Any], let bounds=CGRect(dictionaryRepresentation:raw as CFDictionary),
              [bounds.minX,bounds.minY,bounds.width,bounds.height].map({Double($0)})==expectedBounds,
              bounds.width>=100,bounds.height>=100,bounds.width<=4096,bounds.height<=4096 else { throw Failure("visual_geometry_changed") }
        return bounds
    }
    func recognize(_ name: String) throws -> [[String:Any]] {
        let bounds=try verifyWindow(), region=regions[name]!
        let crop=CGRect(x:region[0]*bounds.width,y:region[1]*bounds.height,width:region[2]*bounds.width,height:region[3]*bounds.height)
        let box=OCRCaptureBox()
        SCShareableContent.getExcludingDesktopWindows(true,onScreenWindowsOnly:true) { content,error in
            guard let content, let window=content.windows.first(where:{$0.windowID==CGWindowID(id) && $0.owningApplication?.processID==app.processIdentifier}) else {
                box.finish(.failure(error ?? Failure("visual_window_unavailable")));return
            }
            // sourceRect is ignored for desktopIndependentWindow filters.
            // A display filter including ONLY this window keeps the ROI effective
            // without capturing the desktop or pixels of overlapping applications.
            let displays=content.displays.filter { $0.frame.contains(bounds) }
            guard displays.count==1, let display=displays.first else {
                box.finish(.failure(Failure("window_crosses_display_boundary")));return
            }
            let filter=SCContentFilter(display:display,including:[window])
            let config=SCStreamConfiguration()
            config.sourceRect=CGRect(x:bounds.minX+crop.minX-display.frame.minX,y:bounds.minY+crop.minY-display.frame.minY,width:crop.width,height:crop.height)
            config.width=max(1,Int(crop.width*2));config.height=max(1,Int(crop.height*2));config.showsCursor=false;config.capturesAudio=false
            SCScreenshotManager.captureImage(contentFilter:filter,configuration:config) { image,error in
                if let image { box.finish(.success(image)) }
                else { box.finish(.failure(error ?? Failure("window_capture_unavailable"))) }
            }
        }
        let deadline=Date().addingTimeInterval(2)
        while box.take()==nil && Date()<deadline { RunLoop.current.run(until:Date().addingTimeInterval(0.01)) }
        guard let capture=box.take() else { throw Failure("window_capture_timeout") }
        let image:CGImage
        do { image=try capture.get() } catch { throw Failure("window_capture_failed") }
        _=try verifyWindow()
        let request=VNRecognizeTextRequest()
        request.recognitionLevel = .accurate;request.recognitionLanguages=["zh-Hans","en-US"];request.usesLanguageCorrection=false
        do { try VNImageRequestHandler(cgImage:image).perform([request]) }
        catch { throw Failure("local_ocr_failed") }
        let results=request.results ?? []
        guard results.count<=100 else { throw Failure("ocr_page_budget_exceeded") }
        var bytes=0
        let lines=try results.sorted { $0.boundingBox.midY > $1.boundingBox.midY }.compactMap { item -> [String:Any]? in
            guard let text=item.topCandidates(1).first else { return nil }
            bytes+=text.string.utf8.count
            guard bytes<=64000 else { throw Failure("ocr_text_budget_exceeded") }
            return ["text":text.string,"confidence":text.confidence]
        }
        _=try verifyWindow()
        return lines
    }
    func identity() throws {
        if let identityPaths {
            let bounds=try verifyWindow()
            let root=AXUIElementCreateApplication(app.processIdentifier)
            AXUIElementSetMessagingTimeout(root,2)
            let rows=CGWindowListCopyWindowInfo(.optionIncludingWindow,CGWindowID(id)) as? [[String:Any]] ?? []
            guard let name=rows.first?[kCGWindowName as String] as? String,!name.isEmpty else { throw Failure("visual_window_identity_unavailable") }
            let windows=(attr(root,kAXWindowsAttribute) as? [AXUIElement] ?? []).filter {
                windowBounds($0)==bounds && string($0,kAXTitleAttribute)==name
            }
            guard windows.count==1 else { throw Failure("visual_platform_window_ambiguous") }
            for (region,key) in [("account","expected_account"),("identity","expected_identity"),("header","expected_title")] {
                let node=try path(root,identityPaths[region]!)
                guard let expected=req[key] as? String,!expected.isEmpty,
                      CFEqual(try containingWindow(node),windows[0]),value(node)==expected else { throw Failure("visual_platform_identity_changed") }
            }
            _=try verifyWindow();return
        }
        for (region,key) in [("account","expected_account"),("identity","expected_identity"),("header","expected_title")] {
            guard let expected=req[key] as? String, !expected.isEmpty else { throw Failure("visual_identity_required") }
            let lines=try recognize(region)
            guard lines.filter({($0["text"] as? String)==expected && ($0["confidence"] as? Float ?? 0)>=0.98}).count==1 else {
                throw Failure("visual_identity_unavailable_or_ambiguous")
            }
        }
    }
    try identity()
    let lines=try recognize("messages")
    try identity()
    return ["pid":app.processIdentifier,"lines":lines,"foreground":app.isActive,"preview_only":true,
        "identity_assurance":identityPaths == nil ? "visible_exact_identifiers_ocr" : "owner_verified_platform_witness",
        "images_persisted":false,"network_used":false,
        "sender_qualified":false,"delivery_confirmed":false]
}

do { output(try main()) } catch let failure as Failure { output(["error":failure.code]) }
catch { output(["error":"native_helper_failed"]) }
