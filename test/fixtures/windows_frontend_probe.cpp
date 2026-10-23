// SPDX-License-Identifier: MIT
// Synthetic stdio/pipe witness; never shipped in a runtime package.
#define NOMINMAX
#include <winsock2.h>
#include <windows.h>
#include <fstream>
#include <iostream>
#include <sddl.h>
#include "axr/WindowsFrontend.hpp"
#include "axr/Security.hpp"
using namespace Stellaria::AXR;
int main(int argc,char** argv){
    try{
        if(argc==3&&std::string_view(argv[1])=="--pipe-server"){
            auto actual=ProcessIdentity(GetCurrentProcessId());ExposeWindowsAuthorityIdentity(actual.at("user"));
            auto text=L"D:P(A;;GRGW;;;SY)(A;;GRGW;;;"+Utf8Path(actual.at("user").get<std::string>()).wstring()+L")(A;;GRGW;;;S-1-15-2-2)S:(ML;;NW;;;LW)";
            PSECURITY_DESCRIPTOR descriptor=nullptr;if(!ConvertStringSecurityDescriptorToSecurityDescriptorW(text.c_str(),SDDL_REVISION_1,&descriptor,nullptr))return 4;
            SECURITY_ATTRIBUTES attributes{sizeof(attributes),descriptor,FALSE};
            auto endpoint=Utf8Path(argv[2]);auto pipe=CreateNamedPipeW(endpoint.c_str(),PIPE_ACCESS_DUPLEX|FILE_FLAG_FIRST_PIPE_INSTANCE,
                PIPE_TYPE_MESSAGE|PIPE_READMODE_MESSAGE|PIPE_WAIT|PIPE_REJECT_REMOTE_CLIENTS,1,128,128,5000,&attributes);LocalFree(descriptor);
            if(pipe==INVALID_HANDLE_VALUE)return 5;std::cout<<actual.dump()<<std::endl;
            if(!ConnectNamedPipe(pipe,nullptr)&&GetLastError()!=ERROR_PIPE_CONNECTED)return 6;
            char input[16]{};DWORD received=0;bool ok=ReadFile(pipe,input,16,&received,nullptr);CloseHandle(pipe);
            std::cout<<Json{{"received",ok?std::string(input,received):std::string{}}}.dump()<<std::endl;return ok?0:7;
        }
        if(argc==1)return RunWindowsFrontend();
        if(argc!=2||std::string_view(argv[1])!="--sandbox-mcp")return 3;
        auto sandbox=WindowsFrontendIdentity(GetCurrentProcessId());
        std::cout<<Json{{"ready",true},{"sandbox",sandbox}}.dump()<<std::endl;
        std::string line;std::getline(std::cin,line);auto request=ParseBounded(line);Json value;
        std::ifstream outside(Utf8Path(request.at("outside").get<std::string>()));value["outside_read"]=bool(outside);
        value["inherited_secret"]=GetEnvironmentVariableW(L"AXR_SYNTHETIC_PARENT_SECRET",nullptr,0)>0;
        WSADATA initialized{};bool connected=false;if(!WSAStartup(MAKEWORD(2,2),&initialized)){
            auto socket=::socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);sockaddr_in address{};address.sin_family=AF_INET;address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);address.sin_port=htons(request.at("port").get<unsigned short>());
            connected=::connect(socket,reinterpret_cast<sockaddr*>(&address),sizeof(address))==0;closesocket(socket);WSACleanup();}
        value["loopback_connected"]=connected;
        if(request.contains("pipe")){
            auto endpoint=Utf8Path(request.at("pipe").get<std::string>());
            auto pipe=CreateFileW(endpoint.c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,OPEN_EXISTING,SECURITY_SQOS_PRESENT|SECURITY_ANONYMOUS,nullptr);
            value["pipe_connected"]=pipe!=INVALID_HANDLE_VALUE;
            if(pipe!=INVALID_HANDLE_VALUE){value["server_identity"]=PeerIdentity(reinterpret_cast<uintptr_t>(pipe),true);
                DWORD written=0;WriteFile(pipe,"probe",5,&written,nullptr);CloseHandle(pipe);}
        }
        std::cout<<value.dump()<<std::endl;return 0;
    }catch(const std::exception& error){auto message=std::string(error.what());
        if(message.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789_")!=std::string::npos)message="synthetic_frontend_failure";
        std::cout<<Json{{"error",message}}.dump()<<std::endl;return 2;}
}
