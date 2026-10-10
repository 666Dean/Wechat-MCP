// SPDX-License-Identifier: AGPL-3.0-only
#define NOMINMAX
#include <iostream>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Security.Credentials.UI.h>
#include "axr/Core.hpp"
int main(){using namespace winrt::Windows::Security::Credentials::UI;Stellaria::AXR::Json result;
    try{winrt::init_apartment(winrt::apartment_type::multi_threaded);std::string line;std::getline(std::cin,line);
        if(line.size()>1024||Stellaria::AXR::Json::parse(line).at("op")!="owner_auth")throw std::runtime_error("request_denied");
        auto status=UserConsentVerifier::CheckAvailabilityAsync().get();
        if(status!=UserConsentVerifierAvailability::Available)throw std::runtime_error("owner_auth_unavailable");
        auto verification=UserConsentVerifier::RequestVerificationAsync(L"Authorize the exact AXR operation shown in your local owner terminal.").get();
        result={{"verified",verification==UserConsentVerificationResult::Verified}};
    }catch(...){result={{"error","owner_auth_failed_or_unavailable"}};}
    std::cout<<result.dump()<<std::endl;return 0;}
