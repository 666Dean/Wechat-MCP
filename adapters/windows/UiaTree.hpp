// SPDX-License-Identifier: MIT
#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <UIAutomation.h>
#include <wrl/client.h>
#include "UiaTraversal.hpp"

namespace WeChat {
inline std::vector<LONG> UiaRuntimeId(SAFEARRAY* value){
    LONG lower=0,upper=-1;VARTYPE type=VT_EMPTY;
    if(!value||SafeArrayGetDim(value)!=1||FAILED(SafeArrayGetVartype(value,&type))||type!=VT_I4||
            FAILED(SafeArrayGetLBound(value,1,&lower))||FAILED(SafeArrayGetUBound(value,1,&upper))||
            upper<lower||static_cast<long long>(upper)-lower+1>64)
        throw std::runtime_error("uia_runtime_identity_unavailable");
    LONG* data=nullptr;
    if(FAILED(SafeArrayAccessData(value,reinterpret_cast<void**>(&data)))||!data)
        throw std::runtime_error("uia_runtime_identity_unavailable");
    std::vector<LONG> result;
    try{result.assign(data,data+(static_cast<long long>(upper)-lower+1));}
    catch(...){SafeArrayUnaccessData(value);throw;}
    if(FAILED(SafeArrayUnaccessData(value)))throw std::runtime_error("uia_runtime_identity_unavailable");
    return result;
}

class UiaTree {
    using Element=Microsoft::WRL::ComPtr<IUIAutomationElement>;
    Microsoft::WRL::ComPtr<IUIAutomationTreeWalker> view,raw;
    static std::vector<LONG> Key(const Element& element){
        if(!element)throw std::runtime_error("uia_runtime_identity_unavailable");
        struct RuntimeArray {SAFEARRAY* value=nullptr;~RuntimeArray(){if(value)SafeArrayDestroy(value);}} id;
        if(FAILED(element->GetRuntimeId(&id.value)))throw std::runtime_error("uia_runtime_identity_unavailable");
        return UiaRuntimeId(id.value);
    }
public:
    UiaTree(IUIAutomation* automation,IUIAutomationTreeWalker* walker):view(walker){
        if(!automation||!view||FAILED(automation->get_RawViewWalker(&raw))||!raw)
            throw std::runtime_error("uia_tree_unavailable");
    }
    std::vector<Element> Children(Element root){
        return UiaChildren(root,Key,
            [&](const Element& value){Element result;
                if(FAILED(raw->GetParentElement(value.Get(),&result)))throw std::runtime_error("uia_parent_unavailable");return result;},
            [&](const Element& value){Element result;
                if(FAILED(view->GetFirstChildElement(value.Get(),&result)))throw std::runtime_error("uia_children_unavailable");return result;},
            [&](const Element& value){Element result;
                if(FAILED(view->GetNextSiblingElement(value.Get(),&result)))throw std::runtime_error("uia_children_unavailable");return result;});
    }
};
}
