// SPDX-License-Identifier: MIT
// Explicit manual metadata experiment; never automatically discovers windows.
#include "windows_msaa_metadata.hpp"
#include <cstdint>
#include <iostream>
#include <string>

int main(int argc,char** argv){
    if(argc!=2)return 2;
    HWND window=nullptr;
    try{
        const std::string arg=argv[1];
        if(arg.empty()||!std::all_of(arg.begin(),arg.end(),[](char c){return c>='0'&&c<='9';}))return 2;
        std::size_t used=0;const auto value=std::stoull(arg,&used);
        if(used!=arg.size()||!value||value>UINTPTR_MAX)return 2;
        window=reinterpret_cast<HWND>(static_cast<std::uintptr_t>(value));
    }catch(...){return 2;}
    if(!IsWindow(window)||!IsWindowVisible(window))return 2;
    DWORD pid=0;GetWindowThreadProcessId(window,&pid);
    HANDLE process=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION|SYNCHRONIZE,FALSE,pid);
    if(!process)return 2;
    auto unchanged=[&]{DWORD current=0;GetWindowThreadProcessId(window,&current);
        return IsWindow(window)&&IsWindowVisible(window)&&current==pid&&WaitForSingleObject(process,0)==WAIT_TIMEOUT;};
    if(FAILED(CoInitializeEx(nullptr,COINIT_MULTITHREADED))){CloseHandle(process);return 2;}
    int code=2;
    {
        try{
            Microsoft::WRL::ComPtr<IAccessible> root;
            if(AccessibleObjectFromWindow(window,OBJID_CLIENT,IID_IAccessible,
                    reinterpret_cast<void**>(root.GetAddressOf()))!=S_OK||!root)
                throw std::runtime_error("msaa_root_unavailable");
            const auto result=WeChat::Diagnostic::MsaaMetadata(root.Get());
            if(!unchanged())throw std::runtime_error("msaa_window_changed");
            std::cout<<"{\"view\":\"msaa\",\"nodes\":"<<result.nodes<<",\"objects\":"<<result.objects
                <<",\"elements\":"<<result.elements<<",\"text_roles\":"<<result.textRoles
                <<",\"readonly_text_roles\":"<<result.readonlyTextRoles<<",\"unknown_roles\":"<<result.unknownRoles
                <<",\"unknown_text_states\":"<<result.unknownTextStates<<",\"repeated_objects\":"<<result.repeatedObjects
                <<",\"node_budget_reached\":"<<(result.nodeLimited?"true":"false")
                <<",\"depth_budget_reached\":"<<(result.depthLimited?"true":"false")
                <<",\"traversal_complete\":"<<(result.Complete()?"true":"false")<<",\"roles\":{";
            bool first=true;for(const auto& [role,count]:result.roles){if(!first)std::cout<<',';first=false;std::cout<<'"'<<role<<"\":"<<count;}
            std::cout<<"},\"window_revalidated\":true,\"content_read\":false,\"input_performed\":false}"<<std::endl;
            code=0;
        }catch(const std::exception&){
            // Never forward provider exceptions, strings or arbitrary HRESULTs.
            std::cout<<"{\"error\":\"msaa_metadata_probe_failed\",\"content_read\":false,\"input_performed\":false}"<<std::endl;
        }
    }
    CoUninitialize();CloseHandle(process);return code;
}
