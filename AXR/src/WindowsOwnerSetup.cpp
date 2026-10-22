// SPDX-License-Identifier: AGPL-3.0-only
// Fixed, one-shot LocalSystem -> interactive owner setup. The job only manages
// child lifetime; it is not an agent sandbox or authorization mechanism.
#include "axr/WindowsOwnerSetup.hpp"
#include "axr/WindowsInstallation.hpp"
#include "axr/Security.hpp"
#include <algorithm>
#include <cmath>
#include <fstream>
#if defined(_WIN32)
#define NOMINMAX
#include <windows.h>
#include <sddl.h>
#include <wtsapi32.h>
#include <userenv.h>
#include <shlobj.h>
#include "WindowsSetupTransport.hpp"
#endif
namespace Stellaria::AXR {
namespace {
bool Hex64(const Json& value){return value.is_string()&&value.get_ref<const std::string&>().size()==64&&
    value.get_ref<const std::string&>().find_first_not_of("0123456789abcdef")==std::string::npos;}
void ValidateChallenge(const Json& value){
    if(!value.is_object()||value.size()!=5||!value.contains("version")||!value.at("version").is_number_integer()||value.at("version")!=2||
       !value.contains("kind")||!value.at("kind").is_string()||value.at("kind")!="wechat-owner-enrollment"||!value.contains("nonce")||!Hex64(value.at("nonce"))||
       !value.contains("configuration_digest")||!Hex64(value.at("configuration_digest"))||!value.contains("expires")||
       !value.at("expires").is_number()||!std::isfinite(value.at("expires").get<double>())||
       value.at("expires").get<double>()<=Now()||value.at("expires").get<double>()>Now()+180)
        throw std::runtime_error("windows_owner_setup_challenge_invalid");
}
#if defined(_WIN32)
struct Handle {
    HANDLE value=nullptr;
    Handle()=default;explicit Handle(HANDLE handle):value(handle){}
    Handle(const Handle&)=delete;Handle& operator=(const Handle&)=delete;
    Handle(Handle&& other)noexcept:value(other.value){other.value=nullptr;}
    Handle& operator=(Handle&& other)noexcept{if(this!=&other){Reset();value=other.value;other.value=nullptr;}return *this;}
    ~Handle(){Reset();}
    void Reset(){if(value&&value!=INVALID_HANDLE_VALUE)CloseHandle(value);value=nullptr;}
};
[[noreturn]] void Denied(){throw std::runtime_error("windows_owner_setup_denied");}
std::filesystem::path InstalledRoot(){PWSTR path=nullptr;
    if(FAILED(SHGetKnownFolderPath(FOLDERID_ProgramFiles,KF_FLAG_DEFAULT,nullptr,&path)))Denied();
    auto root=std::filesystem::path(path)/L"Stellaria AXR";CoTaskMemFree(path);return root;
}
Json Host(bool server){
    auto actual=ProcessIdentity(GetCurrentProcessId());auto image=Utf8Path(actual.at("image").get<std::string>());
    if(image.filename()!=(server?L"axr-authority.exe":L"axr-owner.exe"))
        throw std::runtime_error(server?"windows_owner_setup_authority_host_required":"windows_owner_setup_owner_host_required");
    DWORD session=0;
    if(server){if(actual.at("user")!="S-1-5-18")throw std::runtime_error("windows_owner_setup_system_required");}
    else if(actual.at("user")=="S-1-5-18"||!ProcessIdToSessionId(GetCurrentProcessId(),&session)||!session)
        throw std::runtime_error("windows_owner_setup_interactive_owner_required");
    if(image.parent_path()!=InstalledRoot())Denied();
    VerifyWindowsInstallation(image.parent_path());return actual;
}
using namespace WindowsSetupTransport;
std::string Read(const std::filesystem::path& path,size_t maximum){
    std::ifstream stream(path,std::ios::binary);if(!stream)Denied();std::string raw(maximum+1,'\0');
    stream.read(raw.data(),std::streamsize(raw.size()));auto count=stream.gcount();
    if(count>std::streamsize(maximum)||stream.bad())Denied();raw.resize(size_t(count));return raw;
}
struct Sid {
    PSID value=nullptr;
    explicit Sid(const std::string& text){auto wide=Utf8Path(text).wstring();
        if(!ConvertStringSidToSidW(wide.c_str(),&value)||!IsValidSid(value))Denied();}
    ~Sid(){if(value)LocalFree(value);}
};
struct Privilege {
    Handle token;TOKEN_PRIVILEGES previous{};bool changed=false;
    explicit Privilege(const wchar_t* name){
        if(!OpenProcessToken(GetCurrentProcess(),TOKEN_ADJUST_PRIVILEGES|TOKEN_QUERY,&token.value))Denied();
        TOKEN_PRIVILEGES next{};next.PrivilegeCount=1;next.Privileges[0].Attributes=SE_PRIVILEGE_ENABLED;
        if(!LookupPrivilegeValueW(nullptr,name,&next.Privileges[0].Luid))Denied();DWORD size=sizeof(previous);SetLastError(ERROR_SUCCESS);
        if(!AdjustTokenPrivileges(token.value,FALSE,&next,sizeof(previous),&previous,&size)||GetLastError()!=ERROR_SUCCESS)Denied();changed=true;
    }
    ~Privilege(){if(changed)AdjustTokenPrivileges(token.value,FALSE,&previous,0,nullptr,nullptr);}
};
Handle UserToken(const Sid& expected){
    PWTS_SESSION_INFOW sessions=nullptr;DWORD count=0;
    if(!WTSEnumerateSessionsW(WTS_CURRENT_SERVER_HANDLE,0,1,&sessions,&count))Denied();
    struct Free {PWTS_SESSION_INFOW value;~Free(){WTSFreeMemory(value);}} free{sessions};Handle selected;
    for(DWORD i=0;i<count;++i){if(sessions[i].State!=WTSActive||!sessions[i].SessionId)continue;
        Handle token;if(!WTSQueryUserToken(sessions[i].SessionId,&token.value))continue;
        DWORD size=0;GetTokenInformation(token.value,TokenUser,nullptr,0,&size);if(!size||size>4096)Denied();
        std::vector<unsigned char> data(size);if(!GetTokenInformation(token.value,TokenUser,data.data(),size,&size))Denied();
        if(EqualSid(reinterpret_cast<TOKEN_USER*>(data.data())->User.Sid,expected.value)){
            if(selected.value)throw std::runtime_error("windows_owner_setup_multiple_active_sessions");selected=std::move(token);}
    }
    if(!selected.value)throw std::runtime_error("windows_owner_setup_owner_not_active");return selected;
}
std::vector<wchar_t> Environment(HANDLE token,const std::filesystem::path& root){
    std::wstring windows(32768,L'\0'),system(32768,L'\0'),profile(32768,L'\0');DWORD size=DWORD(profile.size());
    auto wn=GetWindowsDirectoryW(windows.data(),DWORD(windows.size())),sn=GetSystemDirectoryW(system.data(),DWORD(system.size()));
    if(!wn||wn>=windows.size()||!sn||sn>=system.size()||!GetUserProfileDirectoryW(token,profile.data(),&size)||!size||size>profile.size())Denied();
    windows.resize(wn);system.resize(sn);profile.resize(size-1);
    std::vector<std::wstring> entries={L"APPDATA="+profile+L"\\AppData\\Roaming",L"LOCALAPPDATA="+profile+L"\\AppData\\Local",
        L"PATH="+system+L";"+root.wstring(),L"SystemRoot="+windows,L"TEMP="+profile+L"\\AppData\\Local\\Temp",
        L"TMP="+profile+L"\\AppData\\Local\\Temp",L"USERPROFILE="+profile,L"WINDIR="+windows};
    std::sort(entries.begin(),entries.end());std::vector<wchar_t> block;
    for(const auto& entry:entries){block.insert(block.end(),entry.begin(),entry.end());block.push_back(0);}block.push_back(0);return block;
}
struct Child {
    Handle process,thread,job;DWORD pid=0;Json identity;
    ~Child(){if(process.value){if(WaitForSingleObject(process.value,0)!=WAIT_OBJECT_0)TerminateProcess(process.value,1);
        job.Reset();WaitForSingleObject(process.value,5000);}}
};
void Launch(Child& child,const Sid& owner,const std::filesystem::path& root,const Deadline& deadline){
    Privilege tcb(L"SeTcbPrivilege"),assign(L"SeAssignPrimaryTokenPrivilege"),quota(L"SeIncreaseQuotaPrivilege");
    auto token=UserToken(owner);auto environment=Environment(token.value,root);
    child.job=Handle(CreateJobObjectW(nullptr,nullptr));if(!child.job.value)Denied();
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};limits.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if(!SetInformationJobObject(child.job.value,JobObjectExtendedLimitInformation,&limits,sizeof(limits)))Denied();
    auto executable=root/L"axr-owner.exe";auto command=L"\""+executable.wstring()+L"\" --owner-enroll";
    std::wstring desktop=L"winsta0\\default";STARTUPINFOW startup{};startup.cb=sizeof(startup);startup.lpDesktop=desktop.data();PROCESS_INFORMATION info{};
    deadline.Remaining();
    if(!CreateProcessAsUserW(token.value,executable.c_str(),command.data(),nullptr,nullptr,FALSE,
            CREATE_SUSPENDED|CREATE_NO_WINDOW|CREATE_UNICODE_ENVIRONMENT,environment.data(),root.c_str(),&startup,&info))Denied();
    child.process=Handle(info.hProcess);child.thread=Handle(info.hThread);child.pid=info.dwProcessId;
    if(!AssignProcessToJobObject(child.job.value,child.process.value))Denied();
    child.identity=ProcessIdentity(child.pid);if(Utf8Path(child.identity.at("image").get<std::string>())!=executable)Denied();
    DWORD size=0;GetTokenInformation(token.value,TokenUser,nullptr,0,&size);std::vector<unsigned char> user(size);
    if(!GetTokenInformation(token.value,TokenUser,user.data(),size,&size)||!EqualSid(reinterpret_cast<TOKEN_USER*>(user.data())->User.Sid,owner.value))Denied();
    if(ResumeThread(child.thread.value)==DWORD(-1))Denied();child.thread.Reset();
}
Handle Pipe(const std::wstring& endpoint,const std::string& ownerSid){
    auto text=L"D:P(A;;GRGW;;;SY)(A;;GRGW;;;"+Utf8Path(ownerSid).wstring()+L")";PSECURITY_DESCRIPTOR descriptor=nullptr;
    if(!ConvertStringSecurityDescriptorToSecurityDescriptorW(text.c_str(),SDDL_REVISION_1,&descriptor,nullptr))Denied();
    struct Free {PSECURITY_DESCRIPTOR value;~Free(){LocalFree(value);}} free{descriptor};
    SECURITY_ATTRIBUTES attributes{sizeof(attributes),descriptor,FALSE};
    Handle pipe(CreateNamedPipeW(endpoint.c_str(),PIPE_ACCESS_DUPLEX|FILE_FLAG_OVERLAPPED|FILE_FLAG_FIRST_PIPE_INSTANCE,
        PIPE_TYPE_MESSAGE|PIPE_READMODE_MESSAGE|PIPE_WAIT|PIPE_REJECT_REMOTE_CLIENTS,1,300001,300001,5000,&attributes));
    if(pipe.value==INVALID_HANDLE_VALUE)Denied();return pipe;
}
struct Descriptor {
    Handle lock;std::filesystem::path path;std::string raw;
    explicit Descriptor(const std::filesystem::path& root):path(root/L"runtime"/L"owner-bootstrap.json"){
        lock=Handle(CreateFileW((root/L"runtime"/L"owner-bootstrap.lock").c_str(),GENERIC_READ|GENERIC_WRITE,
            FILE_SHARE_READ,nullptr,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
        if(lock.value==INVALID_HANDLE_VALUE)throw std::runtime_error("windows_owner_setup_already_running");}
    ~Descriptor(){if(!raw.empty())try{if(Read(path,8192)==raw){std::error_code error;std::filesystem::remove(path,error);}}catch(...){} }
    void Write(const Json& value){raw=value.dump();if(!DurableWrite(path,raw))throw std::runtime_error("windows_owner_setup_descriptor_write_failed");}
};
#endif
}
Json ExchangeWindowsOwnerSetup(std::string ownerSid,const Json& challenge){
    ValidateChallenge(challenge);
    if(ownerSid.empty()||ownerSid.size()>184||ownerSid.find_first_not_of("S-0123456789")!=std::string::npos||ownerSid.rfind("S-1-5-21-",0)!=0)
        throw std::runtime_error("windows_owner_setup_owner_sid_invalid");
#if defined(_WIN32)
    auto server=Host(true);auto root=InstalledRoot();Sid sid(ownerSid);Deadline deadline(challenge.at("expires"));Descriptor descriptor(root);
    auto nonce=Digest(RandomId()+RandomId()),endpoint=std::string("\\\\.\\pipe\\Stellaria.AXR.Setup.")+RandomId();
    auto pipe=Pipe(Utf8Path(endpoint).wstring(),ownerSid);
    descriptor.Write({{"version",2},{"kind","windows-owner-setup"},{"endpoint",endpoint},{"nonce",nonce},
        {"expires",challenge.at("expires")},{"server",server},{"owner_user",ownerSid},{"configuration_digest",challenge.at("configuration_digest")}});
    Child child;Launch(child,sid,root,deadline);if(child.identity.at("user")!=ownerSid)Denied();
    Connect(pipe.value,deadline);Stable(pipe.value,false,child.identity);
    if(Receive(pipe.value,32768,deadline,false,child.identity)!=Json{{"version",2},{"kind","owner-setup.open"},{"nonce",nonce}})Denied();
    Send(pipe.value,{{"version",2},{"kind","owner-setup.challenge"},{"nonce",nonce},{"challenge",challenge}},deadline,false,child.identity);
    auto packet=Receive(pipe.value,300000,deadline,false,child.identity);
    if(!packet.is_object()||packet.size()!=4||packet.at("version")!=2||packet.at("kind")!="owner-setup.response"||packet.at("nonce")!=nonce)Denied();
    Send(pipe.value,{{"version",2},{"kind","owner-setup.received"},{"nonce",nonce},{"authority_restored",false}},deadline,false,child.identity);
    return {{"response",packet.at("response")},{"identity",child.identity}};
#else
    throw std::runtime_error("windows_owner_setup_required");
#endif
}
struct WindowsOwnerSetupClient::Impl {
    Json challenge;
#if defined(_WIN32)
    Handle pipe;Json server;std::string nonce;std::unique_ptr<Deadline> deadline;bool responded=false;
#endif
};
WindowsOwnerSetupClient::WindowsOwnerSetupClient():impl_(std::make_unique<Impl>()){
#if defined(_WIN32)
    auto owner=Host(false);auto value=ParseBounded(Read(InstalledRoot()/L"runtime"/L"owner-bootstrap.json",8192));
    if(!value.is_object()||value.size()!=8||value.at("version")!=2||value.at("kind")!="windows-owner-setup"||
       value.at("owner_user")!=owner.at("user")||!Hex64(value.at("nonce"))||!Hex64(value.at("configuration_digest")))Denied();
    auto endpoint=value.at("endpoint").get<std::string>();constexpr std::string_view prefix="\\\\.\\pipe\\Stellaria.AXR.Setup.";
    if(endpoint.rfind(prefix,0)!=0||endpoint.size()!=prefix.size()+32||endpoint.substr(prefix.size()).find_first_not_of("0123456789abcdef")!=std::string::npos)Denied();
    auto expires=value.at("expires").get<double>();if(!std::isfinite(expires)||expires<=Now()||expires>Now()+180)Denied();
    impl_->deadline=std::make_unique<Deadline>(expires);impl_->server=value.at("server");impl_->nonce=value.at("nonce");
    if(impl_->server.at("user")!="S-1-5-18"||Utf8Path(impl_->server.at("image").get<std::string>())!=InstalledRoot()/L"axr-authority.exe")Denied();
    impl_->pipe=Handle(CreateFileW(Utf8Path(endpoint).c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,OPEN_EXISTING,
        FILE_FLAG_OVERLAPPED|SECURITY_SQOS_PRESENT|SECURITY_ANONYMOUS,nullptr));
    if(impl_->pipe.value==INVALID_HANDLE_VALUE)Denied();DWORD mode=PIPE_READMODE_MESSAGE;
    if(!SetNamedPipeHandleState(impl_->pipe.value,&mode,nullptr,nullptr))Denied();Stable(impl_->pipe.value,true,impl_->server);
    Send(impl_->pipe.value,{{"version",2},{"kind","owner-setup.open"},{"nonce",impl_->nonce}},*impl_->deadline,true,impl_->server);
    auto packet=Receive(impl_->pipe.value,32768,*impl_->deadline,true,impl_->server);
    if(packet.size()!=4||packet.at("version")!=2||packet.at("kind")!="owner-setup.challenge"||packet.at("nonce")!=impl_->nonce)Denied();
    impl_->challenge=packet.at("challenge");ValidateChallenge(impl_->challenge);
    if(impl_->challenge.at("expires")!=value.at("expires")||impl_->challenge.at("configuration_digest")!=value.at("configuration_digest"))Denied();
#else
    throw std::runtime_error("windows_owner_setup_required");
#endif
}
WindowsOwnerSetupClient::~WindowsOwnerSetupClient()=default;
void WindowsOwnerSetupClient::Close(){
#if defined(_WIN32)
    impl_->responded=true;impl_->pipe.Reset();
#endif
}
Json WindowsOwnerSetupClient::Challenge()const{return impl_->challenge;}
void WindowsOwnerSetupClient::Respond(const Json& response){
#if defined(_WIN32)
    if(impl_->responded)Denied();impl_->responded=true;
    Send(impl_->pipe.value,{{"version",2},{"kind","owner-setup.response"},{"nonce",impl_->nonce},{"response",response}},*impl_->deadline,true,impl_->server);
    if(Receive(impl_->pipe.value,32768,*impl_->deadline,true,impl_->server)!=Json{{"version",2},{"kind","owner-setup.received"},{"nonce",impl_->nonce},{"authority_restored",false}})Denied();
#else
    (void)response;throw std::runtime_error("windows_owner_setup_required");
#endif
}
}
