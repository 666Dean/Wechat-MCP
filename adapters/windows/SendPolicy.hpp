// SPDX-License-Identifier: MIT
#pragma once
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace WeChat {
struct Activity {
    bool desktop = false;
    bool foreground = false;
    double idle = -1;
};

inline double IdleSeconds(std::uint64_t now, std::uint32_t last) {
    auto elapsed=std::uint32_t(std::uint32_t(now)-last);
    return elapsed<86400000 && elapsed<=now ? double(elapsed)/1000. : -1.;
}

// OS facts come from the interactive helper, never the service's session zero.
// A continuation must remain in the pinned window, but its own input must not
// cause another idle admission. The controller seals the phase in each Action.
inline bool NeedsActivation(const std::string& policy, int seconds, bool initial, const Activity& facts) {
    if ((policy != "immediate" && policy != "when_idle" && policy != "foreground_only") || seconds < 5 || seconds > 300)
        throw std::runtime_error("send_policy_invalid");
    if (!facts.desktop) throw std::runtime_error("interactive_desktop_unavailable");
    if (!initial) {
        if (!facts.foreground) throw std::runtime_error("foreground_changed");
        return false;
    }
    if (policy != "immediate") {
        if (!std::isfinite(facts.idle) || facts.idle < 0 || facts.idle >= 86400)
            throw std::runtime_error("activity_unavailable");
        if (facts.idle < seconds) throw std::runtime_error("user_active");
    }
    if (policy == "foreground_only" && !facts.foreground) throw std::runtime_error("foreground_required");
    return !facts.foreground;
}
}
