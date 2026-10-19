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
var submitMethod="none"
var shell:[String:Any]=[:]
var authorityContext:[String:String]?=nil
var authorityMode=""
var authorityChecks=0
var claimedPermit=false
var lastAuthorityCheck=Date.distantPast
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
  // Window titles in CGWindowList can be withheld without Screen Recording.
  // Read the authorized AX title/geometry instead; no image or capture grant.
  guard AXIsProcessTrusted() else{throw Stop("accessibility_required")}
  let root=AXUIElementCreateApplication(app.processIdentifier);AXUIElementSetMessagingTimeout(root,2)
  let windows=(attr(root,kAXWindowsAttribute) as? [AXUIElement] ?? []).filter{label($0)=="微信"}
  guard windows.count==1,let window=windows.first,
        let position=attr(window,kAXPositionAttribute),CFGetTypeID(position)==AXValueGetTypeID(),
        let size=attr(window,kAXSizeAttribute),CFGetTypeID(size)==AXValueGetTypeID() else{throw Stop("main_window_missing_or_ambiguous")}
  var origin=CGPoint.zero;var dimensions=CGSize.zero
  guard AXValueGetValue(position as! AXValue,.cgPoint,&origin),AXValueGetValue(size as! AXValue,.cgSize,&dimensions),dimensions.width>0,dimensions.height>0 else{throw Stop("main_window_geometry_required")}
  let rows=(CGWindowListCopyWindowInfo(.optionAll,kCGNullWindowID) as? [[String:Any]] ?? []).filter{row in
   guard (row[kCGWindowOwnerPID as String] as? Int)==Int(app.processIdentifier),
         (row[kCGWindowLayer as String] as? Int)==0,
         let bounds=row[kCGWindowBounds as String] as? [String:Double],
         let x=bounds["X"],let y=bounds["Y"],let width=bounds["Width"],let height=bounds["Height"] else{return false}
   return abs(x-origin.x)<0.5 && abs(y-origin.y)<0.5 && abs(width-dimensions.width)<0.5 && abs(height-dimensions.height)<0.5
  }
  guard rows.count==1,let row=rows.first,let id=row[kCGWindowNumber as String] as? Int,let bounds=row[kCGWindowBounds as String] as? [String:Any] else{throw Stop("visible_main_window_missing_or_ambiguous")}
  return ["binding":["pid":Int(app.processIdentifier),"window_id":id,"title":"微信","bounds":bounds],"application_active":app.isActive,"send_available":false,"window_metadata_only":true,"title_source":"accessibility","capture_used":false,"ui_actions":false,"send_invoked":false]
 }
 guard let req=decoded as? [String:Any],let mode=req["mode"] as? String,
       ["navigate","stage_draft","read_draft","send","validate_scope"].contains(mode),
       let operation=req["operation"] as? String,
       let text=req["expected_text"] as? String,!text.isEmpty,text.utf8.count<=16000,
       let binding=req["visual_binding"] as? [String:Any],let pid=binding["pid"] as? Int,pid>0,
       let windowID=binding["window_id"] as? Int,windowID>0,
       let title=binding["title"] as? String,title=="微信",let bounds=binding["bounds"] as? NSDictionary else {throw Stop("bad_scope")}
 let phase=req["navigation_phase"] as? String ?? "complete"
 guard ["complete","open","query","select"].contains(phase) else{throw Stop("bad_navigation_phase")}
 let operations=["navigate":"application.navigate","stage_draft":"application.draft","read_draft":"messages.read","send":"messages.send"]
 guard (mode=="validate_scope" && operations.values.contains(operation)) || operations[mode]==operation else{throw Stop("operation_mismatch")}
 if operation=="messages.send" {
  guard binding["recipient_assurance"] as? String=="cached_exact_draft_and_fresh_search",let witness=binding["recipient_witness"] as? String,witness.count==64,witness.allSatisfy({"0123456789abcdef".contains($0)}) else{throw Stop("recipient_witness_required")}
 }
 func authority(_ claim:Bool=false,_ forceServer:Bool=false) throws {
  guard let c=req["guard_context"] as? [String:String],let encoded=c["proof"],
        let account=req["account"] as? String,let identity=req["identity"] as? String else{throw Stop("sealed_scope_required")}
  var scope:[String:Any]=["operations":[operation],"resource":["platform":"wechat","account_id":account,"conversation_id":identity],"text":text,"visual_binding":binding]
  if operation=="application.navigate" {
   var navigation:[String:Any]=["menu_path":["编辑","搜索"],"main_window_id":windowID,"query":text]
   if req["navigation_phase"] != nil {navigation["phase"]=phase}
   scope["navigation_binding"]=navigation
  }
  let json=String(decoding:try JSONSerialization.data(withJSONObject:scope),as:UTF8.self)
  let allowed:Int32
  if let endpoint=c["authority_endpoint"] {
   allowed=endpoint.withCString{p in encoded.withCString{q in json.withCString{r in
    claim ? axr_authority_claim(p,q,r) : claimedPermit && !forceServer ? axr_authority_local_permit(p,q,r) : axr_authority_preflight(p,q,r)
   }}}
  } else {
   // Gen1 reference profile only. Native formal builds reject this C ABI.
   guard let store=c["store"] else{throw Stop("authority_endpoint_required")}
   allowed=store.withCString{p in encoded.withCString{q in json.withCString{r in axr_check_scoped_commit(p,q,r)}}}
  }
  authorityChecks+=1
  guard allowed==1 else{
   if c["authority_endpoint"] != nil {
    throw Stop("authority_"+String(cString:axr_authority_last_failure())+(claim ? "_claim_" : "_preflight_")+String(authorityChecks))
   }
   throw Stop("authority_or_scope_changed")
  }
  if claim {claimedPermit=true}
  lastAuthorityCheck=Date()
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
 let backgroundMode=binding["activation_policy"] as? String=="background_when_idle"
 let previousForeground=NSWorkspace.shared.frontmostApplication?.processIdentifier
 if backgroundMode && app.isActive {throw Stop("background_requires_inactive_app")}
 func verifyActivity() throws {
  if backgroundMode {
   guard NSWorkspace.shared.frontmostApplication?.processIdentifier==previousForeground,!app.isActive else{throw Stop("foreground_changed")}
   let idle=CGEventSource.secondsSinceLastEventType(.hidSystemState,eventType:CGEventType(rawValue:UInt32.max)!)
   guard idle.isFinite,idle>=Double(binding["idle_seconds"] as? Int ?? 15) else{throw Stop("user_active")}
  }
 }
 // Only the first navigation step changes focus. Later steps require the
 // expected foreground window/dialog; they never silently move focus back.
 if mode=="navigate" && ["complete","open"].contains(phase) && !backgroundMode {
  let activation=binding["activation_policy"] as? String ?? "immediate"
  let idleGate=binding["idle_gate"] as? String ?? "initial"
  guard ["initial","continuation"].contains(idleGate) else{throw Stop("idle_gate_invalid")}
  if activation != "immediate" {
   // Check idle once at transaction admission, not after our own posted keys.
   // Continuation is sealed by the authority and still requires foreground.
   if idleGate=="initial" {
    let idle=CGEventSource.secondsSinceLastEventType(.hidSystemState,eventType:CGEventType(rawValue:UInt32.max)!)
    guard idle.isFinite,idle >= Double(binding["idle_seconds"] as? Int ?? 15) else{throw Stop("user_active")}
   } else {guard app.isActive else{throw Stop("foreground_changed")}}
   if activation=="foreground_only" && !app.isActive {throw Stop("foreground_required")}
  }
  try authority(true)
  if attr(target,kAXMinimizedAttribute) as? Bool==true {
   guard AXUIElementSetAttributeValue(target,kAXMinimizedAttribute as CFString,kCFBooleanFalse) == .success else{throw Stop("restore_main_window_failed")}
  }
  guard app.isActive || app.activate(options:[]) else{throw Stop("activation_failed")}
  guard AXUIElementPerformAction(target,kAXRaiseAction as CFString) == .success else{throw Stop("raise_failed")}
  // Activation/raise is asynchronous. Wait for the actual key window rather
  // than treating the activation request's return value as foreground proof.
  let activationDeadline=Date().addingTimeInterval(0.8)
  while Date()<activationDeadline {
   if app.isActive,let focused=attr(root,kAXFocusedWindowAttribute),
      CFGetTypeID(focused)==AXUIElementGetTypeID(),label(focused as! AXUIElement)==title {break}
   RunLoop.current.run(until:Date().addingTimeInterval(0.025))
  }
  guard app.isActive else{throw Stop("activation_unconfirmed")}
 }
 func verify(_ dialog:Bool=false) throws {
  guard !app.isTerminated,backgroundMode || app.isActive else{throw Stop("foreground_changed")}
  try verifyActivity()
  let rows=(CGWindowListCopyWindowInfo(.optionOnScreenOnly,kCGNullWindowID) as? [[String:Any]] ?? []).filter{($0[kCGWindowOwnerPID as String] as? Int)==pid && ($0[kCGWindowLayer as String] as? Int)==0}
  guard rows.contains(where:{($0[kCGWindowNumber as String] as? Int)==windowID && ($0[kCGWindowBounds as String] as? NSDictionary)==bounds}) else{throw Stop("window_epoch_or_geometry_changed")}
  guard let focused=attr(root,kAXFocusedWindowAttribute),CFGetTypeID(focused)==AXUIElementGetTypeID() else{throw Stop("focused_window_unavailable")}
  let current=focused as! AXUIElement
  if dialog {
   let subrole=attr(current,kAXSubroleAttribute) as? String ?? ""
   shell=["focused_is_dialog":subrole=="AXDialog","focused_title_empty":label(current).isEmpty,"ax_window_count":windows().count]
   guard subrole=="AXDialog",label(current).isEmpty else{throw Stop("search_dialog_unconfirmed")}
  } else {
   // CGWindowList can put a tooltip/auxiliary window first. The AX key-window
   // identity and the pinned CG window/geometry above are the actual witness.
   guard label(current)==title,CFEqual(current,target) else{throw Stop("main_window_not_foreground")}
  }
 }
 func key(_ code:CGKeyCode,_ flags:CGEventFlags=[],dialog:Bool=false) throws {
  // Revalidate a claimed permit locally on every key. Prepared read-only
  // selection/copy has a fresh server check at most one second apart; final
  // text/Return always requires a new server claim immediately beforehand.
  if claimedPermit || Date().timeIntervalSince(lastAuthorityCheck)>1 {try proof()}
  try verify(dialog)
  if claimedPermit || Date().timeIntervalSince(lastAuthorityCheck)>1 {try proof()}
  for down in [true,false] {
   // Preserve the device-validated foreground input source. Experimental
   // background events must not change normal WeChat keyboard semantics.
   guard let event=CGEvent(keyboardEventSource:backgroundMode ? CGEventSource(stateID:.privateState) : nil,virtualKey:code,keyDown:down) else{throw Stop("event_unavailable")}
   event.flags=flags;event.postToPid(pid_t(pid));usleep(25000)
  }
 }
 try verify(mode=="navigate" && ["query","select"].contains(phase))
 // Non-send transactions claim before their first UI/clipboard operation.
 // Send keeps all input comparisons in preflight and claims at final Return.
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
  let copyDeadline=Date().addingTimeInterval(0.8)
  while Date()<copyDeadline {
   try verify(dialog);try proof()
   if pb.changeCount != owned {
    if pb.string(forType:.string)==text {owned=pb.changeCount;return true}
    return false
   }
   RunLoop.current.run(until:Date().addingTimeInterval(0.025))
  }
  // Unknown clipboard data is never disclosed or assumed to be our epoch.
  throw Stop("copy_result_timeout")
 }
 var originalPointer:CGPoint?=nil,parkedPointer:CGPoint?=nil
 func pointer() throws -> CGPoint {guard let event=CGEvent(source:nil) else{throw Stop("pointer_unavailable")};return event.location}
 func samePoint(_ a:CGPoint,_ b:CGPoint)->Bool {abs(a.x-b.x)<1.5 && abs(a.y-b.y)<1.5}
 defer {
  // Do not move a pointer that the owner has since used. No click is posted.
  if let before=originalPointer,let ownedPoint=parkedPointer,let current=try? pointer(),samePoint(current,ownedPoint) {
   CGWarpMouseCursorPosition(before)
  }
 }
 func protectSearchPointer() throws {
  if backgroundMode {return}
  try verify(true);try proof()
  guard let focused=attr(root,kAXFocusedWindowAttribute),CFGetTypeID(focused)==AXUIElementGetTypeID(),
        let position=attr(focused as! AXUIElement,kAXPositionAttribute),CFGetTypeID(position)==AXValueGetTypeID(),
        let size=attr(focused as! AXUIElement,kAXSizeAttribute),CFGetTypeID(size)==AXValueGetTypeID() else{throw Stop("search_geometry_required")}
  var origin=CGPoint.zero;var dimensions=CGSize.zero
  guard AXValueGetValue(position as! AXValue,.cgPoint,&origin),AXValueGetValue(size as! AXValue,.cgSize,&dimensions),dimensions.width>0,dimensions.height>0 else{throw Stop("search_geometry_required")}
  let rect=CGRect(origin:origin,size:dimensions);let current=try pointer();originalPointer=current
  if !rect.contains(current) {parkedPointer=current;return}
  guard let x=bounds["X"] as? Double,let y=bounds["Y"] as? Double,let width=bounds["Width"] as? Double,let height=bounds["Height"] as? Double else{throw Stop("main_geometry_required")}
  let candidates=[CGPoint(x:x+16,y:y+16),CGPoint(x:x+16,y:y+height-16),CGPoint(x:x+width-16,y:y+16)]
  guard let safe=candidates.first(where:{!rect.insetBy(dx:-8,dy:-8).contains($0)}) else{throw Stop("search_pointer_parking_unavailable")}
  guard CGWarpMouseCursorPosition(safe) == .success else{throw Stop("search_pointer_parking_failed")}
  parkedPointer=safe
  if let move=CGEvent(mouseEventSource:nil,mouseType:.mouseMoved,mouseCursorPosition:safe,mouseButton:.left) {move.postToPid(pid_t(pid))}
 }
 if mode=="navigate" {
  guard text.utf8.count<=512,!text.contains("\n"),!text.contains("\r") else{throw Stop("query_budget")}
  if ["complete","open"].contains(phase) {
  guard let bar=attr(root,kAXMenuBarAttribute),CFGetTypeID(bar)==AXUIElementGetTypeID() else{throw Stop("menu_bar_missing")}
  let parents=children(bar as! AXUIElement).filter{label($0)=="编辑"}
  guard parents.count==1 else{throw Stop("edit_menu_ambiguous")}
  try proof();try verify()
  if !backgroundMode {guard AXUIElementPerformAction(parents[0],kAXPressAction as CFString) == .success else{throw Stop("menu_open_failed")}}
  let menus=children(parents[0]).filter{attr($0,kAXRoleAttribute) as? String=="AXMenu"}
  let entries=menus.flatMap{children($0)}.filter{label($0)=="搜索"}
  guard entries.count==1,attr(entries[0],kAXEnabledAttribute) as? Bool==true else{throw Stop("search_entry_ambiguous")}
  try proof()
  if backgroundMode {
   guard (attr(entries[0],kAXMenuItemCmdCharAttribute) as? String)?.lowercased()=="f",
         (attr(entries[0],kAXMenuItemCmdModifiersAttribute) as? Int)==0 else{throw Stop("background_search_shortcut_unconfirmed")}
   try key(3,.maskCommand)
  } else {guard AXUIElementPerformAction(entries[0],kAXPressAction as CFString) == .success else{throw Stop("search_open_failed")}}
  let searchDeadline=Date().addingTimeInterval(2)
  while Date()<searchDeadline {RunLoop.current.run(until:Date().addingTimeInterval(0.05));if (try? verify(true)) != nil {break}}
  try verify(true)
  if phase=="open" {return ["navigation_step_complete":true,"send_invoked":false]}
  }
  try protectSearchPointer()
  if ["complete","query"].contains(phase) {
  try key(0,.maskCommand,dialog:true);try put(text)
  if phase=="query" {try authority(true)}
  try key(9,.maskCommand,dialog:true)
  // Do not Cmd+A/C here: manipulating the search editor after paste changes
  // WeChat's selected result, and Return can then open message-history search.
  // Check the exact clipboard epoch instead. The controller MUST independently
  // verify the fresh SearchRecent stable recipient before touching chat input.
  guard pb.changeCount==owned,pb.string(forType:.string)==text else{throw Stop("search_clipboard_changed")}
  // Search results are asynchronous. A mouse hovering the results can switch
  // the active row to chat-history search while they appear. Keep it outside,
  // wait for the ordinary search UI, and cancel if the owner moves it.
  let settle=Date().addingTimeInterval(0.85)
  while Date()<settle {
   try verify(true);try proof()
   if !backgroundMode {guard let parked=parkedPointer,samePoint(try pointer(),parked) else{throw Stop("search_pointer_changed")}}
   RunLoop.current.run(until:Date().addingTimeInterval(0.025))
  }
  if phase=="query" {return ["navigation_step_complete":true,"query_input_submitted":true,"send_invoked":false]}
  }
  if phase=="select" {
   try authority(true)
  }
  // This Return is allowed only in the new untitled search dialog, never a chat.
  try verify(true);if !backgroundMode {guard let parked=parkedPointer,samePoint(try pointer(),parked) else{throw Stop("search_pointer_changed")}};navigated=true;try key(36,dialog:true)
  let selectionDeadline=Date().addingTimeInterval(0.8)
  while Date()<selectionDeadline {
   if let focused=attr(root,kAXFocusedWindowAttribute),CFGetTypeID(focused)==AXUIElementGetTypeID() {
    let selectedTitle=label(focused as! AXUIElement)
    if selectedTitle=="搜索聊天记录" {throw Stop("history_search_selected_no_input")}
    if selectedTitle==title {break}
   }
   RunLoop.current.run(until:Date().addingTimeInterval(0.025))
  }
  try verify()
  return ["navigation_invoked":true,"query_input_submitted":true,"main_window_verified":true,"recipient_verified":false,"send_invoked":false]
 }
 if mode=="stage_draft" {
  // SearchRecent proves the recipient, not whether the live composer is empty.
  // Inspect the native edit commands after selecting the composer contents;
  // never infer live input from an old SessionTable draft or placeholder text.
  try authority(true);try key(0,.maskCommand)
  guard let bar=attr(root,kAXMenuBarAttribute),CFGetTypeID(bar)==AXUIElementGetTypeID() else{throw Stop("menu_bar_missing")}
  let edits=children(bar as! AXUIElement).filter{label($0)=="编辑"}
  guard edits.count==1,AXUIElementPerformAction(edits[0],kAXPressAction as CFString) == .success else{throw Stop("edit_menu_unavailable")}
  let menus=children(edits[0]).filter{attr($0,kAXRoleAttribute) as? String=="AXMenu"}
  let entries=menus.flatMap{children($0)}
  func enabled(_ name:String)->Bool? {
   let values=entries.filter{label($0)==name};return values.count==1 ? attr(values[0],kAXEnabledAttribute) as? Bool : nil
  }
  let cut=enabled("剪切"),copy=enabled("拷贝"),paste=enabled("粘贴")
  guard menus.count==1,AXUIElementPerformAction(menus[0],kAXCancelAction as CFString) == .success else{throw Stop("edit_menu_close_failed")}
  try verify();try proof()
  let replacing=binding["draft_policy"] as? String=="replace"
  guard paste==true,cut != nil,copy != nil else{throw Stop("composer_state_unconfirmed")}
  if !replacing && (cut != false || copy != false) {throw Stop("existing_input_preserved")}
  if replacing {try key(51)} else {try key(124)}
  try put(text);try verify();staged=true;try key(9,.maskCommand)
  RunLoop.current.run(until:Date().addingTimeInterval(0.2))
 }
 if mode=="read_draft" {try authority(true)}
 let exact=try echo()
 if mode=="send" && exact {
  guard try echo() else{throw Stop("draft_changed_before_commit")}
  try verify();guard pb.changeCount==owned else{throw Stop("clipboard_changed_before_commit")}
  // Keep the previously qualified foreground Return path. Do not add another
  // discovery/submit route to a send transaction or retry an uncertain action.
  try authority(true);try authority(false,true)
  guard try echo() else{throw Stop("draft_changed_after_commit_claim")}
  try verify();try proof()
  submitted=true;submitMethod="keyboard_return";try key(36)
 }
 return ["draft_match":exact,"stage_invoked":staged,"send_invoked":submitted,"delivery_confirmed":false,"content_disclosed":false,
         "submit_method":submitMethod,"started_background":backgroundMode,"foreground_unchanged":NSWorkspace.shared.frontmostApplication?.processIdentifier==previousForeground]
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
   (result["draft_match"] as? Bool==true || result["navigation_invoked"] as? Bool==true || result["navigation_step_complete"] as? Bool==true)
  output["authority_receipt_recorded"]=endpoint.withCString{e in proof.withCString{p in evidence.withCString{d in axr_authority_observe(e,p,verified ? 1:0,d)}}}==1
 }
 emit(output)
}
do {finish(try run())}catch let error as Stop{finish(["error":error.code,"stage_invoked":staged,"send_invoked":submitted,"navigation_invoked":navigated,"shell":shell,"content_disclosed":false])}catch{finish(["error":"operation_failed","stage_invoked":staged,"send_invoked":submitted,"content_disclosed":false])}
