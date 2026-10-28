// SPDX-License-Identifier: MIT
// WeChat-specific, ordinary-user UI Automation helper; each invocation owns a STA.
#define NOMINMAX
#include <windows.h>
#include <UIAutomation.h>
#include <wrl/client.h>
#include <fstream>
#include <iostream>
#include <chrono>
#include <thread>
#include <algorithm>
#include <map>
#include <wtsapi32.h>
#include "SendPolicy.hpp"
#include "axr/Core.hpp"
#include "axr/Commit.h"
#include "axr/WindowsNavigation.hpp"
using Microsoft::WRL::ComPtr;
using Stellaria::AXR::Json;
static std::string Utf8(const std::wstring& s){if(s.empty())return {};int n=WideCharToMultiByte(CP_UTF8,0,s.data(),int(s.size()),nullptr,0,nullptr,nullptr);std::string v(n,'\0');WideCharToMultiByte(CP_UTF8,0,s.data(),int(s.size()),v.data(),n,nullptr,nullptr);return v;}
static std::string Name(IUIAutomationElement* e){BSTR b=nullptr;if(FAILED(e->get_CurrentName(&b)))return {};std::string v=Utf8(b?std::wstring(b,SysStringLen(b)):L"");SysFreeString(b);return v;}
static std::wstring Wide(const std::string& s){if(s.empty())return {};int n=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s.data(),int(s.size()),nullptr,0);if(!n)throw std::runtime_error("invalid_utf8");std::wstring v(n,L'\0');MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s.data(),int(s.size()),v.data(),n);return v;}
static std::string Value(IUIAutomationElement* e){ComPtr<IUIAutomationValuePattern> p;if(SUCCEEDED(e->GetCurrentPatternAs(UIA_ValuePatternId,IID_PPV_ARGS(&p)))){BSTR b=nullptr;if(SUCCEEDED(p->get_CurrentValue(&b))){auto v=Utf8(b?std::wstring(b,SysStringLen(b)):L"");SysFreeString(b);return v;}}return Name(e);}
static std::string Id(IUIAutomationElement* e){BSTR b=nullptr;if(FAILED(e->get_CurrentAutomationId(&b)))return {};std::string v=Utf8(b?std::wstring(b,SysStringLen(b)):L"");SysFreeString(b);return v;}
static std::string Draft(IUIAutomationValuePattern* p){BSTR b=nullptr;if(FAILED(p->get_CurrentValue(&b)))throw std::runtime_error("draft_value_unavailable");auto text=Utf8(b?std::wstring(b,SysStringLen(b)):L"");SysFreeString(b);return text;}
static std::string Birth(HANDLE process){FILETIME created,exited,kernel,user;if(!GetProcessTimes(process,&created,&exited,&kernel,&user))throw std::runtime_error("wechat_process_birth_unavailable");ULARGE_INTEGER value;value.LowPart=created.dwLowDateTime;value.HighPart=created.dwHighDateTime;return std::to_string(value.QuadPart);}
static void SetValue(IUIAutomationValuePattern* input,const std::string& text){auto wide=Wide(text);BSTR prepared=SysAllocStringLen(wide.data(),UINT(wide.size()));if(!prepared)throw std::runtime_error("draft_allocation_failed");auto changed=input->SetValue(prepared);SysFreeString(prepared);if(FAILED(changed))throw std::runtime_error("input_prepare_failed");}
static std::string Role(IUIAutomationElement* e){CONTROLTYPEID t=0;e->get_CurrentControlType(&t);switch(t){case UIA_TextControlTypeId:return "Text";case UIA_EditControlTypeId:return "Edit";case UIA_ListControlTypeId:return "List";case UIA_ButtonControlTypeId:return "Button";default:return "Other";}}
static std::vector<ComPtr<IUIAutomationElement>> Children(IUIAutomationTreeWalker* walker,IUIAutomationElement* e){std::vector<ComPtr<IUIAutomationElement>> v;ComPtr<IUIAutomationElement> child;walker->GetFirstChildElement(e,&child);while(child&&v.size()<500){v.push_back(child);ComPtr<IUIAutomationElement> next;walker->GetNextSiblingElement(child.Get(),&next);child=next;}return v;}
static ComPtr<IUIAutomationElement> Path(IUIAutomationTreeWalker* walker,ComPtr<IUIAutomationElement> root,const Json& parts){for(const auto& n:parts){auto children=Children(walker,root.Get());int index=n.get<int>();if(index<0||std::size_t(index)>=children.size())throw std::runtime_error("selector_changed");root=children[index];}return root;}
struct Candidate{std::vector<HWND> windows;};
static BOOL CALLBACK Enum(HWND window,LPARAM param){DWORD pid=0;GetWindowThreadProcessId(window,&pid);HANDLE p=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);if(!p)return TRUE;wchar_t path[32768];DWORD len=32768;bool ok=QueryFullProcessImageNameW(p,0,path,&len);CloseHandle(p);if(ok&&IsWindowVisible(window)){auto file=std::filesystem::path(std::wstring(path,len)).filename().wstring();if(file==L"WeChat.exe"||file==L"Weixin.exe")reinterpret_cast<Candidate*>(param)->windows.push_back(window);}return TRUE;}
static bool authorityClaimed=false,sendInvoked=false;
static WeChat::Activity Activity(HWND window) {
    WeChat::Activity facts;
    DWORD session=0, bytes=0;LPWSTR state=nullptr;
    bool active=ProcessIdToSessionId(GetCurrentProcessId(),&session) && session!=0 &&
        WTSQuerySessionInformationW(WTS_CURRENT_SERVER_HANDLE,session,WTSConnectState,&state,&bytes) &&
        bytes==sizeof(WTS_CONNECTSTATE_CLASS) && *reinterpret_cast<WTS_CONNECTSTATE_CLASS*>(state)==WTSActive;
    if(state)WTSFreeMemory(state);
    HDESK desktop=OpenInputDesktop(0,FALSE,DESKTOP_READOBJECTS);
    if(desktop){
        wchar_t input[256]{},current[256]{};DWORD needed=0;
        facts.desktop=active && GetUserObjectInformationW(desktop,UOI_NAME,input,sizeof(input),&needed) &&
            GetUserObjectInformationW(GetThreadDesktop(GetCurrentThreadId()),UOI_NAME,current,sizeof(current),&needed) &&
            _wcsicmp(input,L"Default")==0 && _wcsicmp(input,current)==0 && GetForegroundWindow()!=nullptr;
        CloseDesktop(desktop);
    }
    facts.foreground=facts.desktop && GetForegroundWindow()==window;
    LASTINPUTINFO info{sizeof(LASTINPUTINFO)};
    if(facts.desktop && GetLastInputInfo(&info)){
        // Unsigned subtraction handles DWORD rollover; implausible ages fail.
        facts.idle=WeChat::IdleSeconds(GetTickCount64(),info.dwTime);
    }
    return facts;
}
static void Authority(const Json& request,bool claim=false){
    const auto& context=request.at("guard_context");
    Json scope={{"operations",Json::array({request.at("operation")})},
        {"resource",{{"platform","wechat"},{"account_id",request.at("account")},{"conversation_id",request.at("identity")}}},
        {"text",request.at("expected_text")},{"visual_binding",request.at("visual_binding")}};
    auto endpoint=context.at("authority_endpoint").get<std::string>(),proof=context.at("proof").get<std::string>(),encoded=scope.dump();
    int allowed=claim&&!authorityClaimed?axr_authority_claim(endpoint.c_str(),proof.c_str(),encoded.c_str()):axr_authority_preflight(endpoint.c_str(),proof.c_str(),encoded.c_str());
    if(allowed!=1)throw std::runtime_error("authority_or_scope_changed");
    if(claim)authorityClaimed=true;
}
static Json Main(const Json& req,const Json* authority=nullptr){
    Candidate candidate;EnumWindows(Enum,reinterpret_cast<LPARAM>(&candidate));
    std::string op=req.at("op");
    if(op=="status")return {{"running",candidate.windows.size()==1},{"ambiguous_process",candidate.windows.size()>1},{"accessibility",true}};
    if(op=="readiness"&&candidate.windows.size()!=1)return {{"running",false},{"ambiguous_process",candidate.windows.size()>1},{"accessibility",false}};
    if(candidate.windows.size()!=1)throw std::runtime_error("wechat_window_missing_or_ambiguous");
    HWND window=candidate.windows[0];DWORD pid=0;GetWindowThreadProcessId(window,&pid);
    HANDLE p=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);wchar_t exe[32768];DWORD size=32768;
    if(!p||!QueryFullProcessImageNameW(p,0,exe,&size)){if(p)CloseHandle(p);throw std::runtime_error("wechat_identity_unavailable");}
    std::string birth;try{birth=Birth(p);}catch(...){CloseHandle(p);throw;}CloseHandle(p);
    std::ifstream file(std::filesystem::path(std::wstring(exe,size)),std::ios::binary);
    if(!file||std::filesystem::file_size(std::filesystem::path(std::wstring(exe,size)))>512ull*1024*1024)throw std::runtime_error("executable_identity_read_failed");
    std::string bytes((std::istreambuf_iterator<char>(file)),{});
    if(req.value("executable_hash",std::string{})!=Stellaria::AXR::Digest(bytes))throw std::runtime_error("wechat_executable_not_owner_pinned");
    ComPtr<IUIAutomation> automation;if(FAILED(CoCreateInstance(CLSID_CUIAutomation,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&automation))))throw std::runtime_error("uia_unavailable");
    ComPtr<IUIAutomationElement> root;automation->ElementFromHandle(window,&root);
    ComPtr<IUIAutomationTreeWalker> walker;automation->get_ControlViewWalker(&walker);
    if(!root||!walker)throw std::runtime_error("uia_tree_unavailable");
    // Pre-consent metadata only: no names, values, tree walk, focus or input.
    if(op=="readiness")return {{"running",true},{"ambiguous_process",false},{"accessibility",true}};
    Json nodes=Json::array();std::size_t remaining=64000;
    std::function<void(ComPtr<IUIAutomationElement>,Json,unsigned,bool)> walk;
    walk=[&](ComPtr<IUIAutomationElement> node,Json path,unsigned depth,bool read){
        if(depth>16||nodes.size()>=500)return;auto children=Children(walker.Get(),node.Get());
        Json item{{"path",path},{"role",Role(node.Get())},{"identifier",Id(node.Get())},{"children",children.size()}};
        if(read){
            auto name=Name(node.Get());
            auto length=std::min<std::size_t>({name.size(),4000,remaining});
            // Avoid splitting a UTF-8 continuation when enforcing the byte budget.
            while(length<name.size()&&length>0&&(static_cast<unsigned char>(name[length])&0xC0)==0x80)--length;
            item["value"]=name.substr(0,length);item["truncated"]=length<name.size();remaining-=length;
        }
        nodes.push_back(item);for(std::size_t i=0;i<children.size();++i){auto childPath=path;childPath.push_back(i);walk(children[i],childPath,depth+1,read);}
    };
    if(op=="structure"){walk(root,Json::array(),0,false);return {{"nodes",nodes},{"pid",pid},{"text_redacted",true}};}
    if(authority&&op=="binding"){
        Authority(*authority);
        if(Value(Path(walker.Get(),root,req.at("account_path")).Get())!=req.at("expected_account").get<std::string>())throw std::runtime_error("runtime_account_witness_changed");
        Authority(*authority,true);
        auto binding=authority->at("visual_binding");
        binding["expected_pid"]=pid;binding["window_id"]=reinterpret_cast<std::uintptr_t>(window);binding["process_birth"]=birth;
        auto facts=Activity(window);
        return {{"binding",binding},{"activity",{{"desktop_available",facts.desktop},{"application_active",facts.foreground},{"idle_seconds",facts.idle>=0?Json(facts.idle):Json(nullptr)}}},
            {"main_window_verified",true},{"send_invoked",false},{"content_disclosed",false}};
    }
    if(req.at("expected_pid").get<DWORD>()!=pid)throw std::runtime_error("application_epoch_changed");
    if(authority&&(req.at("window_id").get<std::uintptr_t>()!=reinterpret_cast<std::uintptr_t>(window)||req.at("process_birth")!=birth))throw std::runtime_error("main_window_instance_changed");
    ComPtr<IUIAutomationElement> boundTarget;
    bool timingAdmitted=false;
    auto currentForeground=[&]{
        if(authority)WeChat::NeedsActivation(req.value("activation_policy",std::string("immediate")),
            req.value("idle_seconds",15),false,Activity(window));
    };
    auto verify=[&]{
        if(authority)Authority(*authority);
        else {const auto& control=req.at("guard_context");
        Json scope={{"resource",{{"platform",req.at("expected_platform")},{"account_id",req.at("expected_account")},{"conversation_id",req.at("expected_identity")}}},
                    {"operations",op=="send_text"?Json::array({"messages.send"}):Json::array({"messages.read","messages.search"})}};
        if(op=="send_text")scope["text"]=req.at("text");
        if(!axr_check_scoped_commit(control.at("store").get<std::string>().c_str(),control.at("proof").get<std::string>().c_str(),scope.dump().c_str()))throw std::runtime_error("authority_or_requested_scope_changed");}
        if(op!="navigate"&&Value(Path(walker.Get(),root,req.at("header_path")).Get())!=req.at("expected_title").get<std::string>())throw std::runtime_error("target_identity_changed");
        DWORD current=0;GetWindowThreadProcessId(window,&current);if(current!=pid)throw std::runtime_error("application_epoch_changed");
        if(authority){HANDLE currentProcess=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);if(!currentProcess)throw std::runtime_error("application_epoch_changed");std::string currentBirth;try{currentBirth=Birth(currentProcess);}catch(...){CloseHandle(currentProcess);throw;}CloseHandle(currentProcess);if(currentBirth!=birth)throw std::runtime_error("application_epoch_changed");}
        if(boundTarget){BOOL same=FALSE;auto fresh=Path(walker.Get(),root,req.at("path"));if(FAILED(automation->CompareElements(boundTarget.Get(),fresh.Get(),&same))||!same)throw std::runtime_error("control_epoch_changed");}
        if(op=="send_text"||op=="read"||authority){
            for(auto pair:{std::pair{"account_path","expected_account"},std::pair{"identity_path","expected_identity"}}){
                if(op=="navigate"&&std::string(pair.first)=="identity_path")continue;
                auto expected=req.at(pair.second).get<std::string>();
                if(expected.empty()||Value(Path(walker.Get(),root,req.at(pair.first)).Get())!=expected)throw std::runtime_error("stable_identity_witness_changed");
            }
        }
        if(authority){
            const auto policy=req.value("activation_policy",std::string("immediate"));
            auto phase=req.value("idle_gate",std::string("initial"));
            if(phase!="initial" && phase!="continuation")throw std::runtime_error("idle_gate_invalid");
            bool initial=op=="navigate" && phase=="initial" && !timingAdmitted;
            bool activate=WeChat::NeedsActivation(policy,req.value("idle_seconds",15),initial,Activity(window));
            if(activate){
                // No simulated input, foreground-lock changes or focus retries.
                Authority(*authority,true);
                if(!SetForegroundWindow(window))throw std::runtime_error("foreground_activation_denied");
            }
            WeChat::NeedsActivation(policy,req.value("idle_seconds",15),false,Activity(window));
            timingAdmitted=true;
        }
    };
    verify();
    if(authority&&op=="navigate"){
        auto search=Path(walker.Get(),root,req.at("search_path"));ComPtr<IUIAutomationValuePattern> input;
        if(FAILED(search->GetCurrentPatternAs(UIA_ValuePatternId,IID_PPV_ARGS(&input))))throw std::runtime_error("search_input_unavailable");
        // Preserve the user's unfinished search as well as their chat draft.
        if(!Draft(input.Get()).empty())throw std::runtime_error("existing_search_never_overwrite");
        verify();Authority(*authority,true);auto query=req.at("text").get<std::string>();currentForeground();SetValue(input.Get(),query);
        if(Draft(input.Get())!=query)throw std::runtime_error("search_query_echo_changed");
        verify();auto selected=Path(walker.Get(),root,req.at("search_result_path"));
        if(Value(selected.Get())!=req.at("search_result_title").get<std::string>())throw std::runtime_error("search_result_label_changed");
        ComPtr<IUIAutomationSelectionItemPattern> selection;ComPtr<IUIAutomationInvokePattern> invoke;
        bool select=SUCCEEDED(selected->GetCurrentPatternAs(UIA_SelectionItemPatternId,IID_PPV_ARGS(&selection)));
        if(!select&&FAILED(selected->GetCurrentPatternAs(UIA_InvokePatternId,IID_PPV_ARGS(&invoke))))throw std::runtime_error("search_result_action_unavailable");
        verify();BOOL same=FALSE;auto fresh=Path(walker.Get(),root,req.at("search_result_path"));
        if(FAILED(automation->CompareElements(selected.Get(),fresh.Get(),&same))||!same||Draft(input.Get())!=query)throw std::runtime_error("search_result_epoch_changed");
        currentForeground();auto status=select?selection->Select():invoke->Invoke();if(FAILED(status))throw std::runtime_error("search_selection_unknown");
        verify();
        if(Value(Path(walker.Get(),root,req.at("header_path")).Get())!=req.at("expected_title").get<std::string>()||
           Value(Path(walker.Get(),root,req.at("identity_path")).Get())!=req.at("expected_identity").get<std::string>())throw std::runtime_error("selected_conversation_witness_changed");
        return {{"navigation_invoked",true},{"query_echo_match",true},{"main_window_verified",true},{"send_invoked",false},{"content_disclosed",false}};
    }
    auto target=Path(walker.Get(),root,req.at("path"));boundTarget=target;verify();
    if(authority){
        auto text=req.at("text").get<std::string>();
        ComPtr<IUIAutomationValuePattern> input;
        if(FAILED(target->GetCurrentPatternAs(UIA_ValuePatternId,IID_PPV_ARGS(&input))))throw std::runtime_error("input_unavailable");
        if(op=="stage_draft"){
            auto policy=req.value("draft_policy",std::string("preserve"));
            if(policy!="preserve" && policy!="replace")throw std::runtime_error("draft_policy_invalid");
            auto prior=Draft(input.Get());
            if(!prior.empty() && policy!="replace")throw std::runtime_error("existing_draft_never_overwrite");
            verify();Authority(*authority,true);
            if(Draft(input.Get())!=prior)throw std::runtime_error("draft_changed_before_prepare");
            auto wide=Wide(text);BSTR prepared=SysAllocStringLen(wide.data(),UINT(wide.size()));
            if(!prepared)throw std::runtime_error("draft_allocation_failed");
            try{currentForeground();}catch(...){SysFreeString(prepared);throw;}
            auto changed=input->SetValue(prepared);SysFreeString(prepared);
            if(FAILED(changed))throw std::runtime_error("draft_prepare_failed");
            verify();return {{"draft_match",Draft(input.Get())==text},{"stage_invoked",true},{"send_invoked",false},{"content_disclosed",false}};
        }
        if(op=="read_draft"){
            Authority(*authority,true);bool exact=Draft(input.Get())==text;verify();
            return {{"draft_match",exact},{"send_invoked",false},{"content_disclosed",false}};
        }
        if(op=="commit_draft"){
            if(Draft(input.Get())!=text)throw std::runtime_error("exact_draft_required");
            auto send=Path(walker.Get(),root,req.at("send_path"));ComPtr<IUIAutomationInvokePattern> invoke;
            if(FAILED(send->GetCurrentPatternAs(UIA_InvokePatternId,IID_PPV_ARGS(&invoke))))throw std::runtime_error("send_action_unavailable");
            verify();BOOL same=FALSE;auto current=Path(walker.Get(),root,req.at("send_path"));
            if(FAILED(automation->CompareElements(send.Get(),current.Get(),&same))||!same||Draft(input.Get())!=text)
                throw std::runtime_error("draft_or_send_control_changed");
            // Claim only after both exact-input comparisons, immediately before
            // a single external invocation. Never retry an uncertain send.
            Authority(*authority,true);currentForeground();sendInvoked=true;
            if(FAILED(invoke->Invoke()))throw std::runtime_error("send_outcome_unknown");
            return {{"draft_match",true},{"send_invoked",true},{"delivery_confirmed",false},{"content_disclosed",false}};
        }
        throw std::runtime_error("authority_operation_denied");
    }
    if(op=="read"){walk(target,req.at("path"),0,true);verify();return {{"nodes",nodes},{"pid",pid},{"foreground",GetForegroundWindow()==window}};}
    if(op=="send_text"){
        auto text=req.at("text").get<std::string>();if(text.empty()||text.size()>8000)throw std::runtime_error("send_text_invalid");
        ComPtr<IUIAutomationValuePattern> input;
        if(FAILED(target->GetCurrentPatternAs(UIA_ValuePatternId,IID_PPV_ARGS(&input)))||!Draft(input.Get()).empty())throw std::runtime_error("input_unavailable_or_existing_draft");
        std::function<unsigned(ComPtr<IUIAutomationElement>,unsigned)> matches;
        unsigned visited=0;
        matches=[&](ComPtr<IUIAutomationElement> node,unsigned depth){if(depth>12||++visited>1500)throw std::runtime_error("message_witness_budget_exceeded");unsigned count=Value(node.Get())==text?1:0;for(auto& child:Children(walker.Get(),node.Get()))count+=matches(child,depth+1);return count;};
        auto before=matches(Path(walker.Get(),root,req.at("messages_path")),0);verify();
        auto wide=Wide(text);BSTR prepared=SysAllocStringLen(wide.data(),UINT(wide.size()));
        if(!prepared)throw std::runtime_error("draft_allocation_failed");
        HRESULT changed=input->SetValue(prepared);SysFreeString(prepared);
        if(FAILED(changed)||Draft(input.Get())!=text)throw std::runtime_error("draft_prepare_failed");
        verify();auto send=Path(walker.Get(),root,req.at("send_path"));ComPtr<IUIAutomationInvokePattern> invoke;
        if(FAILED(send->GetCurrentPatternAs(UIA_InvokePatternId,IID_PPV_ARGS(&invoke))))throw std::runtime_error("send_action_unavailable");
        verify();BOOL same=FALSE;auto freshSend=Path(walker.Get(),root,req.at("send_path"));
        if(FAILED(automation->CompareElements(send.Get(),freshSend.Get(),&same))||!same)throw std::runtime_error("send_control_epoch_changed");
        if(Draft(input.Get())!=text)throw std::runtime_error("draft_changed_before_commit");
        if(FAILED(invoke->Invoke()))throw std::runtime_error("send_action_unavailable");
        auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(2);
        while(std::chrono::steady_clock::now()<deadline){verify();visited=0;if(Draft(input.Get()).empty()&&matches(Path(walker.Get(),root,req.at("messages_path")),0)>before)
            return {{"verified",true},{"witness","new_client_bubble_and_empty_draft"},{"delivery_confirmed",false}};
            std::this_thread::sleep_for(std::chrono::milliseconds(50));}
        return {{"verified",false},{"invoked",true},{"delivery_confirmed",false}};
    }
    throw std::runtime_error("operation_denied");
}
static Json V2(const Json& request){
    if(!request.is_object()||request.size()!=7)throw std::runtime_error("authority_request_invalid");
    auto mode=request.at("mode").get<std::string>(),op=request.at("operation").get<std::string>();
    auto text=request.at("expected_text").get<std::string>();
    if(text.empty()||text.size()>16000||!request.at("visual_binding").is_object())throw std::runtime_error("authority_scope_invalid");
    std::map<std::string,std::string> operations={{"binding","status.read"},{"navigate","application.navigate"},{"stage_draft","application.draft"},{"read_draft","status.read"},{"send","messages.send"}};
    if(!operations.contains(mode)||operations.at(mode)!=op)throw std::runtime_error("authority_operation_mismatch");
    if(mode=="send"){
        const auto& binding=request.at("visual_binding");
        if(!binding.contains("recipient_assurance")||!binding["recipient_assurance"].is_string()||
           binding["recipient_assurance"]!="cached_exact_draft_and_fresh_search"||
           !binding.contains("recipient_witness")||!binding["recipient_witness"].is_string())
            throw std::runtime_error("recipient_witness_required");
        const auto witness=binding["recipient_witness"].get<std::string>();
        if(witness.size()!=64||!std::all_of(witness.begin(),witness.end(),[](unsigned char ch){return (ch>='0'&&ch<='9')||(ch>='a'&&ch<='f');}))
            throw std::runtime_error("recipient_witness_required");
    }
    Authority(request);
    auto req=request.at("visual_binding");req["op"]=mode=="send"?"commit_draft":mode;
    if(req.contains("expected_account")&&req.at("expected_account")!=request.at("account"))throw std::runtime_error("authority_account_mismatch");
    if(mode!="navigate"&&mode!="binding"&&req.contains("expected_identity")&&req.at("expected_identity")!=request.at("identity"))throw std::runtime_error("authority_recipient_mismatch");
    req["text"]=text;req["expected_account"]=request.at("account");
    if(mode!="navigate")req["expected_identity"]=request.at("identity");
    return Main(req,&request);
}
static Json Readiness(const Json& request){
    if(!request.is_object()||request.size()!=2||request.at("mode")!="readiness"||!request.at("executable_hash").is_string())
        throw std::runtime_error("readiness_request_invalid");
    auto pin=request.at("executable_hash").get<std::string>();
    if(pin.size()!=64||pin.find_first_not_of("0123456789abcdef")!=std::string::npos)
        throw std::runtime_error("readiness_executable_pin_required");
    return Main({{"op","readiness"},{"executable_hash",pin}});
}
int main(int argc,char** argv){HRESULT initialized=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);Json result,request;
    bool pipeMode=argc==3&&std::string(argv[1])=="--authority-pipe",v2=pipeMode||(argc==2&&std::string(argv[1])=="--authority-v2");
    std::unique_ptr<Stellaria::AXR::WindowsNavigationPeer> peer;
    if(v2&&!pipeMode)std::cout<<Json{{"version",2},{"ready",true},{"input_received",false}}.dump()<<std::endl;
    try{if(argc!=1&&!v2)throw std::runtime_error("fixed_entrypoint_required");
        if(pipeMode)peer=std::make_unique<Stellaria::AXR::WindowsNavigationPeer>(argv[2]);
        if(FAILED(initialized))throw std::runtime_error("sta_initialization_failed");
        if(peer)request=peer->Request();else{std::string line;char ch;while(std::cin.get(ch)&&ch!='\n'){if(line.size()>=1024*1024)throw std::runtime_error("request_too_large");line.push_back(ch);}request=Json::parse(line);}
        // Only the authenticated protected-System pipe may use this exception
        // to task preflight. It cannot carry a scope, selectors or text.
        bool readiness=request.is_object()&&(request.value("mode",std::string{})=="readiness"||request.value("op",std::string{})=="readiness");
        if(readiness){if(!peer)throw std::runtime_error("readiness_authenticated_pipe_required");result=Readiness(request);}
        else result=v2?V2(request):Main(request);}
    catch(const nlohmann::json::exception&){result={{"error","invalid_request"}};}
    catch(const std::exception& e){result={{"error",e.what()}};}
    if(v2){result["send_invoked"]=sendInvoked;result["content_disclosed"]=false;
        if(authorityClaimed){auto& context=request.at("guard_context");auto endpoint=context.at("authority_endpoint").get<std::string>(),proof=context.at("proof").get<std::string>(),evidence=Stellaria::AXR::Digest(result.dump());
            bool verified=!sendInvoked&&!result.contains("error")&&(result.value("draft_match",false)||result.value("main_window_verified",false));
            result["authority_receipt_recorded"]=axr_authority_observe(endpoint.c_str(),proof.c_str(),verified?1:0,evidence.c_str())==1;}}
    if(peer){try{peer->Respond(result);}catch(...){if(SUCCEEDED(initialized))CoUninitialize();return 2;}}
    else std::cout<<result.dump()<<std::endl;
    if(SUCCEEDED(initialized))CoUninitialize();return 0;}
