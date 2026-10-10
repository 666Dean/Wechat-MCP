// SPDX-License-Identifier: AGPL-3.0-only
// Sandboxing witness used only with synthetic fixture data / loopback TCP.
#include "axr/Core.hpp"
#include <iostream>
#include <fstream>
#ifdef _WIN32
#include <winsock2.h>
#else
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#endif
int main(){using namespace Stellaria::AXR;Json output;try{
    std::string line;std::getline(std::cin,line);if(line.size()>4096)return 2;auto request=Json::parse(line);
    if(request.at("op")=="read"){
        std::ifstream file(request.at("path").get<std::string>(),std::ios::binary);
        output={{"allowed",bool(file)}};
    }else if(request.at("op")=="network"){
#ifdef _WIN32
        WSADATA data;WSAStartup(MAKEWORD(2,2),&data);
#endif
        auto handle=socket(AF_INET,SOCK_STREAM,0);sockaddr_in address{};address.sin_family=AF_INET;
        address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);address.sin_port=htons(request.at("port").get<unsigned short>());
        bool allowed=connect(handle,reinterpret_cast<sockaddr*>(&address),sizeof(address))==0;
#ifdef _WIN32
        if(handle!=INVALID_SOCKET)closesocket(handle);WSACleanup();
#else
        if(handle>=0)close(handle);
#endif
        output={{"allowed",allowed}};
    }else return 2;
}catch(...){return 2;}std::cout<<output.dump()<<std::endl;}
