// SPDX-License-Identifier: AGPL-3.0-only
#include "axr/WindowsInstallation.hpp"
#if defined(_WIN32)
#define NOMINMAX
#include <windows.h>
#include <aclapi.h>
#include <sddl.h>
#include <shlobj.h>
#endif
namespace Stellaria::AXR {
std::filesystem::path WindowsInstallationRoot(){
#if defined(_WIN32)
    PWSTR value=nullptr;
    if(FAILED(SHGetKnownFolderPath(FOLDERID_ProgramFiles,KF_FLAG_DEFAULT,nullptr,&value)))
        throw std::runtime_error("authority_installation_unavailable");
    auto path=std::filesystem::path(value)/L"Stellaria AXR";CoTaskMemFree(value);return path;
#else
    throw std::runtime_error("windows_installation_required");
#endif
}
#if defined(_WIN32)
namespace {
void Protected(const std::filesystem::path& path,bool ancestor){
    auto attributes=GetFileAttributesW(path.c_str());
    if(attributes==INVALID_FILE_ATTRIBUTES)throw std::runtime_error("authority_installation_unavailable");
    if(attributes&FILE_ATTRIBUTE_REPARSE_POINT)throw std::runtime_error("authority_installation_reparse_denied");
    PSID owner=nullptr;PACL acl=nullptr;PSECURITY_DESCRIPTOR descriptor=nullptr;
    auto status=GetNamedSecurityInfoW(path.c_str(),SE_FILE_OBJECT,OWNER_SECURITY_INFORMATION|DACL_SECURITY_INFORMATION,
        &owner,nullptr,&acl,nullptr,&descriptor);
    struct Release {PSECURITY_DESCRIPTOR value;~Release(){if(value)LocalFree(value);}} release{descriptor};
    struct InstallerSid {PSID value=nullptr;
        InstallerSid(){if(!ConvertStringSidToSidW(L"S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",&value))
            throw std::runtime_error("authority_installation_acl_unavailable");}
        ~InstallerSid(){if(value)LocalFree(value);}};
    static const InstallerSid installer;
    auto trusted=[&](PSID sid){return sid&&(IsWellKnownSid(sid,WinLocalSystemSid)||IsWellKnownSid(sid,WinBuiltinAdministratorsSid)||EqualSid(sid,installer.value));};
    if(status!=ERROR_SUCCESS||!acl)throw std::runtime_error("authority_installation_acl_unavailable");
    if(!trusted(owner))throw std::runtime_error("authority_installation_not_protected");
    for(DWORD i=0;i<acl->AceCount;++i){void* raw=nullptr;
        if(!GetAce(acl,i,&raw))throw std::runtime_error("authority_installation_not_protected");
        auto header=static_cast<ACE_HEADER*>(raw);
        if((header->AceFlags&INHERIT_ONLY_ACE)||header->AceType==ACCESS_DENIED_ACE_TYPE)continue;
        if(header->AceType!=ACCESS_ALLOWED_ACE_TYPE)throw std::runtime_error("authority_installation_not_protected");
        auto ace=static_cast<ACCESS_ALLOWED_ACE*>(raw);
        DWORD writes=FILE_WRITE_DATA|FILE_APPEND_DATA|FILE_WRITE_EA|FILE_WRITE_ATTRIBUTES|FILE_DELETE_CHILD|
            DELETE|WRITE_DAC|WRITE_OWNER|GENERIC_WRITE|GENERIC_ALL;
        if(ancestor)writes&=~(FILE_WRITE_DATA|FILE_APPEND_DATA); // Creating a sibling does not replace this protected directory.
        if((ace->Mask&writes)&&!trusted(&ace->SidStart))throw std::runtime_error("authority_installation_not_protected");
    }
}
}
#endif
void VerifyWindowsInstallation(const std::filesystem::path& directory){
#if defined(_WIN32)
    for(auto parent=directory;!parent.empty();parent=parent.parent_path()){
        Protected(parent,parent!=directory);if(parent==parent.root_path())break;
    }
    size_t count=0;
    for(const auto& entry:std::filesystem::recursive_directory_iterator(directory)){
        if(++count>20000)throw std::runtime_error("authority_installation_budget");
        Protected(entry.path(),false);
    }
#else
    (void)directory;throw std::runtime_error("windows_installation_required");
#endif
}
}
