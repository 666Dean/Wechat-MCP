// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Stellaria-Commercial-1.0
#include "../src/WindowsSetupTransport.hpp"
#include "axr/Security.hpp"
#include "axr/WindowsFrontend.hpp"
#include <aclapi.h>
#include <sddl.h>
#include <cassert>
#include <iostream>
#include <thread>
using namespace Stellaria::AXR;
using namespace Stellaria::AXR::WindowsSetupTransport;
namespace {
struct Pair {
    std::wstring endpoint;HANDLE server=INVALID_HANDLE_VALUE,client=INVALID_HANDLE_VALUE;
    Pair(){endpoint=L"\\\\.\\pipe\\Stellaria.AXR.Test.Setup."+Utf8Path(RandomId()).wstring();
        server=CreateNamedPipeW(endpoint.c_str(),PIPE_ACCESS_DUPLEX|FILE_FLAG_OVERLAPPED|FILE_FLAG_FIRST_PIPE_INSTANCE,
            PIPE_TYPE_MESSAGE|PIPE_READMODE_MESSAGE|PIPE_WAIT|PIPE_REJECT_REMOTE_CLIENTS,1,4096,4096,1000,nullptr);
        assert(server!=INVALID_HANDLE_VALUE);}
    void Open(){client=CreateFileW(endpoint.c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED|SECURITY_SQOS_PRESENT|SECURITY_ANONYMOUS,nullptr);assert(client!=INVALID_HANDLE_VALUE);
        DWORD mode=PIPE_READMODE_MESSAGE;assert(SetNamedPipeHandleState(client,&mode,nullptr,nullptr));}
    ~Pair(){if(client!=INVALID_HANDLE_VALUE)CloseHandle(client);if(server!=INVALID_HANDLE_VALUE)CloseHandle(server);}
};
DWORD Allowed(HANDLE object,const wchar_t* text){
    PSID sid=nullptr;assert(ConvertStringSidToSidW(text,&sid));
    PACL acl=nullptr;PSECURITY_DESCRIPTOR descriptor=nullptr;
    assert(GetSecurityInfo(object,SE_KERNEL_OBJECT,DACL_SECURITY_INFORMATION,nullptr,nullptr,&acl,nullptr,&descriptor)==ERROR_SUCCESS);
    DWORD rights=0;
    for(DWORD i=0;acl&&i<acl->AceCount;++i){void* raw=nullptr;assert(GetAce(acl,i,&raw));
        auto header=static_cast<ACE_HEADER*>(raw);
        if(header->AceType==ACCESS_ALLOWED_ACE_TYPE){auto ace=static_cast<ACCESS_ALLOWED_ACE*>(raw);
            if(EqualSid(&ace->SidStart,sid))rights|=ace->Mask;}}
    LocalFree(sid);LocalFree(descriptor);return rights;
}
}
int main(){
    auto actual=ProcessIdentity(GetCurrentProcessId());
    {Pair pair;std::exception_ptr failure;
     std::thread worker([&]{try{Deadline budget(Now()+5);Connect(pair.server,budget);
        assert((Receive(pair.server,1024,budget,false,actual)==Json{{"request","fixture"}}));
        Send(pair.server,{{"response","fixture"}},budget,false,actual);}catch(...){failure=std::current_exception();}});
     pair.Open();Deadline budget(Now()+5);Send(pair.client,{{"request","fixture"}},budget,true,actual);
     assert((Receive(pair.client,1024,budget,true,actual)==Json{{"response","fixture"}}));worker.join();if(failure)std::rethrow_exception(failure);}
    {Pair pair;bool denied=false;auto start=GetTickCount64();
     try{Connect(pair.server,Deadline(Now()+0.1));}catch(const std::exception& error){denied=std::string(error.what())=="windows_owner_setup_expired";}
     assert(denied&&GetTickCount64()-start<2000);}
    {Pair pair;pair.Open();Deadline budget(Now()+2);Connect(pair.server,budget);bool denied=false;
     try{Receive(pair.server,1024,Deadline(Now()+0.1),false,actual);}catch(const std::exception& error){denied=std::string(error.what())=="windows_owner_setup_expired";}
     assert(denied);}
    {Pair pair;pair.Open();Deadline budget(Now()+2);Connect(pair.server,budget);auto wrong=actual;wrong["birth"]="different";bool denied=false;
     try{Receive(pair.server,1024,budget,false,wrong);}catch(...){denied=true;}assert(denied);}
    {Pair pair;pair.Open();Deadline budget(Now()+2);Connect(pair.server,budget);bool denied=false;auto start=GetTickCount64();
     auto check=[&]{if(GetTickCount64()-start>100)throw std::runtime_error("synthetic_scope_stopped");};
     try{Receive(pair.server,1024,Deadline(Now()+5,check),false,actual);}catch(const std::exception& error){denied=std::string(error.what())=="synthetic_scope_stopped";}
     assert(denied&&GetTickCount64()-start<1000);}
    {Pair pair;pair.Open();Deadline budget(Now()+2);Connect(pair.server,budget);std::string raw(256,'x');
     assert(Transfer(pair.client,raw.data(),DWORD(raw.size()),true,budget)==raw.size());bool denied=false;
     try{Receive(pair.server,100,budget,false,actual);}catch(...){denied=true;}assert(denied);}
    {Pair pair;pair.Open();Deadline budget(Now()+2);Connect(pair.server,budget);std::string raw="{\"b\":1,\"a\":2}";
     assert(Transfer(pair.client,raw.data(),DWORD(raw.size()),true,budget)==raw.size());bool denied=false;
     try{Receive(pair.server,100,budget,false,actual);}catch(const std::exception& e){denied=std::string(e.what())=="windows_owner_setup_noncanonical_frame";}
     assert(denied);}
    {const char* fake="S-1-5-21-111111111-222222222-333333333-4444";
     const wchar_t* wide=L"S-1-5-21-111111111-222222222-333333333-4444";
     HANDLE token=nullptr;assert(OpenProcessToken(GetCurrentProcess(),TOKEN_QUERY|READ_CONTROL,&token));
     auto before=Allowed(GetCurrentProcess(),L"S-1-15-2-2"),tokenBefore=Allowed(token,L"S-1-15-2-2");
#ifdef AXR_SECURITY_RELEASE
     bool denied=false;try{ExposeWindowsOwnerSetupIdentity(fake);}catch(const std::exception& e){denied=std::string(e.what())=="windows_frontend_authority_required";}
     assert(denied&&Allowed(GetCurrentProcess(),wide)==0&&Allowed(token,wide)==0);
#else
     assert(Allowed(GetCurrentProcess(),wide)==0&&Allowed(token,wide)==0);
     ExposeWindowsOwnerSetupIdentity(fake);
     assert(Allowed(GetCurrentProcess(),wide)==PROCESS_QUERY_LIMITED_INFORMATION);
     assert(Allowed(token,wide)==TOKEN_QUERY);
#endif
     assert(Allowed(GetCurrentProcess(),L"S-1-15-2-2")==before&&Allowed(token,L"S-1-15-2-2")==tokenBefore);
     CloseHandle(token);}
    std::cout<<"native setup roundtrip, identity, bounds, cancellation and owner-only metadata ACL passed; no service or owner launch\n";
}
