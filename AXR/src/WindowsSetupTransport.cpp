// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Stellaria-Commercial-1.0
#include "WindowsSetupTransport.hpp"
#if defined(_WIN32)
#include "axr/Security.hpp"
#include <algorithm>
namespace Stellaria::AXR::WindowsSetupTransport {
namespace {
[[noreturn]] void Denied(const char* code="windows_owner_setup_denied"){throw std::runtime_error(code);}
struct Event {
    HANDLE value=CreateEventW(nullptr,TRUE,FALSE,nullptr);
    Event(){if(!value)Denied();}~Event(){CloseHandle(value);}
};
void Pending(HANDLE pipe,OVERLAPPED& pending,const Deadline& deadline,DWORD& size){
    try{
        while(true){auto remaining=deadline.Remaining();auto state=WaitForSingleObject(pending.hEvent,std::min<DWORD>(50,remaining));
            if(state==WAIT_TIMEOUT)continue;
            if(state!=WAIT_OBJECT_0)Denied("windows_owner_setup_wait_failed");
            if(!GetOverlappedResult(pipe,&pending,&size,FALSE))throw std::runtime_error("windows_owner_setup_io_os_"+std::to_string(GetLastError()));
            deadline.Remaining();return;}
    }catch(...){CancelIoEx(pipe,&pending);GetOverlappedResult(pipe,&pending,&size,TRUE);throw;}
}
}
Deadline::Deadline(double expires,std::function<void()> active):wall(expires),tick(GetTickCount64()+ULONGLONG(std::max(0.0,std::min(180.0,expires-Now()))*1000)),check(std::move(active)){}
DWORD Deadline::Remaining()const{if(check)check();auto now=GetTickCount64();double left=wall-Now();
    if(left<=0||now>=tick)throw std::runtime_error("windows_owner_setup_expired");
    return DWORD(std::max(1.0,std::min(left*1000,double(tick-now))));}
void Connect(HANDLE pipe,const Deadline& deadline){
    deadline.Remaining();Event event;OVERLAPPED pending{};pending.hEvent=event.value;DWORD size=0;
    if(!ConnectNamedPipe(pipe,&pending)){
        auto error=GetLastError();if(error==ERROR_IO_PENDING)Pending(pipe,pending,deadline,size);else if(error!=ERROR_PIPE_CONNECTED)throw std::runtime_error("windows_owner_setup_connect_os_"+std::to_string(error));}
}
DWORD Transfer(HANDLE pipe,void* buffer,DWORD size,bool write,const Deadline& deadline){
    deadline.Remaining();Event event;OVERLAPPED pending{};pending.hEvent=event.value;DWORD transferred=0;
    if(!(write?WriteFile(pipe,buffer,size,&transferred,&pending):ReadFile(pipe,buffer,size,&transferred,&pending))){
        auto error=GetLastError();if(error!=ERROR_IO_PENDING)throw std::runtime_error(std::string(write?"windows_owner_setup_write_os_":"windows_owner_setup_read_os_")+std::to_string(error));Pending(pipe,pending,deadline,transferred);}
    return transferred;
}
void Stable(HANDLE pipe,bool serverPeer,const Json& expected){if(PeerIdentity(reinterpret_cast<uintptr_t>(pipe),serverPeer)!=expected)Denied("windows_owner_setup_peer_identity_changed");}
void Send(HANDLE pipe,const Json& value,const Deadline& deadline,bool serverPeer,const Json& expected,size_t maximum){
    Stable(pipe,serverPeer,expected);auto raw=value.dump();if(maximum>MaximumFrameBytes||raw.size()>maximum)Denied();
    if(Transfer(pipe,raw.data(),DWORD(raw.size()),true,deadline)!=raw.size())Denied();
}
Json Receive(HANDLE pipe,size_t maximum,const Deadline& deadline,bool serverPeer,const Json& expected){
    if(maximum>MaximumFrameBytes)Denied();Stable(pipe,serverPeer,expected);std::string raw(maximum+1,'\0');
    auto size=Transfer(pipe,raw.data(),DWORD(raw.size()),false,deadline);if(size>maximum)Denied();raw.resize(size);
    auto value=ParseBounded(raw);if(value.dump()!=raw)Denied("windows_owner_setup_noncanonical_frame");Stable(pipe,serverPeer,expected);return value;
}
}
#endif
