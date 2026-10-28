// SPDX-License-Identifier: MIT
// Synthetic activity only: never queries desktops, windows or user input.
#include "../../adapters/windows/SendPolicy.hpp"
#include <iostream>
#include <limits>

int main() {
    int checks=0;
    auto require=[&](bool value){++checks;if(!value)throw std::runtime_error("policy_test_failed");};
    auto denied=[&](const std::string& error, const std::string& policy, int seconds, bool initial, WeChat::Activity facts){
        try { WeChat::NeedsActivation(policy,seconds,initial,facts); }
        catch(const std::runtime_error& e){require(e.what()==error);return;}
        throw std::runtime_error("policy_should_have_denied");
    };
    try {
        require(WeChat::IdleSeconds(100,100)==0);
        require(WeChat::IdleSeconds(100,101)==-1);
        require(WeChat::IdleSeconds(86400100,100)==-1);
        require(WeChat::IdleSeconds(1,0xfffffffeu)==-1);
        require(WeChat::IdleSeconds(0x100000014ull,0xffffff00u)==.276);
        require(WeChat::NeedsActivation("immediate",15,true,{true,false,-1}));
        require(WeChat::NeedsActivation("when_idle",15,true,{true,false,15}));
        require(!WeChat::NeedsActivation("foreground_only",15,true,{true,true,15}));
        denied("user_active","when_idle",15,true,{true,true,14.999});
        denied("foreground_required","foreground_only",15,true,{true,false,20});
        for(auto policy:{"immediate","when_idle","foreground_only"}) {
            require(!WeChat::NeedsActivation(policy,15,false,{true,true,0}));
            denied("foreground_changed",policy,15,false,{true,false,90});
            denied("interactive_desktop_unavailable",policy,15,true,{false,true,90});
            denied("interactive_desktop_unavailable",policy,15,false,{false,true,90});
        }
        for(double idle:{-1.,86400.,std::numeric_limits<double>::infinity(),std::numeric_limits<double>::quiet_NaN()})
            denied("activity_unavailable","when_idle",15,true,{true,true,idle});
        for(auto policy:{"background_when_idle","unknown"})denied("send_policy_invalid",policy,15,true,{true,true,90});
        for(int seconds:{4,301})denied("send_policy_invalid","when_idle",seconds,true,{true,true,90});
        std::cout<<"synthetic send policy checks: "<<checks<<"; no OS activity sampled\n";
    } catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
