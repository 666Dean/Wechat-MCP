// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Stellaria-Commercial-1.0
#define NOMINMAX
#include "../src/WindowsInstallationAcl.hpp"
#include <cassert>
#include <iostream>
#include <string>

namespace {
void Check(const std::wstring& sddl,bool ancestor,bool expected){
    PSECURITY_DESCRIPTOR descriptor=nullptr;
    assert(ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(),SDDL_REVISION_1,&descriptor,nullptr));
    PSID owner=nullptr;PACL acl=nullptr;BOOL defaulted=FALSE,present=FALSE;
    assert(GetSecurityDescriptorOwner(descriptor,&owner,&defaulted));
    assert(GetSecurityDescriptorDacl(descriptor,&present,&acl,&defaulted));
    bool accepted=false;
    try{Stellaria::AXR::WindowsInstallationAcl::Verify(owner,acl,ancestor);accepted=true;}
    catch(const std::runtime_error&){}
    LocalFree(descriptor);
    assert(accepted==expected);
}
}

int main(){
    // Actual ProgramData-style directory ACEs, parsed by Windows itself.
    const std::wstring defaults=L"O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;BU)(A;;0x116;;;BU)";
    Check(defaults,true,true);Check(defaults,false,false);
    for(const auto& rights:{L"0x2",L"0x4",L"0x10",L"0x100",L"0x110",L"0x116"}){
        auto descriptor=L"O:SYD:P(A;;"+std::wstring(rights)+L";;;BU)";
        Check(descriptor,true,true);Check(descriptor,false,false);
    }
    for(const auto& rights:{L"0x40",L"SD",L"WD",L"WO",L"GW",L"GA",L"0x156",L"0x10116",L"0x40116",L"0x80116"}){
        auto descriptor=L"O:SYD:P(A;;"+std::wstring(rights)+L";;;BU)";
        Check(descriptor,true,false);Check(descriptor,false,false);
    }
    for(const auto& sid:{L"SY",L"BA",L"S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"}){
        auto descriptor=L"O:"+std::wstring(sid)+L"D:P(A;;FA;;;"+sid+L")";
        Check(descriptor,true,true);Check(descriptor,false,true);
    }
    Check(L"O:BUD:P(A;;GRGX;;;BU)",true,false);
    Check(L"O:BUD:P(A;;GRGX;;;BU)",false,false);
    Check(L"O:SYD:NO_ACCESS_CONTROL",true,false);
    Check(L"O:SYD:NO_ACCESS_CONTROL",false,false);
    Check(L"O:SYD:P(A;;GRGX;;;BU)(A;OIIO;GA;;;BU)",true,true);
    Check(L"O:SYD:P(A;;GRGX;;;BU)(A;OIIO;GA;;;BU)",false,true);
    std::cout<<"46 native synthetic ACL decisions passed; no filesystem ACL, service or credentials changed\n";
}
