// SPDX-License-Identifier: AGPL-3.0-only
#pragma once
#include "Core.hpp"
namespace Stellaria::AXR {
// Existing, enrolled owner credential only. No creation, replacement, deletion,
// software fallback or private-key export. Enrollment must qualify hardware
// separately; a successful Hello signature is not hardware attestation.
class WindowsHelloOwnerKey {
public:
    explicit WindowsHelloOwnerKey(std::string expectedPublicKey);
    ~WindowsHelloOwnerKey();
    WindowsHelloOwnerKey(const WindowsHelloOwnerKey&)=delete;
    WindowsHelloOwnerKey& operator=(const WindowsHelloOwnerKey&)=delete;
    std::string PublicKey() const;
    std::string Sign(std::string_view message) const;
    Json Attestation() const; // Untrusted evidence; verifier must check roots.
private:
    struct Impl;std::unique_ptr<Impl> impl_;
};
}
