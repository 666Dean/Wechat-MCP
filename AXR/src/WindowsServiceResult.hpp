// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Stellaria-Commercial-1.0
#pragma once
#include "axr/Core.hpp"
#include <array>

namespace Stellaria::AXR::WindowsServiceResult {
inline std::string ErrorCode(std::string_view raw){
    constexpr std::array<std::string_view,17> prefixes={"authority_","windows_","wechat_","wcdb_","owner_",
        "rooted_","setup_","source_","native_","task_","protected_","credential_","hardware_","integrity_","identity_","ipc_","hello_"};
    if(raw.empty()||raw.size()>100||raw.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789_")!=std::string_view::npos)
        return "authority_operation_failed";
    for(auto prefix:prefixes)if(raw.starts_with(prefix)&&raw.size()>prefix.size())return std::string(raw);
    return "authority_operation_failed";
}
inline std::string OwnerPythonCode(std::string_view raw,std::string_view type){
    auto code=ErrorCode(raw);if(code!="authority_operation_failed")return code;
    constexpr std::array<std::pair<std::string_view,std::string_view>,12> types={{{"KeyError","key"},{"IndexError","index"},
        {"TypeError","type"},{"ValueError","value"},{"AttributeError","attribute"},{"PermissionError","permission"},
        {"FileNotFoundError","file_not_found"},{"OSError","os"},{"RuntimeError","runtime"},{"MemoryError","memory"},
        {"TimeoutError","timeout"},{"JSONDecodeError","json_decode"}}};
    for(auto [name,label]:types)if(type==name)return "owner_bootstrap_"+std::string(label)+"_error";
    return code;
}
inline Json Record(int action,std::string_view failure,double finished,unsigned long pid){
    constexpr std::array<const char*,6> modes={"serve","initialize","refresh","recover","reconfigure","qualify"};
    return {{"version",2},{"operation",action>=0&&action<int(modes.size())?modes[action]:"unknown"},
        {"result",failure.empty()?"Completed":"Failed"},
        {"error_code",failure.empty()?Json(nullptr):Json(ErrorCode(failure))},{"finished",finished},{"pid",pid}};
}
inline Json OwnerRecord(std::string_view failure,double finished,unsigned long pid){
    auto record=Record(-1,failure.empty()?"authority_operation_failed":failure,finished,pid);
    record["operation"]="owner-bootstrap";return record;
}
}
