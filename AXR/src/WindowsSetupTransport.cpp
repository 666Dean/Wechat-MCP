// SPDX-License-Identifier: AGPL-3.0-only
#include "WindowsSetupTransport.hpp"
#if defined(_WIN32)
#include "axr/Security.hpp"
#include <algorithm>
namespace Stellaria::AXR::WindowsSetupTransport {
namespace {
[[noreturn]] void Denied(){throw std::runtime_error("windows_owner_setup_denied");}
struct Event {
    HANDLE value=CreateEventW(nullptr,TRUE,FALSE,nullptr);
    Event(){if(!value)Denied();}~Event(){CloseHandle(value);}
};
void Pending(HANDLE pipe,OVERLAPPED& pending,const Deadline& deadline,DWORD& size){
    DWORD remaining=0;try{remaining=deadline.Remaining();}catch(...){CancelIoEx(pipe,&pending);GetOverlappedResult(pipe,&pending,&size,TRUE);throw;}
    if(WaitForSingleObject(pending.hEvent,remaining)!=WAIT_OBJECT_0){
        CancelIoEx(pipe,&pending);GetOverlappedResult(pipe,&pending,&size,TRUE);throw std::runtime_error("windows_owner_setup_expired");}
    if(!GetOverlappedResult(pipe,&pending,&size,FALSE))Denied();
}
}
Deadline::Deadline(double expires):wall(expires),tick(GetTickCount64()+ULONGLONG(std::max(0.0,std::min(180.0,expires-Now()))*1000)){}
DWORD Deadline::Remaining()const{auto now=GetTickCount64();double left=wall-Now();
    if(left<=0||now>=tick)throw std::runtime_error("windows_owner_setup_expired");
    return DWORD(std::max(1.0,std::min(left*1000,double(tick-now))));}
void Connect(HANDLE pipe,const Deadline& deadline){
    deadline.Remaining();Event event;OVERLAPPED pending{};pending.hEvent=event.value;DWORD size=0;
    if(!ConnectNamedPipe(pipe,&pending)){
        auto error=GetLastError();if(error==ERROR_IO_PENDING)Pending(pipe,pending,deadline,size);else if(error!=ERROR_PIPE_CONNECTED)Denied();}
}
DWORD Transfer(HANDLE pipe,void* buffer,DWORD size,bool write,const Deadline& deadline){
    deadline.Remaining();Event event;OVERLAPPED pending{};pending.hEvent=event.value;DWORD transferred=0;
    if(!(write?WriteFile(pipe,buffer,size,&transferred,&pending):ReadFile(pipe,buffer,size,&transferred,&pending))){
        if(GetLastError()!=ERROR_IO_PENDING)Denied();Pending(pipe,pending,deadline,transferred);}
    return transferred;
}
void Stable(HANDLE pipe,bool serverPeer,const Json& expected){if(PeerIdentity(reinterpret_cast<uintptr_t>(pipe),serverPeer)!=expected)Denied();}
void Send(HANDLE pipe,const Json& value,const Deadline& deadline,bool serverPeer,const Json& expected){
    Stable(pipe,serverPeer,expected);auto raw=value.dump();if(raw.size()>300000)Denied();
    if(Transfer(pipe,raw.data(),DWORD(raw.size()),true,deadline)!=raw.size())Denied();
}
Json Receive(HANDLE pipe,size_t maximum,const Deadline& deadline,bool serverPeer,const Json& expected){
    if(maximum>300000)Denied();Stable(pipe,serverPeer,expected);std::string raw(maximum+1,'\0');
    auto size=Transfer(pipe,raw.data(),DWORD(raw.size()),false,deadline);if(size>maximum)Denied();raw.resize(size);
    auto value=ParseBounded(raw);if(value.dump()!=raw)Denied();Stable(pipe,serverPeer,expected);return value;
}
}
#endif
