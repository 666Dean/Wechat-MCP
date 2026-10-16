// SPDX-License-Identifier: MIT
// Experimental original-app menu search and bounded draft input; not a product sender.
import AppKit
import ApplicationServices
import CoreGraphics
import Foundation
import AXRCommit
import CryptoKit

struct Stop: Error { let code: String; init(_ code: String) { self.code=code } }
var staged=false, submitted=false, navigated=false
var shell:[String:Any]=[:]
var authorityContext:[String:String]?=nil
var authorityMode=""
func attr(_ node: AXUIElement,_ key: String)->CFTypeRef? {
 var value:CFTypeRef?; guard AXUIElementCopyAttributeValue(node,key as CFString,&value) == .success else{return nil};return value
}
func children(_ node: AXUIElement)->[AXUIElement] { attr(node,kAXChildrenAttribute) as? [AXUIElement] ?? [] }
func label(_ node: AXUIElement)->String {attr(node,kAXTitleAttribute) as? String ?? ""}
func emit(_ value:[String:Any]) {print(String(decoding:try! JSONSerialization.data(withJSONObject:value,options:.sortedKeys),as:UTF8.self))}
func frame() throws -> Data {
 var data=Data()
 while let chunk=try FileHandle.standardInput.read(upToCount:4096),!chunk.isEmpty {
  guard data.count+chunk.count<=1024*1024 else{throw Stop("request_budget")};data.append(chunk)
  if let end=data.firstIndex(of:10){return Data(data[..<end])}
 }
 return data
}
func run() throws -> [String:Any] {
 let decoded=try JSONSerialization.jsonObject(with:frame())
 if let request=decoded as? [String:Any] {
  authorityContext=request["guard_context"] as? [String:String]
  authorityMode=request["mode"] as? String ?? ""
 }
 if let request=decoded as? [String:Any],request["mode"] as? String=="binding" {
  let apps=NSRunningApplication.runningApplications(withBundleIdentifier:"com.tencent.xinWeChat")
  guard apps.count==1,let app=apps.first,app.bundleURL?.path=="/Applications/WeChat.app" else{throw Stop("original_application_required")}
  let rows=(CGWindowListCopyWindowInfo(.optionOnScreenOnly,kCGNullWindowID) as? [[String:Any]] ?? []).filter{($0[kCGWindowOwnerPID as String] as? Int)==Int(app.processIdentifier) && ($0[kCGWindowLayer as String] as? Int)==0 && ($0[kCGWindowName as String] as? String)=="微信"}
  guard rows.count==1,let row=rows.first,let id=row[kCGWindowNumber as String] as? Int,let bounds=row[kCGWindowBounds as String] as? [String:Any] else{throw Stop("visible_main_window_missing_or_ambiguous")}
  return ["binding":["pid":Int(app.processIdentifier),"window_id":id,"title":"微信","bounds":bounds],"send_available":false,"window_metadata_only":true,"ui_actions":false,"send_invoked":false]
 }
 guard let req=decoded as? [String:Any],let mode=req["mode"] as? String,
       ["navigate","stage_draft","read_draft","send","validate_scope"].contains(mode),
       let operation=req["operation"] as? String,
       let text=req["expected_text"] as? String,!text.isEmpty,text.utf8.count<=16000,
       let binding=req["visual_binding"] as? [String:Any],let pid=binding["pid"] as? Int,pid>0,
       let windowID=binding["window_id"] as? Int,windowID>0,
       let title=binding["title"] as? String,title=="微信",let bounds=binding["bounds"] as? NSDictionary else {throw Stop("bad_scope")}
 let operations=["navigate":"application.navigate","stage_draft":"application.draft","read_draft":"messages.read","send":"messages.send"]
 guard (mode=="validate_scope" && operations.values.contains(operation)) || operations[mode]==operation else{throw Stop("operation_mismatch")}
 if operation=="messages.send" {
  guard binding["recipient_assurance"] as? String=="cached_exact_draft_and_fresh_search",let witness=binding["recipient_witness"] as? String,witness.count==64,witness.allSatisfy({"0123456789abcdef".contains($0)}) else{throw Stop("recipient_witness_required")}
 }
 func authority(_ claim:Bool=false) throws {
  guard let c=req["guard_context"] as? [String:String],let encoded=c["proof"],
        let account=req["account"] as? String,let identity=req["identity"] as? String else{throw Stop("sealed_scope_required")}
  var scope:[String:Any]=["operations":[operation],"resource":["platform":"wechat","account_id":account,"conversation_id":identity],"text":text,"visual_binding":binding]
  if operation=="application.navigate" {scope["navigation_binding"]=["menu_path":["编辑","搜索"],"main_window_id":windowID,"query":text] as [String:Any]}
  let json=String(decoding:try JSONSerialization.data(withJSONObject:scope),as:UTF8.self)
  let allowed:Int32
  if let endpoint=c["authority_endpoint"] {
   allowed=endpoint.withCString{p in encoded.withCString{q in json.withCString{r in claim ? axr_authority_claim(p,q,r) : axr_authority_preflight(p,q,r)}}}
  } else {
   // Gen1 reference profile only. Native formal builds reject this C ABI.
   guard let store=c["store"] else{throw Stop("authority_endpoint_required")}
   allowed=store.withCString{p in encoded.withCString{q in json.withCString{r in axr_check_scoped_commit(p,q,r)}}}
  }
  guard allowed==1 else{throw Stop("authority_or_scope_changed")}
 }
 func proof() throws {try authority()}
 try proof()
 if mode=="validate_scope" {return ["scope_valid":true,"ui_accessed":false,"send_available":false,"send_invoked":false]}
 guard AXIsProcessTrusted() else{throw Stop("accessibility_required")}
 let apps=NSRunningApplication.runningApplications(withBundleIdentifier:"com.tencent.xinWeChat")
 guard apps.count==1,let app=apps.first,Int(app.processIdentifier)==pid,app.bundleURL?.path=="/Applications/WeChat.app" else{throw Stop("original_application_epoch_required")}
 let root=AXUIElementCreateApplication(pid_t(pid));AXUIElementSetMessagingTimeout(root,2)
 func windows()->[AXUIElement] {attr(root,kAXWindowsAttribute) as? [AXUIElement] ?? []}
 var matches=windows().filter{label($0)==title}
 let discoveryDeadline=Date().addingTimeInterval(1)
 while matches.isEmpty && Date()<discoveryDeadline {RunLoop.current.run(until:Date().addingTimeInterval(0.05));matches=windows().filter{label($0)==title}}
 guard matches.count==1 else{throw Stop("main_window_missing_or_ambiguous")}
 let target=matches[0]
 guard app.isActive || app.activate(options:[]) else{throw Stop("activation_failed")}
 guard AXUIElementPerformAction(target,kAXRaiseAction as CFString) == .success else{throw Stop("raise_failed")}
 RunLoop.current.run(until:Date().addingTimeInterval(0.2))
 func verify(_ dialog:Bool=false) throws {
  try proof()
  guard !app.isTerminated,app.isActive else{throw Stop("foreground_changed")}
  let rows=(CGWindowListCopyWindowInfo(.optionOnScreenOnly,kCGNullWindowID) as? [[String:Any]] ?? []).filter{($0[kCGWindowOwnerPID as String] as? Int)==pid && ($0[kCGWindowLayer as String] as? Int)==0}
  guard rows.contains(where:{($0[kCGWindowNumber as String] as? Int)==windowID && ($0[kCGWindowBounds as String] as? NSDictionary)==bounds}) else{throw Stop("window_epoch_or_geometry_changed")}
  guard let focused=attr(root,kAXFocusedWindowAttribute),CFGetTypeID(focused)==AXUIElementGetTypeID() else{throw Stop("focused_window_unavailable")}
  let current=focused as! AXUIElement
  if dialog {
   let subrole=attr(current,kAXSubroleAttribute) as? String ?? ""
   shell=["focused_is_dialog":subrole=="AXDialog","focused_title_empty":label(current).isEmpty,"ax_window_count":windows().count]
   guard subrole=="AXDialog",label(current).isEmpty else{throw Stop("search_dialog_unconfirmed")}
  } else {
   guard label(current)==title,rows.first?[kCGWindowNumber as String] as? Int==windowID else{throw Stop("main_window_not_foreground")}
  }
 }
 func key(_ code:CGKeyCode,_ flags:CGEventFlags=[],dialog:Bool=false) throws {
  try verify(dialog)
  for down in [true,false] {
   guard let event=CGEvent(keyboardEventSource:nil,virtualKey:code,keyDown:down) else{throw Stop("event_unavailable")}
   event.flags=flags;event.postToPid(pid_t(pid));usleep(25000)
  }
 }
 try verify()
 // Non-send transactions claim before their first UI/clipboard operation.
 // Send keeps all input comparisons in preflight and claims at final Return.
 if mode != "send" {try authority(true)}
 let pb=NSPasteboard.general;let before=pb.changeCount;let items=pb.pasteboardItems ?? []
 guard items.count<=32,items.allSatisfy({$0.types.count<=32}) else{throw Stop("clipboard_budget")}
 var bytes=0
 let saved=items.map{item->[NSPasteboard.PasteboardType:Data] in var result:[NSPasteboard.PasteboardType:Data]=[:];for type in item.types {if let data=item.data(forType:type){bytes+=data.count;result[type]=data}};return result}
 guard bytes<=1024*1024,pb.changeCount==before else{throw Stop("clipboard_backup_changed_or_oversized")}
 var owned=before
 defer {if pb.changeCount==owned {pb.clearContents();let restored=saved.map{values->NSPasteboardItem in let item=NSPasteboardItem();for(t,d)in values{item.setData(d,forType:t)};return item};if !restored.isEmpty{pb.writeObjects(restored)}}}
 func put(_ value:String) throws {
  guard pb.changeCount==owned else{throw Stop("clipboard_changed")};pb.clearContents();pb.setString(value,forType:.string);owned=pb.changeCount
 }
 func echo(dialog:Bool=false) throws -> Bool {
  let nonce="AXR-copy-"+UUID().uuidString;try put(nonce)
  try key(0,.maskCommand,dialog:dialog);try key(8,.maskCommand,dialog:dialog)
  RunLoop.current.run(until:Date().addingTimeInterval(0.15));try verify(dialog)
  if pb.changeCount != owned && pb.string(forType:.string)==text {owned=pb.changeCount;return true}
  // Unknown clipboard data is never disclosed or assumed to be our epoch.
  return false
 }
 if mode=="navigate" {
  guard text.utf8.count<=512,!text.contains("\n"),!text.contains("\r") else{throw Stop("query_budget")}
  guard let bar=attr(root,kAXMenuBarAttribute),CFGetTypeID(bar)==AXUIElementGetTypeID() else{throw Stop("menu_bar_missing")}
  let parents=children(bar as! AXUIElement).filter{label($0)=="编辑"}
  guard parents.count==1 else{throw Stop("edit_menu_ambiguous")}
  try verify();guard AXUIElementPerformAction(parents[0],kAXPressAction as CFString) == .success else{throw Stop("menu_open_failed")}
  let menus=children(parents[0]).filter{attr($0,kAXRoleAttribute) as? String=="AXMenu"}
  defer {for menu in menus{AXUIElementPerformAction(menu,kAXCancelAction as CFString)}}
  let entries=menus.flatMap{children($0)}.filter{label($0)=="搜索"}
  guard entries.count==1,attr(entries[0],kAXEnabledAttribute) as? Bool==true else{throw Stop("search_entry_ambiguous")}
  try proof();guard AXUIElementPerformAction(entries[0],kAXPressAction as CFString) == .success else{throw Stop("search_open_failed")}
  let searchDeadline=Date().addingTimeInterval(2)
  while Date()<searchDeadline {RunLoop.current.run(until:Date().addingTimeInterval(0.05));if (try? verify(true)) != nil {break}}
  try verify(true)
  try key(0,.maskCommand,dialog:true);try put(text);try key(9,.maskCommand,dialog:true)
  RunLoop.current.run(until:Date().addingTimeInterval(0.2));guard try echo(dialog:true) else{throw Stop("search_query_echo_unconfirmed")}
  // This Return is allowed only in the new untitled search dialog, never a chat.
  try verify(true);navigated=true;try key(36,dialog:true)
  RunLoop.current.run(until:Date().addingTimeInterval(0.3));try verify()
  return ["navigation_invoked":true,"query_echo_match":true,"main_window_verified":true,"recipient_verified":false,"send_invoked":false]
 }
 if mode=="stage_draft" {
  // Collapse a selection before insertion; never replace or delete an unknown draft.
  try key(124);try put(text);try verify();staged=true;try key(9,.maskCommand)
  RunLoop.current.run(until:Date().addingTimeInterval(0.2))
 }
 let exact=try echo()
 if mode=="send" && exact {
  guard try echo() else{throw Stop("draft_changed_before_commit")}
  try verify();guard pb.changeCount==owned else{throw Stop("clipboard_changed_before_commit")}
  try authority(true)
  submitted=true;try key(36)
 }
 return ["draft_match":exact,"stage_invoked":staged,"send_invoked":submitted,"delivery_confirmed":false,"content_disclosed":false]
}
// A separate ready frame lets the installed authority enroll the actual helper
// birth instance BEFORE preparing the sealed final-action proof. No input yet.
if CommandLine.arguments.count==2 && CommandLine.arguments[1]=="--authority-v2" {
 emit(["version":2,"ready":true,"input_received":false]);fflush(stdout)
}
func finish(_ result:[String:Any]) {
 var output=result
 if let context=authorityContext,let endpoint=context["authority_endpoint"],let proof=context["proof"] {
  let data=(try? JSONSerialization.data(withJSONObject:result,options:.sortedKeys)) ?? Data()
  let evidence=SHA256.hash(data:data).map{String(format:"%02x",$0)}.joined()
  // A keyboard submission is never proof of delivery. The independent WCDB
  // observation stays separate, and an uncertain send remains Unknown.
  let verified=authorityMode != "send" && result["error"] == nil &&
   (result["draft_match"] as? Bool==true || result["navigation_invoked"] as? Bool==true)
  output["authority_receipt_recorded"]=endpoint.withCString{e in proof.withCString{p in evidence.withCString{d in axr_authority_observe(e,p,verified ? 1:0,d)}}}==1
 }
 emit(output)
}
do {finish(try run())}catch let error as Stop{finish(["error":error.code,"stage_invoked":staged,"send_invoked":submitted,"navigation_invoked":navigated,"shell":shell,"content_disclosed":false])}catch{finish(["error":"operation_failed","stage_invoked":staged,"send_invoked":submitted,"content_disclosed":false])}
