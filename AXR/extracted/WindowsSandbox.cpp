// SPDX-License-Identifier: AGPL-3.0-only
// AXR Windows sandbox initialization and SECURITY_CAPABILITIES.
// Qt removed. Grants touch only an owner-staged runtime, never live project/data paths.
#define NOMINMAX
#include <windows.h>
#include <userenv.h>
#include <aclapi.h>
#include <iostream>
#include "axr/Core.hpp"
using namespace Stellaria::AXR;
static std::wstring Quote(const std::wstring& value){
    if(!value.empty()&&value.find_first_of(L" \t\"")==std::wstring::npos)return value;
    std::wstring result=L"\"";size_t slashes=0;
    for(auto c:value){if(c==L'\\')++slashes;else if(c==L'\"'){result.append(slashes*2+1,L'\\');result.push_back(c);slashes=0;}else{result.append(slashes,L'\\');slashes=0;result.push_back(c);}}
    result.append(slashes*2,L'\\');result.push_back(L'\"');return result;
}
struct Container {
    std::wstring name;PSID sid=nullptr;std::filesystem::path root;
    std::vector<std::pair<std::filesystem::path,std::vector<unsigned char>>> previous;
    ~Container(){for(auto& [path,descriptor]:previous){SetFileSecurityW(path.wstring().c_str(),DACL_SECURITY_INFORMATION,reinterpret_cast<PSECURITY_DESCRIPTOR>(descriptor.data()));}
        if(sid)FreeSid(sid);if(!name.empty())DeleteAppContainerProfile(name.c_str());}
    void Grant(const std::filesystem::path& path){
        DWORD size=0;GetFileSecurityW(path.wstring().c_str(),DACL_SECURITY_INFORMATION,nullptr,0,&size);
        if(!size)throw std::runtime_error("sandbox_acl_read_failed");std::vector<unsigned char> original(size);
        if(!GetFileSecurityW(path.wstring().c_str(),DACL_SECURITY_INFORMATION,reinterpret_cast<PSECURITY_DESCRIPTOR>(original.data()),size,&size))throw std::runtime_error("sandbox_acl_read_failed");
        previous.emplace_back(path,original);
        PACL old=nullptr,next=nullptr;PSECURITY_DESCRIPTOR descriptor=nullptr;
        if(GetNamedSecurityInfoW(path.wstring().c_str(),SE_FILE_OBJECT,DACL_SECURITY_INFORMATION,nullptr,nullptr,&old,nullptr,&descriptor)!=ERROR_SUCCESS)throw std::runtime_error("sandbox_acl_read_failed");
        EXPLICIT_ACCESSW access{};access.grfAccessPermissions=GENERIC_READ|GENERIC_EXECUTE;access.grfAccessMode=GRANT_ACCESS;
        access.grfInheritance=NO_INHERITANCE;access.Trustee.TrusteeForm=TRUSTEE_IS_SID;access.Trustee.ptstrName=static_cast<LPWSTR>(sid);
        DWORD code=SetEntriesInAclW(1,&access,old,&next);
        bool ok=code==ERROR_SUCCESS&&SetNamedSecurityInfoW(const_cast<LPWSTR>(path.wstring().c_str()),SE_FILE_OBJECT,DACL_SECURITY_INFORMATION,nullptr,nullptr,next,nullptr)==ERROR_SUCCESS;
        if(next)LocalFree(next);if(descriptor)LocalFree(descriptor);if(!ok)throw std::runtime_error("sandbox_acl_grant_failed");
    }
    void Init(const std::filesystem::path& directory){
        root=std::filesystem::canonical(directory);name=L"Stellaria.AXR."+std::filesystem::path(RandomId()).wstring();
        if(FAILED(CreateAppContainerProfile(name.c_str(),name.c_str(),L"AXR isolated agent",nullptr,0,&sid)))throw std::runtime_error("sandbox_profile_failed");
        auto validate=[](const std::filesystem::path& p){auto attributes=GetFileAttributesW(p.wstring().c_str());if(attributes==INVALID_FILE_ATTRIBUTES||attributes&FILE_ATTRIBUTE_REPARSE_POINT)throw std::runtime_error("sandbox_reparse_path_denied");};
        // Only a dedicated staged root is accepted. No junctions, symlinks or credentials in this root.
        validate(root);Grant(root);std::size_t count=0;
        for(auto& entry:std::filesystem::recursive_directory_iterator(root)){
            if(++count>50000)throw std::runtime_error("sandbox_runtime_too_large");validate(entry.path());Grant(entry.path());
        }
    }
};
int wmain(int argc,wchar_t** argv){
    PROCESS_INFORMATION process{};HANDLE job=nullptr;bool started=false;
    try{
        if(argc<5||std::wstring(argv[1])!=L"--root"||std::wstring(argv[3])!=L"--")throw std::runtime_error("sandbox_arguments_invalid");
        Container container;container.Init(argv[2]);auto executable=std::filesystem::canonical(argv[4]);
        auto relative=executable.lexically_relative(container.root);
        if(relative.empty()||relative.is_absolute()||*relative.begin()==L"..")throw std::runtime_error("sandbox_executable_outside_staged_runtime");
        std::wstring command;for(int i=4;i<argc;++i){if(i>4)command+=L" ";command+=Quote(argv[i]);}
        STARTUPINFOEXW startup{};startup.StartupInfo.cb=sizeof(startup);SIZE_T bytes=0;
        InitializeProcThreadAttributeList(nullptr,2,0,&bytes);std::vector<unsigned char> attributes(bytes);
        startup.lpAttributeList=reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attributes.data());
        if(!InitializeProcThreadAttributeList(startup.lpAttributeList,2,0,&bytes))throw std::runtime_error("sandbox_attributes_failed");
        SECURITY_CAPABILITIES capabilities{};capabilities.AppContainerSid=container.sid;
        HANDLE handles[]={GetStdHandle(STD_INPUT_HANDLE),GetStdHandle(STD_OUTPUT_HANDLE),GetStdHandle(STD_ERROR_HANDLE)};
        startup.StartupInfo.dwFlags=STARTF_USESTDHANDLES;startup.StartupInfo.hStdInput=handles[0];startup.StartupInfo.hStdOutput=handles[1];startup.StartupInfo.hStdError=handles[2];
        for(auto h:handles)if(h&&h!=INVALID_HANDLE_VALUE)SetHandleInformation(h,HANDLE_FLAG_INHERIT,HANDLE_FLAG_INHERIT);
        bool configured=UpdateProcThreadAttribute(startup.lpAttributeList,0,PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,&capabilities,sizeof(capabilities),nullptr,nullptr)&&
            UpdateProcThreadAttribute(startup.lpAttributeList,0,PROC_THREAD_ATTRIBUTE_HANDLE_LIST,handles,sizeof(handles),nullptr,nullptr);
        command.push_back(L'\0');
        started=configured&&CreateProcessW(executable.wstring().c_str(),command.data(),nullptr,nullptr,TRUE,
            EXTENDED_STARTUPINFO_PRESENT|CREATE_SUSPENDED|CREATE_NO_WINDOW,nullptr,container.root.wstring().c_str(),&startup.StartupInfo,&process);
        DeleteProcThreadAttributeList(startup.lpAttributeList);
        if(!started)throw std::runtime_error("sandbox_process_start_failed");
        job=CreateJobObjectW(nullptr,nullptr);JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE|JOB_OBJECT_LIMIT_ACTIVE_PROCESS|JOB_OBJECT_LIMIT_PROCESS_MEMORY;
        limits.BasicLimitInformation.ActiveProcessLimit=4;limits.ProcessMemoryLimit=512ull*1024*1024;
        if(!job||!SetInformationJobObject(job,JobObjectExtendedLimitInformation,&limits,sizeof(limits))||!AssignProcessToJobObject(job,process.hProcess))throw std::runtime_error("sandbox_job_failed");
        ResumeThread(process.hThread);if(WaitForSingleObject(process.hProcess,60000)!=WAIT_OBJECT_0)throw std::runtime_error("sandbox_timeout");
        DWORD code=1;GetExitCodeProcess(process.hProcess,&code);CloseHandle(process.hThread);CloseHandle(process.hProcess);process={};CloseHandle(job);job=nullptr;
        if(code)std::cout<<Json{{"error","strict_sandbox_failed"},{"stage","child_exit"},{"exit_code",code}}.dump()<<std::endl;
        return int(code);
    }catch(const std::exception& error){DWORD code=GetLastError();if(process.hProcess){TerminateProcess(process.hProcess,125);WaitForSingleObject(process.hProcess,2000);CloseHandle(process.hThread);CloseHandle(process.hProcess);}if(job)CloseHandle(job);
        std::string stage=error.what();if(!stage.starts_with("sandbox_"))stage="native_operation_failed";
        std::cout<<Json{{"error","strict_sandbox_failed"},{"stage",stage},{"system_error",code}}.dump()<<std::endl;return 1;}
}
