// SPDX-License-Identifier: AGPL-3.0-only
#include "axr/WindowsHello.hpp"
#include "axr/TrustRoot.hpp"
#include "axr/Security.hpp"
#if defined(_WIN32)
#define NOMINMAX
#include <windows.h>
#include <aclapi.h>
#include <sddl.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Security.Credentials.h>
#include <winrt/Windows.Security.Cryptography.h>
#include <winrt/Windows.Security.Cryptography.Core.h>
#include <winrt/Windows.Storage.Streams.h>
#include <chrono>
#endif
namespace Stellaria::AXR {
namespace {
#if defined(_WIN32)
using namespace winrt::Windows::Security::Credentials;
using namespace winrt::Windows::Security::Cryptography;
using namespace winrt::Windows::Security::Cryptography::Core;
void Protected(const std::filesystem::path& path,bool ancestor=false){
    auto attributes=GetFileAttributesW(path.c_str());
    if(attributes==INVALID_FILE_ATTRIBUTES||(attributes&FILE_ATTRIBUTE_REPARSE_POINT))
        throw std::runtime_error("hello_owner_installation_required");
    PSID owner=nullptr;PACL acl=nullptr;PSECURITY_DESCRIPTOR descriptor=nullptr;
    auto status=GetNamedSecurityInfoW(path.c_str(),SE_FILE_OBJECT,
        OWNER_SECURITY_INFORMATION|DACL_SECURITY_INFORMATION,&owner,nullptr,&acl,nullptr,&descriptor);
    struct Release {PSECURITY_DESCRIPTOR value;~Release(){if(value)LocalFree(value);}} release{descriptor};
    struct InstallerSid {
        PSID value=nullptr;
        InstallerSid(){if(!ConvertStringSidToSidW(L"S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",&value))
            throw std::runtime_error("hello_owner_installation_required");}
        ~InstallerSid(){if(value)LocalFree(value);}
    };
    static const InstallerSid installer;
    auto trusted=[&](PSID sid){return sid&&(IsWellKnownSid(sid,WinLocalSystemSid)||
        IsWellKnownSid(sid,WinBuiltinAdministratorsSid)||EqualSid(sid,installer.value));};
    if(status!=ERROR_SUCCESS||!acl||!trusted(owner))throw std::runtime_error("hello_owner_installation_required");
    for(DWORD i=0;i<acl->AceCount;++i){
        void* raw=nullptr;if(!GetAce(acl,i,&raw))throw std::runtime_error("hello_owner_installation_required");
        auto header=static_cast<ACE_HEADER*>(raw);
        if(header->AceFlags&INHERIT_ONLY_ACE)continue; // Does not apply to this object.
        if(header->AceType==ACCESS_DENIED_ACE_TYPE)continue;
        if(header->AceType!=ACCESS_ALLOWED_ACE_TYPE)throw std::runtime_error("hello_owner_installation_required");
        auto ace=static_cast<ACCESS_ALLOWED_ACE*>(raw);
        DWORD writes=FILE_WRITE_DATA|FILE_APPEND_DATA|FILE_WRITE_EA|FILE_WRITE_ATTRIBUTES|
            FILE_DELETE_CHILD|DELETE|WRITE_DAC|WRITE_OWNER|GENERIC_WRITE|GENERIC_ALL;
        // Creating a sibling in an ancestor cannot replace an already protected
        // directory. Delete-child, metadata and ACL modification still deny.
        if(ancestor)writes&=~(FILE_WRITE_DATA|FILE_APPEND_DATA);
        if((ace->Mask&writes)&&!trusted(&ace->SidStart))throw std::runtime_error("hello_owner_installation_required");
    }
}
void OwnerHost(){
    // Always enforced, including reference builds: tests must never pop Hello.
    auto identity=ProcessIdentity(GetCurrentProcessId());
    auto image=Utf8Path(identity.at("image").get<std::string>());
    if(image.filename()!=L"axr-owner.exe")throw std::runtime_error("hello_protected_owner_host_required");
    DWORD session=0;
    if(identity.at("user")=="S-1-5-18"||!ProcessIdToSessionId(GetCurrentProcessId(),&session)||session==0)
        throw std::runtime_error("hello_interactive_owner_required");
    auto root=image.parent_path();
    for(auto parent=root;!parent.empty();parent=parent.parent_path()){
        Protected(parent,parent!=root);if(parent==parent.root_path())break;
    }
    size_t entries=0;
    for(const auto& entry:std::filesystem::recursive_directory_iterator(root)){
        if(++entries>20000)throw std::runtime_error("hello_owner_installation_budget");
        Protected(entry.path());
    }
}
template<class Operation> auto Await(Operation operation,std::chrono::seconds budget){
    using winrt::Windows::Foundation::AsyncStatus;
    if(operation.wait_for(budget)!=AsyncStatus::Completed){
        operation.Cancel();throw std::runtime_error("hello_operation_cancelled_failed_or_expired");
    }
    return operation.GetResults();
}
struct Apartment {
    Apartment(){winrt::init_apartment(winrt::apartment_type::multi_threaded);}
    ~Apartment(){winrt::uninit_apartment();}
};
std::string Bytes(const winrt::Windows::Storage::Streams::IBuffer& buffer,size_t maximum){
    if(!buffer||buffer.Length()>maximum)throw std::runtime_error("hello_result_budget");
    winrt::com_array<uint8_t> bytes;CryptographicBuffer::CopyToByteArray(buffer,bytes);
    return std::string(reinterpret_cast<const char*>(bytes.data()),bytes.size());
}
#endif
}
struct WindowsHelloOwnerKey::Impl {
    std::string publicKey;
#if defined(_WIN32)
    KeyCredential key{nullptr};
#endif
};
WindowsHelloOwnerKey::WindowsHelloOwnerKey(std::string expectedPublicKey):impl_(std::make_unique<Impl>()){
    if(expectedPublicKey.size()!=294)throw std::runtime_error("hello_enrolled_public_key_required");
#if defined(_WIN32)
    OwnerHost(); // Before WinRT initialization, discovery or any possible UI.
    try{
        Apartment apartment;
        if(!Await(KeyCredentialManager::IsSupportedAsync(),std::chrono::seconds(15)))
            throw std::runtime_error("hello_provider_unavailable");
        auto result=Await(KeyCredentialManager::OpenAsync(L"Stellaria.AXR.Owner.v2.owner-presence-v2"),std::chrono::seconds(15));
        if(result.Status()!=KeyCredentialStatus::Success)throw std::runtime_error("hello_enrolled_credential_unavailable");
        impl_->key=result.Credential();
        auto publicKey=Bytes(impl_->key.RetrievePublicKey(CryptographicPublicKeyBlobType::X509SubjectPublicKeyInfo),294);
        if(!ConstantEqual(publicKey,expectedPublicKey))throw std::runtime_error("hello_enrolled_public_key_changed");
        impl_->publicKey=std::move(publicKey);
    }catch(const winrt::hresult_error&){throw std::runtime_error("hello_provider_failed_or_unavailable");}
#else
    throw std::runtime_error("windows_hello_required");
#endif
}
WindowsHelloOwnerKey::~WindowsHelloOwnerKey()=default;
std::string WindowsHelloOwnerKey::PublicKey() const {return impl_->publicKey;}
Json WindowsHelloOwnerKey::Attestation() const {
#if defined(_WIN32)
    try{
        Apartment apartment;
        auto result=Await(impl_->key.GetAttestationAsync(),std::chrono::seconds(30));
        if(result.Status()!=KeyCredentialAttestationStatus::Success)throw std::runtime_error("hello_attestation_unavailable");
        auto statement=Bytes(result.AttestationBuffer(),65536),chain=Bytes(result.CertificateChainBuffer(),65536);
        auto hex=[](std::string_view value){constexpr char digits[]="0123456789abcdef";std::string out;out.reserve(value.size()*2);
            for(unsigned char c:value){out+=digits[c>>4];out+=digits[c&15];}return out;};
        return {{"statement",hex(statement)},{"certificate_chain",hex(chain)}};
    }catch(const winrt::hresult_error&){throw std::runtime_error("hello_attestation_failed_or_unavailable");}
#else
    throw std::runtime_error("windows_hello_required");
#endif
}
std::string WindowsHelloOwnerKey::Sign(std::string_view message) const {
    if(message.empty()||message.size()>MaximumFrameBytes)throw std::runtime_error("hello_message_budget");
#if defined(_WIN32)
    try{
        Apartment apartment;
        auto bytes=winrt::array_view<const uint8_t>(reinterpret_cast<const uint8_t*>(message.data()),
            reinterpret_cast<const uint8_t*>(message.data()+message.size()));
        // RequestSignAsync prompts for each operation. Never reuse a boolean
        // UserConsentVerifier result or issue a silent TPM signature instead.
        auto result=Await(impl_->key.RequestSignAsync(CryptographicBuffer::CreateFromByteArray(bytes)),std::chrono::seconds(60));
        if(result.Status()!=KeyCredentialStatus::Success)throw std::runtime_error("hello_signature_cancelled_or_failed");
        auto signature=Bytes(result.Result(),256);
        if(!VerifyOwnerSignature(impl_->publicKey,message,signature))throw std::runtime_error("hello_signature_invalid");
        return signature;
    }catch(const winrt::hresult_error&){throw std::runtime_error("hello_signature_failed_or_unavailable");}
#else
    throw std::runtime_error("windows_hello_required");
#endif
}
}
