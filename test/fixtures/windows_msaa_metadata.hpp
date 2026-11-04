// SPDX-License-Identifier: MIT
// Manual diagnostics only. No names, values, focus, navigation or actions.
#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <oleacc.h>
#include <wrl/client.h>
#include <algorithm>
#include <map>
#include <set>
#include <stdexcept>
#include <vector>

namespace WeChat::Diagnostic {
using Microsoft::WRL::ComPtr;
struct MsaaCounts {
    unsigned nodes=0,objects=0,elements=0,textRoles=0,readonlyTextRoles=0;
    unsigned unknownRoles=0,unknownTextStates=0,repeatedObjects=0;
    bool nodeLimited=false,depthLimited=false;
    std::map<LONG,unsigned> roles;
    bool Complete() const {
        return !nodeLimited&&!depthLimited&&!unknownRoles&&!unknownTextStates&&!repeatedObjects;
    }
};
struct Variants {
    explicit Variants(std::size_t count):values(count) { for(auto& v:values)VariantInit(&v); }
    ~Variants(){for(auto& v:values)VariantClear(&v);}
    Variants(const Variants&)=delete;
    Variants& operator=(const Variants&)=delete;
    std::vector<VARIANT> values;
};
inline VARIANT Child(LONG id){VARIANT v{};v.vt=VT_I4;v.lVal=id;return v;}

// Injectable child enumeration is used only by the account-free COM fixture.
// Real manual execution uses the standard AccessibleChildren function.
template<class Enumerate>
MsaaCounts MsaaMetadata(IAccessible* root,Enumerate enumerate){
    if(!root)throw std::runtime_error("msaa_root_unavailable");
    MsaaCounts out;std::vector<ComPtr<IUnknown>> seen;
    auto role=[&](IAccessible* object,VARIANT child){
        Variants value(1);auto& v=value.values[0];
        if(object->get_accRole(child,&v)!=S_OK)throw std::runtime_error("msaa_role_unavailable");
        // Never inspect or export a custom string role or arbitrary numeric ID.
        if(v.vt!=VT_I4||v.lVal<ROLE_SYSTEM_TITLEBAR||v.lVal>ROLE_SYSTEM_OUTLINEBUTTON){++out.unknownRoles;return;}
        ++out.roles[v.lVal];
        if(v.lVal==ROLE_SYSTEM_TEXT){
            ++out.textRoles;Variants state(1);auto& s=state.values[0];
            if(object->get_accState(child,&s)!=S_OK||s.vt!=VT_I4)++out.unknownTextStates;
            else if(s.lVal&STATE_SYSTEM_READONLY)++out.readonlyTextRoles;
        }
    };
    auto walk=[&](auto&& self,IAccessible* object,unsigned depth)->void {
        if(out.nodes>=500){out.nodeLimited=true;return;}
        ++out.nodes;++out.objects;
        ComPtr<IUnknown> identity;
        if(FAILED(object->QueryInterface(IID_PPV_ARGS(&identity)))||!identity)
            throw std::runtime_error("msaa_object_identity_unavailable");
        for(const auto& known:seen)if(known.Get()==identity.Get()){++out.repeatedObjects;return;}
        seen.push_back(identity);role(object,Child(CHILDID_SELF));
        LONG count=0;
        if(object->get_accChildCount(&count)!=S_OK||count<0)throw std::runtime_error("msaa_child_count_unavailable");
        if(!count)return;
        if(depth==16){out.depthLimited=true;return;}
        const auto requested=std::min<LONG>(count,500-out.nodes);
        if(requested<count)out.nodeLimited=true;
        if(!requested)return;
        Variants children(requested);LONG obtained=0;
        if(enumerate(object,0,requested,children.values.data(),&obtained)!=S_OK||obtained!=requested)
            throw std::runtime_error("msaa_children_changed");
        std::set<LONG> ids;
        for(auto& child:children.values){
            if(out.nodes>=500){out.nodeLimited=true;break;}
            if(child.vt==VT_DISPATCH&&child.pdispVal){
                ComPtr<IAccessible> nested;
                if(FAILED(child.pdispVal->QueryInterface(IID_PPV_ARGS(&nested)))||!nested)
                    throw std::runtime_error("msaa_child_interface_unavailable");
                self(self,nested.Get(),depth+1);
            }else if(child.vt==VT_I4&&child.lVal>CHILDID_SELF&&ids.insert(child.lVal).second){
                ++out.nodes;++out.elements;role(object,child);
            }else throw std::runtime_error("msaa_child_type_unavailable");
        }
    };
    walk(walk,root,0);if(out.nodes>=500)out.nodeLimited=true;return out;
}
inline MsaaCounts MsaaMetadata(IAccessible* root){return MsaaMetadata(root,AccessibleChildren);}
}
