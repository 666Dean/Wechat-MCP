// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Stellaria-Commercial-1.0
#pragma once
#include <windows.h>
#include <sddl.h>
#include <stdexcept>

namespace Stellaria::AXR::WindowsInstallationAcl {
inline bool Trusted(PSID sid){
    struct InstallerSid {
        PSID value=nullptr;
        InstallerSid(){
            if(!ConvertStringSidToSidW(L"S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",&value))
                throw std::runtime_error("authority_installation_acl_unavailable");
        }
        ~InstallerSid(){if(value)LocalFree(value);}
    };
    static const InstallerSid installer;
    return sid&&(IsWellKnownSid(sid,WinLocalSystemSid)||IsWellKnownSid(sid,WinBuiltinAdministratorsSid)||EqualSid(sid,installer.value));
}

inline void Verify(PSID owner,PACL acl,bool ancestor){
    if(!acl)throw std::runtime_error("authority_installation_acl_unavailable");
    if(!Trusted(owner))throw std::runtime_error("authority_installation_not_protected");
    for(DWORD i=0;i<acl->AceCount;++i){
        void* raw=nullptr;
        if(!GetAce(acl,i,&raw))throw std::runtime_error("authority_installation_not_protected");
        auto header=static_cast<ACE_HEADER*>(raw);
        if((header->AceFlags&INHERIT_ONLY_ACE)||header->AceType==ACCESS_DENIED_ACE_TYPE)continue;
        if(header->AceType!=ACCESS_ALLOWED_ACE_TYPE)throw std::runtime_error("authority_installation_not_protected");
        auto ace=static_cast<ACCESS_ALLOWED_ACE*>(raw);
        DWORD writes=FILE_WRITE_DATA|FILE_APPEND_DATA|FILE_WRITE_EA|FILE_WRITE_ATTRIBUTES|FILE_DELETE_CHILD|
            DELETE|WRITE_DAC|WRITE_OWNER|GENERIC_WRITE|GENERIC_ALL;
        // An ancestor contains the separately protected child on this path.
        // Sibling creation and ancestor metadata rights do not grant access to
        // that child. Its presence also prevents turning the ancestor into a
        // reparse point: FSCTL_SET_REPARSE_POINT rejects nonempty directories.
        // Retain deletion/replacement, ACL/owner and generic-write denials.
        // The application directory and every installed file retain all checks.
        if(ancestor)writes&=~(FILE_WRITE_DATA|FILE_APPEND_DATA|FILE_WRITE_EA|FILE_WRITE_ATTRIBUTES);
        if((ace->Mask&writes)&&!Trusted(&ace->SidStart))throw std::runtime_error("authority_installation_not_protected");
    }
}
}
