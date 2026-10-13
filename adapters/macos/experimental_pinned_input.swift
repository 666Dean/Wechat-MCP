// SPDX-License-Identifier: MIT
// Experimental owner-initialized input. Not registered or qualified as an MCP sender.
// The parent owns OS approval, account/contact qualification, durable attempt
// suppression, the account lease, and independent database observation.
import AppKit
import ApplicationServices
import CoreGraphics
import Foundation
import AXRCommit
var dispatchStarted=false
var stageStarted=false
var activationRequested=false
var activationAccepted=false
var raiseCode:Int?=nil
struct Stop:Error {let code:String;init(_ c:String){code=c}}
func attribute(_ n:AXUIElement,_ key:String)->CFTypeRef? {var v:CFTypeRef?;guard AXUIElementCopyAttributeValue(n,key as CFString,&v) == .success else{return nil};return v}
func emit(_ r:[String:Any]) {print(String(data:try! JSONSerialization.data(withJSONObject:r,options:.sortedKeys),encoding:.utf8)!)}
func key(_ pid:pid_t,_ code:CGKeyCode,_ flags:CGEventFlags=[]) throws {
 for down in [true,false] {guard let e=CGEvent(keyboardEventSource:nil,virtualKey:code,keyDown:down) else {throw Stop("event_unavailable")};e.flags=flags;e.postToPid(pid);usleep(25000)}
}
// Read a single bounded inherited-pipe frame; no unbounded readLine allocation.
func inputFrame() throws -> Data? {
 var data=Data()
 while let chunk=try FileHandle.standardInput.read(upToCount:4096), !chunk.isEmpty {
  guard data.count+chunk.count<=1024*1024 else {throw Stop("request_budget")}
  data.append(chunk)
  if let newline=data.firstIndex(of:10) {return Data(data[..<newline])}
 }
 return data.isEmpty ? nil : data
}
func run() throws -> [String:Any] {
 guard let frame=try inputFrame(),let req=try JSONSerialization.jsonObject(with:frame) as? [String:Any],let title=req["title"] as? String,let windowID=req["window_id"] as? Int,let expected=req["expected_text"] as? String,!title.isEmpty,!expected.isEmpty else {throw Stop("bad_scope")}
 let mode=req["mode"] as? String
 guard mode=="send" || mode=="prepare_send" || mode=="read" || mode=="validate_scope" else {throw Stop("unsupported_mode")}
 let sending=mode=="send" || mode=="prepare_send"
 let staging=mode=="prepare_send"
 if staging {guard let binding=req["visual_binding"] as? [String:Any],binding["input_initialization"] as? String=="owner_attested_empty_and_focused" else {throw Stop("empty_focused_owner_initialization_required")}}
 func proof() throws {

  guard let c=req["guard_context"] as? [String:String],let path=c["store"],let encoded=c["proof"],let account=req["account"] as? String,let identity=req["identity"] as? String,let binding=req["visual_binding"] as? [String:Any],binding["window_id"] as? Int==windowID,binding["title"] as? String==title else {throw Stop("sealed_scope_required")}
  let scope:[String:Any]=["operations":[mode=="validate_scope" ? (req["operation"] as? String ?? "messages.send") : (sending ? "messages.send" : "messages.read")],"resource":["platform":"wechat","account_id":account,"conversation_id":identity],"text":expected,"visual_binding":binding]
  let json=String(decoding:try JSONSerialization.data(withJSONObject:scope),as:UTF8.self)
  guard path.withCString({p in encoded.withCString({q in json.withCString({r in axr_check_scoped_commit(p,q,r)})})})==1 else {throw Stop("authority_or_scope_changed")}
 }
 try proof()
 if mode=="validate_scope" {return ["scope_valid":true,"send_available":false,"send_invoked":false,"ui_accessed":false]}
 guard AXIsProcessTrusted() else {throw Stop("accessibility_required")}
 let apps=NSRunningApplication.runningApplications(withBundleIdentifier:"com.tencent.xinWeChat")
 guard apps.count==1,let app=apps.first,app.bundleURL?.path=="/Applications/WeChat.app" else {throw Stop("original_application_required")}
 let pid=app.processIdentifier
 guard let binding=req["visual_binding"] as? [String:Any],binding["pid"] as? Int==Int(pid) else {throw Stop("application_epoch_changed")}
 let root=AXUIElementCreateApplication(pid);AXUIElementSetMessagingTimeout(root,2)
 func rows()->[[String:Any]] {(CGWindowListCopyWindowInfo(.optionAll,kCGNullWindowID) as? [[String:Any]] ?? []).filter{($0[kCGWindowOwnerPID as String] as? Int)==Int(pid) && ($0[kCGWindowLayer as String] as? Int)==0}}
 guard let original=rows().first(where:{($0[kCGWindowNumber as String] as? Int)==windowID}),original[kCGWindowName as String] as? String==title,let bounds=original[kCGWindowBounds as String] as? NSDictionary else {throw Stop("window_binding_changed")}
 guard let sealed=binding["bounds"] as? NSDictionary,sealed==bounds else {throw Stop("window_geometry_changed")}
 let windows=attribute(root,kAXWindowsAttribute) as? [AXUIElement] ?? []
 let candidates=windows.filter{attribute($0,kAXTitleAttribute) as? String==title}
 guard candidates.count==1,let target=candidates.first else {throw Stop("window_missing_or_ambiguous")}
 activationRequested=true
 activationAccepted=app.isActive || app.activate(options:[])
 guard activationAccepted else {throw Stop("window_activation_failed")}
 let raised=AXUIElementPerformAction(target,kAXRaiseAction as CFString);raiseCode=Int(raised.rawValue)
 guard raised == .success else {throw Stop("window_raise_failed")}
 RunLoop.current.run(until:Date().addingTimeInterval(0.2))
 func verify() throws {
  try proof()
  guard !app.isTerminated,app.isActive else {throw Stop("foreground_changed")}
  guard let current=rows().first(where:{($0[kCGWindowNumber as String] as? Int)==windowID}),current[kCGWindowName as String] as? String==title,(current[kCGWindowBounds as String] as? NSDictionary)==bounds,attribute(target,kAXTitleAttribute) as? String==title else {throw Stop("window_binding_changed")}
  let visible=(CGWindowListCopyWindowInfo(.optionOnScreenOnly,kCGNullWindowID) as? [[String:Any]] ?? []).filter{($0[kCGWindowOwnerPID as String] as? Int)==Int(pid) && ($0[kCGWindowLayer as String] as? Int)==0}
  guard visible.first?[kCGWindowNumber as String] as? Int==windowID else {throw Stop("target_not_front_window")}
 }
 try verify()
 let pb=NSPasteboard.general
 // Preserve the owner's clipboard only in memory. Restore only our own epoch.
 let backupEpoch=pb.changeCount
 let backupItems=pb.pasteboardItems ?? []
 guard backupItems.count<=32,backupItems.allSatisfy({$0.types.count<=32}) else {throw Stop("clipboard_backup_budget")}
 var backupBytes=0
 let saved=backupItems.map{item->[NSPasteboard.PasteboardType:Data] in var result:[NSPasteboard.PasteboardType:Data]=[:];for t in item.types {if let data=item.data(forType:t){backupBytes+=data.count;result[t]=data}};return result}
 guard backupBytes<=1024*1024 else {throw Stop("clipboard_backup_budget")}
 guard pb.changeCount==backupEpoch else {throw Stop("clipboard_changed_during_backup")}
 let nonce="AXR-clipboard-probe-"+UUID().uuidString
 pb.clearContents();pb.setString(nonce,forType:.string);var ownedCount=pb.changeCount
 defer {
  if pb.changeCount==ownedCount {pb.clearContents();let items=saved.map{r->NSPasteboardItem in let item=NSPasteboardItem();for(t,d)in r{item.setData(d,forType:t)};return item};if !items.isEmpty{pb.writeObjects(items)}}
 }
 if staging {
  try verify();try key(pid,53);try verify()
  guard pb.changeCount==ownedCount else {throw Stop("clipboard_changed_before_stage")}
  pb.clearContents();pb.setString(expected,forType:.string);ownedCount=pb.changeCount
  try verify();guard pb.changeCount==ownedCount else {throw Stop("clipboard_changed_before_stage")}
  stageStarted=true;try key(pid,9,.maskCommand)
  RunLoop.current.run(until:Date().addingTimeInterval(0.2));try verify()
  guard pb.changeCount==ownedCount else {throw Stop("clipboard_changed_after_stage")}
  pb.clearContents();pb.setString(nonce,forType:.string);ownedCount=pb.changeCount
 }
 try verify();try key(pid,53);try verify();try key(pid,0,.maskCommand);try verify();try key(pid,8,.maskCommand)
 RunLoop.current.run(until:Date().addingTimeInterval(0.25))
 try verify()
 let copiedCount=pb.changeCount
 guard let text=pb.string(forType:.string),text != nonce else {return ["window_verified":true,"copy_received":false,"exact_draft_match":false,"message_sent":false,"text_disclosed":false]}
 if text==expected {ownedCount=copiedCount}
 if sending && text==expected {
  try verify()
  guard pb.changeCount==copiedCount else {throw Stop("clipboard_changed_before_commit")}
  // Re-copy immediately before the one irreversible key. No retry boundary.
  try key(pid,0,.maskCommand);try verify();try key(pid,8,.maskCommand)
  RunLoop.current.run(until:Date().addingTimeInterval(0.1))
  let finalCount=pb.changeCount
  guard pb.string(forType:.string)==expected else {throw Stop("draft_changed_before_commit")}
  ownedCount=finalCount;try verify()
  guard pb.changeCount==finalCount else {throw Stop("clipboard_changed_before_commit")}
  dispatchStarted=true;try key(pid,36)
  return ["window_verified":true,"exact_draft_match":true,"stage_invoked":stageStarted,"send_invoked":true,"delivery_confirmed":false,"text_disclosed":false]
 }
 return ["window_verified":true,"copy_received":true,"exact_draft_match":text==expected,"message_sent":false,"text_disclosed":false]
}
do {emit(try run())}catch let e as Stop{emit(["error":e.code,"send_invoked":dispatchStarted,"stage_invoked":stageStarted,"text_disclosed":false,"activation_requested":activationRequested,"activation_accepted":activationAccepted,"raise_code":raiseCode as Any? ?? NSNull()])}catch{emit(["error":"probe_failed","send_invoked":dispatchStarted,"stage_invoked":stageStarted,"text_disclosed":false])}
