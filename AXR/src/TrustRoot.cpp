// SPDX-License-Identifier: AGPL-3.0-only
#include "axr/TrustRoot.hpp"
#include "axr/Security.hpp"
#include <algorithm>
#include <array>
#include <openssl/core_names.h>
#include <openssl/evp.h>
#include <openssl/ec.h>
#include <openssl/ecdsa.h>
#include <openssl/rsa.h>
#include <openssl/x509.h>
#if defined(__APPLE__)
#include <Security/Security.h>
#include <unistd.h>
#elif defined(_WIN32)
#define NOMINMAX
#include <windows.h>
#include <ncrypt.h>
#include <bcrypt.h>
#endif
#ifndef AXR_OWNER_KEYCHAIN_GROUP
#define AXR_OWNER_KEYCHAIN_GROUP ""
#endif
#ifndef AXR_AUTHORITY_KEYCHAIN_GROUP
#define AXR_AUTHORITY_KEYCHAIN_GROUP ""
#endif
namespace Stellaria::AXR {
namespace {
[[noreturn]] void Unavailable(){throw std::runtime_error("hardware_trust_root_unavailable");}
#if defined(__APPLE__)
CFStringRef Name(std::string_view value){return CFStringCreateWithBytes(nullptr,reinterpret_cast<const UInt8*>(value.data()),value.size(),kCFStringEncodingUTF8,false);}
std::string Bytes(CFDataRef v){return std::string(reinterpret_cast<const char*>(CFDataGetBytePtr(v)),CFDataGetLength(v));}
#endif
}
struct HardwareSigningKey::Impl {
#if defined(__APPLE__)
    SecKeyRef key=nullptr;
    ~Impl(){if(key)CFRelease(key);}
#elif defined(_WIN32)
    NCRYPT_PROV_HANDLE provider=0;NCRYPT_KEY_HANDLE key=0;
    ~Impl(){if(key)NCryptFreeObject(key);if(provider)NCryptFreeObject(provider);}
#endif
};
HardwareSigningKey::HardwareSigningKey(std::string name,bool create,bool userPresence,bool ownerInteraction):impl_(std::make_unique<Impl>()){
    if(name.empty()||name.size()>128||!std::all_of(name.begin(),name.end(),[](unsigned char c){return (c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='.'||c=='-'||c=='_';}))throw std::runtime_error("trust_root_name_invalid");
#if defined(AXR_SECURITY_RELEASE) && defined(__APPLE__)
    const auto caller=ProcessIdentity(unsigned(getpid()));
    const char* expected=userPresence?"org.stellaria.axr.owner":"org.stellaria.axr.authority";
    if(caller.at("signature_valid")!=true||caller.at("hardened_runtime")!=true||caller.at("signing_id")!=expected)
        throw std::runtime_error("trust_root_process_identity_required");
#elif defined(AXR_SECURITY_RELEASE) && defined(_WIN32)
    if(!userPresence&&ProcessIdentity(GetCurrentProcessId()).at("user")!="S-1-5-18")
        throw std::runtime_error("trust_root_process_identity_required");
#endif
#if defined(__APPLE__)
    // Separate names prevent silently reopening a background key as an owner
    // presence key. Provisioning selects a purpose, not a mutable runtime flag.
    name+=userPresence?".owner-presence-v2":".authority-v2";
    auto tag=CFDataCreate(nullptr,reinterpret_cast<const UInt8*>(name.data()),name.size());
    const void* keys[]={kSecClass,kSecAttrApplicationTag,kSecAttrKeyType,kSecReturnRef,kSecUseAuthenticationUI};
    const void* values[]={kSecClassKey,tag,kSecAttrKeyTypeECSECPrimeRandom,kCFBooleanTrue,(ownerInteraction||userPresence)?kSecUseAuthenticationUIAllow:kSecUseAuthenticationUIFail};
    auto immutable=CFDictionaryCreate(nullptr,keys,values,5,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    auto query=CFDictionaryCreateMutableCopy(nullptr,0,immutable);CFRelease(immutable);
    CFStringRef group=nullptr;
    const std::string_view accessGroup=userPresence?AXR_OWNER_KEYCHAIN_GROUP:AXR_AUTHORITY_KEYCHAIN_GROUP;
#if defined(AXR_SECURITY_RELEASE) && !defined(AXR_OWNER_DEPLOYMENT)
    if(accessGroup.empty()){CFRelease(query);CFRelease(tag);throw std::runtime_error("protected_keychain_group_not_configured");}
#endif
    if(!accessGroup.empty()){
        group=Name(accessGroup);CFDictionarySetValue(query,kSecAttrAccessGroup,group);
        CFDictionarySetValue(query,kSecUseDataProtectionKeychain,kCFBooleanTrue);
    }
    struct GroupRelease {CFStringRef value;~GroupRelease(){if(value)CFRelease(value);}} releaseGroup{group};
    CFTypeRef found=nullptr;auto status=SecItemCopyMatching(query,&found);CFRelease(query);
    if(status==errSecSuccess){impl_->key=(SecKeyRef)found;CFRelease(tag);}
    else if(create&&status==errSecItemNotFound){
        CFErrorRef error=nullptr;
        auto control=SecAccessControlCreateWithFlags(nullptr,kSecAttrAccessibleWhenUnlockedThisDeviceOnly,SecAccessControlCreateFlags(kSecAccessControlPrivateKeyUsage|(userPresence?kSecAccessControlUserPresence:0)),&error);
        if(error){CFRelease(error);error=nullptr;}if(!control){CFRelease(tag);Unavailable();}
        const void* privateKeys[]={kSecAttrIsPermanent,kSecAttrApplicationTag,kSecAttrAccessControl};
        const void* privateValues[]={kCFBooleanTrue,tag,control};
        auto attrs=CFDictionaryCreate(nullptr,privateKeys,privateValues,3,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
        int bits=256;auto size=CFNumberCreate(nullptr,kCFNumberIntType,&bits);
        const void* rootKeys[]={kSecAttrKeyType,kSecAttrKeySizeInBits,kSecAttrTokenID,kSecPrivateKeyAttrs};
        const void* rootValues[]={kSecAttrKeyTypeECSECPrimeRandom,size,kSecAttrTokenIDSecureEnclave,attrs};
        auto immutableParameters=CFDictionaryCreate(nullptr,rootKeys,rootValues,4,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
        auto parameters=CFDictionaryCreateMutableCopy(nullptr,0,immutableParameters);CFRelease(immutableParameters);
        if(group){CFDictionarySetValue(parameters,kSecAttrAccessGroup,group);CFDictionarySetValue(parameters,kSecUseDataProtectionKeychain,kCFBooleanTrue);}
        impl_->key=SecKeyCreateRandomKey(parameters,&error);
        if(error){CFRelease(error);error=nullptr;}CFRelease(parameters);CFRelease(size);CFRelease(attrs);CFRelease(control);CFRelease(tag);
        if(!impl_->key)Unavailable();
    }else{CFRelease(tag);Unavailable();}
    auto attrs=SecKeyCopyAttributes(impl_->key);
    if(!attrs)Unavailable();auto token=CFDictionaryGetValue(attrs,kSecAttrTokenID);
    bool hardware=token&&CFEqual(token,kSecAttrTokenIDSecureEnclave);CFRelease(attrs);if(!hardware)Unavailable();
#elif defined(_WIN32)
    if(NCryptOpenStorageProvider(&impl_->provider,MS_PLATFORM_CRYPTO_PROVIDER,0)!=ERROR_SUCCESS)Unavailable();
    DWORD type=0,n=0;
    if(NCryptGetProperty(impl_->provider,NCRYPT_IMPL_TYPE_PROPERTY,reinterpret_cast<PBYTE>(&type),sizeof(type),&n,0)!=ERROR_SUCCESS||!(type&NCRYPT_IMPL_HARDWARE_FLAG))Unavailable();
    if(userPresence)throw std::runtime_error("windows_owner_presence_key_requires_enrolled_hello_provider");
    // TPM background signing is implemented. Owner presence must use the
    // enrolled Hello key provider; never silently substitute a silent TPM key.
    name+=".authority-v2";
    std::wstring wide(name.begin(),name.end());auto status=NCryptOpenKey(impl_->provider,&impl_->key,wide.c_str(),0,ownerInteraction?0:NCRYPT_SILENT_FLAG);
    if(status!=ERROR_SUCCESS){
        if(!create||status!=NTE_BAD_KEYSET)Unavailable();
        if(NCryptCreatePersistedKey(impl_->provider,&impl_->key,NCRYPT_ECDSA_P256_ALGORITHM,wide.c_str(),0,0)!=ERROR_SUCCESS)Unavailable();
        DWORD usage=NCRYPT_ALLOW_SIGNING_FLAG,exportPolicy=0;
        if(NCryptSetProperty(impl_->key,NCRYPT_KEY_USAGE_PROPERTY,reinterpret_cast<PBYTE>(&usage),sizeof(usage),0)!=ERROR_SUCCESS||
           NCryptSetProperty(impl_->key,NCRYPT_EXPORT_POLICY_PROPERTY,reinterpret_cast<PBYTE>(&exportPolicy),sizeof(exportPolicy),0)!=ERROR_SUCCESS||
           NCryptFinalizeKey(impl_->key,NCRYPT_SILENT_FLAG)!=ERROR_SUCCESS)Unavailable();
    }
#else
    (void)create;(void)userPresence;(void)ownerInteraction;Unavailable();
#endif
}
HardwareSigningKey::~HardwareSigningKey()=default;
std::string HardwareSigningKey::Provider() const {
#if defined(__APPLE__)
    return "SecureEnclave/P256";
#elif defined(_WIN32)
    return "MicrosoftPlatformCryptoProvider/P256";
#else
    Unavailable();
#endif
}
std::string HardwareSigningKey::PublicKey() const {
#if defined(__APPLE__)
    auto publicKey=SecKeyCopyPublicKey(impl_->key);if(!publicKey)Unavailable();
    CFErrorRef error=nullptr;auto data=SecKeyCopyExternalRepresentation(publicKey,&error);CFRelease(publicKey);
    if(error){CFRelease(error);error=nullptr;}if(!data)Unavailable();auto result=Bytes(data);CFRelease(data);return result;
#elif defined(_WIN32)
    DWORD n=0;if(NCryptExportKey(impl_->key,0,BCRYPT_ECCPUBLIC_BLOB,nullptr,nullptr,0,&n,0)!=ERROR_SUCCESS)Unavailable();
    std::vector<unsigned char> buffer(n);if(NCryptExportKey(impl_->key,0,BCRYPT_ECCPUBLIC_BLOB,nullptr,buffer.data(),n,&n,0)!=ERROR_SUCCESS||n!=sizeof(BCRYPT_ECCKEY_BLOB)+64)Unavailable();
    auto header=reinterpret_cast<BCRYPT_ECCKEY_BLOB*>(buffer.data());if(header->cbKey!=32||header->dwMagic!=BCRYPT_ECDSA_PUBLIC_P256_MAGIC)Unavailable();
    return std::string(1,'\x04')+std::string(reinterpret_cast<char*>(buffer.data()+sizeof(BCRYPT_ECCKEY_BLOB)),64);
#else
    Unavailable();
#endif
}
std::string HardwareSigningKey::Sign(std::string_view message) const {
    if(message.size()>MaximumFrameBytes)throw std::runtime_error("trust_root_message_budget");
#if defined(__APPLE__)
    auto bytes=CFDataCreate(nullptr,reinterpret_cast<const UInt8*>(message.data()),message.size());CFErrorRef error=nullptr;
    auto signature=SecKeyCreateSignature(impl_->key,kSecKeyAlgorithmECDSASignatureMessageX962SHA256,bytes,&error);CFRelease(bytes);
    if(error){CFRelease(error);error=nullptr;}if(!signature)Unavailable();auto result=Bytes(signature);CFRelease(signature);return result;
#elif defined(_WIN32)
    std::array<unsigned char,32> hash{};unsigned size=0;
    if(EVP_Digest(message.data(),message.size(),hash.data(),&size,EVP_sha256(),nullptr)!=1)Unavailable();
    std::array<unsigned char,64> raw{};DWORD n=0;
    if(NCryptSignHash(impl_->key,nullptr,hash.data(),DWORD(hash.size()),raw.data(),DWORD(raw.size()),&n,NCRYPT_SILENT_FLAG)!=ERROR_SUCCESS||n!=64)Unavailable();
    auto signature=ECDSA_SIG_new();if(!signature)Unavailable();
    if(ECDSA_SIG_set0(signature,BN_bin2bn(raw.data(),32,nullptr),BN_bin2bn(raw.data()+32,32,nullptr))!=1){ECDSA_SIG_free(signature);Unavailable();}
    int length=i2d_ECDSA_SIG(signature,nullptr);if(length<=0){ECDSA_SIG_free(signature);Unavailable();}
    std::string result(length,'\0');auto p=reinterpret_cast<unsigned char*>(result.data());i2d_ECDSA_SIG(signature,&p);ECDSA_SIG_free(signature);return result;
#else
    Unavailable();
#endif
}
bool VerifyRootSignature(std::string_view publicKey,std::string_view message,std::string_view signature){
    if(publicKey.size()!=65||publicKey.front()!='\x04'||message.size()>MaximumFrameBytes||signature.empty()||signature.size()>80)return false;
    std::unique_ptr<EVP_PKEY_CTX,decltype(&EVP_PKEY_CTX_free)> keyContext(EVP_PKEY_CTX_new_from_name(nullptr,"EC",nullptr),EVP_PKEY_CTX_free);
    if(!keyContext||EVP_PKEY_fromdata_init(keyContext.get())!=1)return false;
    char group[]="prime256v1";
    OSSL_PARAM parameters[]={OSSL_PARAM_construct_utf8_string(OSSL_PKEY_PARAM_GROUP_NAME,group,0),OSSL_PARAM_construct_octet_string(OSSL_PKEY_PARAM_PUB_KEY,const_cast<char*>(publicKey.data()),publicKey.size()),OSSL_PARAM_construct_end()};
    EVP_PKEY* raw=nullptr;if(EVP_PKEY_fromdata(keyContext.get(),&raw,EVP_PKEY_PUBLIC_KEY,parameters)!=1)return false;
    std::unique_ptr<EVP_PKEY,decltype(&EVP_PKEY_free)> key(raw,EVP_PKEY_free);
    std::unique_ptr<EVP_MD_CTX,decltype(&EVP_MD_CTX_free)> context(EVP_MD_CTX_new(),EVP_MD_CTX_free);
    return context&&EVP_DigestVerifyInit(context.get(),nullptr,EVP_sha256(),nullptr,key.get())==1&&
        EVP_DigestVerify(context.get(),reinterpret_cast<const unsigned char*>(signature.data()),signature.size(),reinterpret_cast<const unsigned char*>(message.data()),message.size())==1;
}
bool VerifyOwnerSignature(std::string_view publicKey,std::string_view message,std::string_view signature){
    if(publicKey.size()==65)return VerifyRootSignature(publicKey,message,signature);
#if defined(_WIN32)
    // A bounded canonical profile, not generic ASN.1 algorithm negotiation.
    // Never accept this format as an authority root or execution permit key.
    if(publicKey.size()!=294||signature.size()!=256||message.size()>MaximumFrameBytes)return false;
    auto cursor=reinterpret_cast<const unsigned char*>(publicKey.data());
    const auto end=cursor+publicKey.size();
    std::unique_ptr<EVP_PKEY,decltype(&EVP_PKEY_free)> key(d2i_PUBKEY(nullptr,&cursor,long(publicKey.size())),EVP_PKEY_free);
    if(!key||cursor!=end||EVP_PKEY_is_a(key.get(),"RSA")!=1||EVP_PKEY_get_bits(key.get())!=2048)return false;
    BIGNUM* rawExponent=nullptr;
    if(EVP_PKEY_get_bn_param(key.get(),OSSL_PKEY_PARAM_RSA_E,&rawExponent)!=1)return false;
    std::unique_ptr<BIGNUM,decltype(&BN_free)> exponent(rawExponent,BN_free);
    if(!BN_is_word(exponent.get(),65537))return false;
    int size=i2d_PUBKEY(key.get(),nullptr);if(size!=int(publicKey.size()))return false;
    std::string encoded(size,'\0');auto output=reinterpret_cast<unsigned char*>(encoded.data());
    if(i2d_PUBKEY(key.get(),&output)!=size||encoded!=publicKey)return false;
    std::unique_ptr<EVP_MD_CTX,decltype(&EVP_MD_CTX_free)> context(EVP_MD_CTX_new(),EVP_MD_CTX_free);
    EVP_PKEY_CTX* operation=nullptr;
    return context&&EVP_DigestVerifyInit(context.get(),&operation,EVP_sha256(),nullptr,key.get())==1&&
        operation&&EVP_PKEY_CTX_set_rsa_padding(operation,RSA_PKCS1_PADDING)>0&&
        EVP_DigestVerify(context.get(),reinterpret_cast<const unsigned char*>(signature.data()),signature.size(),
            reinterpret_cast<const unsigned char*>(message.data()),message.size())==1;
#else
    return false;
#endif
}
}
