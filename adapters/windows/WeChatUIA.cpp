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
#include "axr/Core.hpp"
#include "axr/Commit.h"
using Microsoft::WRL::ComPtr;
using Stellaria::AXR::Json;
static std::string Utf8(const std::wstring& s){if(s.empty())return {};int n=WideCharToMultiByte(CP_UTF8,0,s.data(),int(s.size()),nullptr,0,nullptr,nullptr);std::string v(n,'\0');WideCharToMultiByte(CP_UTF8,0,s.data(),int(s.size()),v.data(),n,nullptr,nullptr);return v;}
static std::string Name(IUIAutomationElement* e){BSTR b=nullptr;if(FAILED(e->get_CurrentName(&b)))return {};std::string v=Utf8(b?std::wstring(b,SysStringLen(b)):L"");SysFreeString(b);return v;}
static std::wstring Wide(const std::string& s){if(s.empty())return {};int n=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s.data(),int(s.size()),nullptr,0);if(!n)throw std::runtime_error("invalid_utf8");std::wstring v(n,L'\0');MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s.data(),int(s.size()),v.data(),n);return v;}
static std::string Value(IUIAutomationElement* e){ComPtr<IUIAutomationValuePattern> p;if(SUCCEEDED(e->GetCurrentPatternAs(UIA_ValuePatternId,IID_PPV_ARGS(&p)))){BSTR b=nullptr;if(SUCCEEDED(p->get_CurrentValue(&b))){auto v=Utf8(b?std::wstring(b,SysStringLen(b)):L"");SysFreeString(b);return v;}}return Name(e);}
static std::string Id(IUIAutomationElement* e){BSTR b=nullptr;if(FAILED(e->get_CurrentAutomationId(&b)))return {};std::string v=Utf8(b?std::wstring(b,SysStringLen(b)):L"");SysFreeString(b);return v;}
static std::string Draft(IUIAutomationValuePattern* p){BSTR b=nullptr;if(FAILED(p->get_CurrentValue(&b)))throw std::runtime_error("draft_value_unavailable");auto text=Utf8(b?std::wstring(b,SysStringLen(b)):L"");SysFreeString(b);return text;}
static std::string Role(IUIAutomationElement* e){CONTROLTYPEID t=0;e->get_CurrentControlType(&t);switch(t){case UIA_TextControlTypeId:return "Text";case UIA_EditControlTypeId:return "Edit";case UIA_ListControlTypeId:return "List";case UIA_ButtonControlTypeId:return "Button";default:return "Other";}}
static std::vector<ComPtr<IUIAutomationElement>> Children(IUIAutomationTreeWalker* walker,IUIAutomationElement* e){std::vector<ComPtr<IUIAutomationElement>> v;ComPtr<IUIAutomationElement> child;walker->GetFirstChildElement(e,&child);while(child&&v.size()<500){v.push_back(child);ComPtr<IUIAutomationElement> next;walker->GetNextSiblingElement(child.Get(),&next);child=next;}return v;}
static ComPtr<IUIAutomationElement> Path(IUIAutomationTreeWalker* walker,ComPtr<IUIAutomationElement> root,const Json& parts){for(const auto& n:parts){auto children=Children(walker,root.Get());int index=n.get<int>();if(index<0||std::size_t(index)>=children.size())throw std::runtime_error("selector_changed");root=children[index];}return root;}
struct Candidate{std::vector<HWND> windows;};
static BOOL CALLBACK Enum(HWND window,LPARAM param){DWORD pid=0;GetWindowThreadProcessId(window,&pid);HANDLE p=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);if(!p)return TRUE;wchar_t path[32768];DWORD len=32768;bool ok=QueryFullProcessImageNameW(p,0,path,&len);CloseHandle(p);if(ok&&IsWindowVisible(window)){auto file=std::filesystem::path(std::wstring(path,len)).filename().wstring();if(file==L"WeChat.exe"||file==L"Weixin.exe")reinterpret_cast<Candidate*>(param)->windows.push_back(window);}return TRUE;}
static bool authorityClaimed=false,sendInvoked=false;
static void Authority(const Json& request,bool claim=false){
    const auto& context=request.at("guard_context");
    Json scope={{"operations",Json::array({request.at("operation")})},
        {"resource",{{"platform","wechat"},{"account_id",request.at("account")},{"conversation_id",request.at("identity")}}},
        {"text",request.at("expected_text")},{"visual_binding",request.at("visual_binding")}};
    auto endpoint=context.at("authority_endpoint").get<std::string>(),proof=context.at("proof").get<std::string>(),encoded=scope.dump();
    int allowed=claim?axr_authority_claim(endpoint.c_str(),proof.c_str(),encoded.c_str()):axr_authority_preflight(endpoint.c_str(),proof.c_str(),encoded.c_str());
    if(allowed!=1)throw std::runtime_error("authority_or_scope_changed");
    if(claim)authorityClaimed=true;
}
static Json Main(const Json& req,const Json* authority=nullptr){
    Candidate candidate;EnumWindows(Enum,reinterpret_cast<LPARAM>(&candidate));
    std::string op=req.at("op");
    if(op=="status")return {{"running",candidate.windows.size()==1},{"ambiguous_process",candidate.windows.size()>1},{"accessibility",true}};
    if(candidate.windows.size()!=1)throw std::runtime_error("wechat_window_missing_or_ambiguous");
    HWND window=candidate.windows[0];DWORD pid=0;GetWindowThreadProcessId(window,&pid);
    HANDLE p=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);wchar_t exe[32768];DWORD size=32768;
    if(!p||!QueryFullProcessImageNameW(p,0,exe,&size)){if(p)CloseHandle(p);throw std::runtime_error("wechat_identity_unavailable");}CloseHandle(p);
    std::ifstream file(std::filesystem::path(std::wstring(exe,size)),std::ios::binary);
    if(!file||std::filesystem::file_size(std::filesystem::path(std::wstring(exe,size)))>512ull*1024*1024)throw std::runtime_error("executable_identity_read_failed");
    std::string bytes((std::istreambuf_iterator<char>(file)),{});
    if(req.value("executable_hash",std::string{})!=Stellaria::AXR::Digest(bytes))throw std::runtime_error("wechat_executable_not_owner_pinned");
    ComPtr<IUIAutomation> automation;if(FAILED(CoCreateInstance(CLSID_CUIAutomation,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&automation))))throw std::runtime_error("uia_unavailable");
    ComPtr<IUIAutomationElement> root;automation->ElementFromHandle(window,&root);
    ComPtr<IUIAutomationTreeWalker> walker;automation->get_ControlViewWalker(&walker);
    if(!root||!walker)throw std::runtime_error("uia_tree_unavailable");
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
    if(req.at("expected_pid").get<DWORD>()!=pid)throw std::runtime_error("application_epoch_changed");
    ComPtr<IUIAutomationElement> boundTarget;
    auto verify=[&]{
        if(authority)Authority(*authority);
        else {const auto& control=req.at("guard_context");
        Json scope={{"resource",{{"platform",req.at("expected_platform")},{"account_id",req.at("expected_account")},{"conversation_id",req.at("expected_identity")}}},
                    {"operations",op=="send_text"?Json::array({"messages.send"}):Json::array({"messages.read","messages.search"})}};
        if(op=="send_text")scope["text"]=req.at("text");
        if(!axr_check_scoped_commit(control.at("store").get<std::string>().c_str(),control.at("proof").get<std::string>().c_str(),scope.dump().c_str()))throw std::runtime_error("authority_or_requested_scope_changed");}
        if(Value(Path(walker.Get(),root,req.at("header_path")).Get())!=req.at("expected_title").get<std::string>())throw std::runtime_error("target_identity_changed");
        DWORD current=0;GetWindowThreadProcessId(window,&current);if(current!=pid)throw std::runtime_error("application_epoch_changed");
        if(boundTarget){BOOL same=FALSE;auto fresh=Path(walker.Get(),root,req.at("path"));if(FAILED(automation->CompareElements(boundTarget.Get(),fresh.Get(),&same))||!same)throw std::runtime_error("control_epoch_changed");}
        if(op=="send_text"||op=="read"||authority){
            for(auto pair:{std::pair{"account_path","expected_account"},std::pair{"identity_path","expected_identity"}}){
                auto expected=req.at(pair.second).get<std::string>();
                if(expected.empty()||Value(Path(walker.Get(),root,req.at(pair.first)).Get())!=expected)throw std::runtime_error("stable_identity_witness_changed");
            }
        }};
    verify();auto target=Path(walker.Get(),root,req.at("path"));boundTarget=target;verify();
    if(authority){
        auto text=req.at("text").get<std::string>();
        ComPtr<IUIAutomationValuePattern> input;
        if(FAILED(target->GetCurrentPatternAs(UIA_ValuePatternId,IID_PPV_ARGS(&input))))throw std::runtime_error("input_unavailable");
        if(op=="stage_draft"){
            if(!Draft(input.Get()).empty())throw std::runtime_error("existing_draft_never_overwrite");
            verify();Authority(*authority,true);
            auto wide=Wide(text);BSTR prepared=SysAllocStringLen(wide.data(),UINT(wide.size()));
            if(!prepared)throw std::runtime_error("draft_allocation_failed");
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
            Authority(*authority,true);sendInvoked=true;
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
    std::map<std::string,std::string> operations={{"navigate","application.navigate"},{"stage_draft","application.draft"},{"read_draft","status.read"},{"send","messages.send"}};
    if(!operations.contains(mode)||operations.at(mode)!=op)throw std::runtime_error("authority_operation_mismatch");
    Authority(request);
    if(mode=="navigate")throw std::runtime_error("windows_search_navigation_not_qualified");
    auto req=request.at("visual_binding");req["op"]=mode=="send"?"commit_draft":mode;
    req["text"]=text;req["expected_account"]=request.at("account");req["expected_identity"]=request.at("identity");
    return Main(req,&request);
}
int main(int argc,char** argv){HRESULT initialized=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);Json result,request;bool v2=argc==2&&std::string(argv[1])=="--authority-v2";
    if(v2)std::cout<<Json{{"version",2},{"ready",true},{"input_received",false}}.dump()<<std::endl;
    try{if(argc!=1&&!v2)throw std::runtime_error("fixed_entrypoint_required");if(FAILED(initialized))throw std::runtime_error("sta_initialization_failed");std::string line;char ch;while(std::cin.get(ch)&&ch!='\n'){if(line.size()>=1024*1024)throw std::runtime_error("request_too_large");line.push_back(ch);}request=Json::parse(line);result=v2?V2(request):Main(request);}
    catch(const nlohmann::json::exception&){result={{"error","invalid_request"}};}
    catch(const std::exception& e){result={{"error",e.what()}};}
    if(v2){result["send_invoked"]=sendInvoked;result["content_disclosed"]=false;
        if(authorityClaimed){auto& context=request.at("guard_context");auto endpoint=context.at("authority_endpoint").get<std::string>(),proof=context.at("proof").get<std::string>(),evidence=Stellaria::AXR::Digest(result.dump());
            bool verified=!sendInvoked&&!result.contains("error")&&result.value("draft_match",false);
            result["authority_receipt_recorded"]=axr_authority_observe(endpoint.c_str(),proof.c_str(),verified?1:0,evidence.c_str())==1;}}
    std::cout<<result.dump()<<std::endl;if(SUCCEEDED(initialized))CoUninitialize();return 0;}
