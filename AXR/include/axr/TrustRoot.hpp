// SPDX-License-Identifier: AGPL-3.0-only
#pragma once
#include "Core.hpp"
namespace Stellaria::AXR {
// Used only in the trusted authority service. No private-key export operation.
// Provisioning is owner-controlled. No software fallback exists in this class.
class HardwareSigningKey {
public:
    explicit HardwareSigningKey(std::string name,bool create=false,bool userPresence=false,bool ownerInteraction=false);
    ~HardwareSigningKey();
    HardwareSigningKey(const HardwareSigningKey&)=delete;
    HardwareSigningKey& operator=(const HardwareSigningKey&)=delete;
    std::string PublicKey() const; // SEC1 uncompressed P-256 public point
    std::string Sign(std::string_view message) const; // DER ECDSA/SHA-256
    std::string Provider() const;
private:
    struct Impl;std::unique_ptr<Impl> impl_;
};
bool VerifyRootSignature(std::string_view publicKey,std::string_view message,std::string_view signature);
}
