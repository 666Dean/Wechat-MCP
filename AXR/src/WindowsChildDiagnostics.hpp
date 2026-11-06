// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Stellaria-Commercial-1.0
#pragma once
#if defined(_WIN32)
#include "WindowsSetupTransport.hpp"
#include "WindowsServiceResult.hpp"
#include <sstream>

namespace Stellaria::AXR::WindowsChildDiagnostics {
// Advisory only after the independently failed exchange and failed child exit.
// Neither stderr nor this parser authenticates a peer or promotes success.
inline std::string FailureCode(std::string_view raw){
    if(raw.empty()||raw.size()>4096)return {};
    try{
        std::istringstream stream{std::string(raw)};std::string line,first;unsigned count=0;
        while(std::getline(stream,line)){
            if(!line.empty()&&line.back()=='\r')line.pop_back();
            if(++count>2||line.empty())return {};auto value=ParseBounded(line);
            if(!value.is_object()||value.size()!=2||value.dump()!=line)return {};
            std::string code;
            if(value.contains("error_code")&&value.contains("exception_type")&&value.at("error_code").is_string()&&value.at("exception_type").is_string())
                code=value.at("error_code").get<std::string>();
            else if(value.contains("error")&&value.contains("authority_started")&&value.at("error").is_string()&&value.at("authority_started")==false)
                code=value.at("error").get<std::string>();
            else return {};
            if(WindowsServiceResult::ErrorCode(code)!=code)return {};
            if(first.empty())first=code;
        }
        return first;
    }catch(...){return {};}
}
class Capture {
    struct Handle {HANDLE value=nullptr;~Handle(){Reset();}void Reset(){if(value&&value!=INVALID_HANDLE_VALUE)CloseHandle(value);value=nullptr;}};
    Handle read_,write_,neutral_;std::vector<unsigned char> attributes_;
    LPPROC_THREAD_ATTRIBUTE_LIST list_=nullptr;HANDLE handles_[2]{};
public:
    Capture(){
        SECURITY_ATTRIBUTES security{sizeof(security),nullptr,TRUE};
        if(!CreatePipe(&read_.value,&write_.value,&security,4096)||!SetHandleInformation(read_.value,HANDLE_FLAG_INHERIT,0))
            throw std::runtime_error("windows_owner_setup_diagnostic_pipe_failed");
        neutral_.value=CreateFileW(L"NUL",GENERIC_READ|GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,&security,OPEN_EXISTING,0,nullptr);
        if(neutral_.value==INVALID_HANDLE_VALUE)throw std::runtime_error("windows_owner_setup_diagnostic_stdio_failed");
    }
    Capture(const Capture&)=delete;Capture& operator=(const Capture&)=delete;
    ~Capture(){if(list_)DeleteProcThreadAttributeList(list_);}
    void Configure(STARTUPINFOEXW& startup){
        SIZE_T size=0;InitializeProcThreadAttributeList(nullptr,1,0,&size);attributes_.resize(size);
        auto candidate=reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attributes_.data());
        if(!InitializeProcThreadAttributeList(candidate,1,0,&size))throw std::runtime_error("windows_owner_setup_diagnostic_handles_failed");
        list_=candidate;handles_[0]=write_.value;handles_[1]=neutral_.value;
        if(!UpdateProcThreadAttribute(list_,0,PROC_THREAD_ATTRIBUTE_HANDLE_LIST,handles_,sizeof(handles_),nullptr,nullptr))
            throw std::runtime_error("windows_owner_setup_diagnostic_handles_failed");
        startup.StartupInfo.cb=sizeof(startup);startup.StartupInfo.dwFlags=STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput=neutral_.value;startup.StartupInfo.hStdOutput=neutral_.value;startup.StartupInfo.hStdError=write_.value;
        startup.lpAttributeList=list_;
    }
    void ParentStarted(){write_.Reset();neutral_.Reset();}
    std::string Failure(HANDLE process){
        DWORD exit=0,available=0,read=0;
        if(!process||WaitForSingleObject(process,250)!=WAIT_OBJECT_0||!GetExitCodeProcess(process,&exit)||!exit||
            !PeekNamedPipe(read_.value,nullptr,0,nullptr,&available,nullptr)||!available||available>4096)return {};
        std::string raw(available,'\0');
        if(!ReadFile(read_.value,raw.data(),available,&read,nullptr)||read!=available)return {};
        return FailureCode(raw);
    }
};
}
#endif
