// SPDX-License-Identifier: AGPL-3.0-only
#pragma once
#include "Core.hpp"
namespace Stellaria::AXR {
std::filesystem::path WindowsInstallationRoot();
// Fixed hosts derive this directory from their own actual OS image, never a
// model-supplied path. Validate the complete dependency tree and ancestors.
void VerifyWindowsInstallation(const std::filesystem::path& directory);
}
