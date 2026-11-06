// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Stellaria-Commercial-1.0
#include "../src/WindowsServiceResult.hpp"
#include <cassert>
#include <iostream>
using namespace Stellaria::AXR::WindowsServiceResult;
int main(){
    auto value=Record(1,"windows_owner_setup_launch_failed",1234.5,42);
    assert(value.at("operation")=="initialize"&&value.at("result")=="Failed");
    assert(value.at("error_code")=="windows_owner_setup_launch_failed"&&value.size()==6);
    assert(value.at("pid")==42&&value.at("finished")==1234.5);
    for(auto raw:{"C:\\private\\credential.key","secret message with spaces","wxid_private_account",
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "{\"error\":\"private\"}","windows_error\nprivate","windows_"})
        assert(Record(1,raw,1,1).at("error_code")=="authority_operation_failed");
    assert(ErrorCode(std::string(101,'a'))=="authority_operation_failed");
    assert(ErrorCode("protected_store_access_denied")=="protected_store_access_denied");
    assert(ErrorCode("hardware_signing_failed")=="hardware_signing_failed");
    assert(ErrorCode("identity_token_unavailable")=="identity_token_unavailable");
    assert(ErrorCode("ipc_peer_unavailable")=="ipc_peer_unavailable");
    auto success=Record(1,"",1,1);
    assert(success.at("result")=="Completed"&&success.at("error_code").is_null());
    assert(Record(5,"owner_hardware_enrollment_required",1,1).at("operation")=="qualify");
    assert(Record(-1,"native_error",1,1).at("operation")=="unknown");
    std::cout<<"bounded service machine codes, privacy rejection and advisory outcomes passed; no service started\n";
}
