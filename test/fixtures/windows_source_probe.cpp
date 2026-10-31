// SPDX-License-Identifier: MIT
// Purely synthetic trusted transport, never installed or connected to a model.
#define NOMINMAX
#include <windows.h>
#include <fstream>
#include <iostream>
#include <thread>
#include "axr/Core.hpp"
using namespace Stellaria::AXR;
static std::filesystem::path Extended(const std::filesystem::path& path){auto text=path.wstring();return text.starts_with(L"\\\\?\\")?path:std::filesystem::path(L"\\\\?\\"+text);}
static bool Readable(const std::filesystem::path& path){std::ifstream file(Extended(path),std::ios::binary);return bool(file);}
int wmain(int argc,wchar_t** argv){
    try{
        std::filesystem::path output,work;
        for(int i=1;i+1<argc;++i){if(std::wstring_view(argv[i])==L"--output-last-message")output=argv[i+1];if(std::wstring_view(argv[i])==L"-C")work=argv[i+1];}
        std::string input((std::istreambuf_iterator<char>(std::cin)),{});auto start=input.find('\n');auto request=Json::parse(input.substr(start+1));
        auto probe=Json::parse(request.at("records").at(0).at("text").get<std::string>());auto mode=probe.value("mode",std::string("normal"));
        if(mode=="wait")std::this_thread::sleep_for(std::chrono::seconds(30));
        if(mode=="tool"){std::cout<<Json{{"type","item.started"},{"item",{{"type","command_execution"}}}}.dump()<<std::endl;std::this_thread::sleep_for(std::chrono::seconds(30));}
        if(mode=="partial_budget"){std::cout<<std::string(1024*1024+1,'x')<<std::flush;std::this_thread::sleep_for(std::chrono::seconds(30));}
        if(mode=="budget"){std::cout<<std::string(5*1024*1024,'x')<<std::flush;std::this_thread::sleep_for(std::chrono::seconds(30));}
        if(mode=="fail")return 5;
        Json result;
        result["outside_read"]=Readable(Utf8Path(probe.at("outside").get<std::string>()));
        result["original_auth_read"]=Readable(Utf8Path(probe.at("original_auth").get<std::string>()));
        wchar_t home[32768];auto length=GetEnvironmentVariableW(L"CODEX_HOME",home,32768);if(!length||length>=32768)return 6;
        result["transport_auth_read"]=Readable(std::filesystem::path(home)/L"auth.json");
        result["schema_read"]=Readable(work/L"schema.json");
        result["inherited_secret"]=GetEnvironmentVariableW(L"AXR_SYNTHETIC_PARENT_SECRET",nullptr,0)>0;
        {std::ofstream own(Extended(work/L"own.txt"));own<<"public fixture";result["own_write"]=bool(own);}
        wchar_t system[MAX_PATH];GetSystemDirectoryW(system,MAX_PATH);auto program=std::filesystem::path(system)/L"cmd.exe";
        auto command=L"\""+program.wstring()+L"\" /c exit 0";STARTUPINFOW startup{};startup.cb=sizeof(startup);PROCESS_INFORMATION child{};
        bool created=CreateProcessW(program.c_str(),command.data(),nullptr,nullptr,FALSE,CREATE_NO_WINDOW,nullptr,nullptr,&startup,&child);
        result["other_program"]=created;if(created){WaitForSingleObject(child.hProcess,3000);CloseHandle(child.hThread);CloseHandle(child.hProcess);}
        Json value={{"kind","ReplyDraft"},{"content",result.dump()},{"sources",request.at("source_keys")}};
        if(mode=="wrong_source")value["sources"]=Json::array({"another-source"});
        {std::ofstream file(Extended(output),std::ios::binary);file<<value.dump();if(!file)return 7;}
        std::cout<<Json{{"type","turn.completed"}}.dump()<<std::endl;return 0;
    }catch(...){return 8;}
}
