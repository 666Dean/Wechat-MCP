// SPDX-License-Identifier: MIT
// Pure COM fixtures. Never enumerate windows or query a real application.
#include "windows_msaa_metadata.hpp"
#include <wrl/implements.h>
#include <climits>
#include <iostream>
#include <string>
using Microsoft::WRL::ComPtr;
using WeChat::Diagnostic::MsaaMetadata;
static unsigned forbiddenCalls=0;
static HRESULT Forbidden(){++forbiddenCalls;return E_ACCESSDENIED;}
class Object;
struct Entry {Object* object=nullptr;LONG role=ROLE_SYSTEM_PUSHBUTTON,state=0;};
class Object final : public Microsoft::WRL::RuntimeClass<
    Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>,IAccessible> {
public:
    LONG role=ROLE_SYSTEM_CLIENT,state=0,countOverride=LONG_MIN;
    VARTYPE roleType=VT_I4,stateType=VT_I4;
    HRESULT roleResult=S_OK,countResult=S_OK,enumerationResult=S_OK;
    bool duplicateIds=false,invalidChild=false,shortEnumeration=false;
    std::vector<Entry> children;
    HRESULT STDMETHODCALLTYPE get_accRole(VARIANT child,VARIANT* result) override {
        if(child.vt!=VT_I4||child.lVal<0||std::size_t(child.lVal)>children.size())return E_INVALIDARG;
        VariantInit(result);result->vt=roleType;
        if(roleType==VT_I4)result->lVal=child.lVal==CHILDID_SELF?role:children[child.lVal-1].role;
        else if(roleType==VT_BSTR)result->bstrVal=SysAllocString(L"synthetic private custom role");
        return roleResult;
    }
    HRESULT STDMETHODCALLTYPE get_accState(VARIANT child,VARIANT* result) override {
        if(child.vt!=VT_I4||child.lVal<0||std::size_t(child.lVal)>children.size())return E_INVALIDARG;
        VariantInit(result);result->vt=stateType;
        if(stateType==VT_I4)result->lVal=child.lVal==CHILDID_SELF?state:children[child.lVal-1].state;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE get_accChildCount(LONG* result) override {
        *result=countOverride==LONG_MIN?LONG(children.size()):countOverride;return countResult;
    }
    static HRESULT Enumerate(IAccessible* parent,LONG start,LONG requested,VARIANT* result,LONG* obtained){
        auto* object=static_cast<Object*>(parent);
        *obtained=std::min<LONG>(requested,LONG(object->children.size())-start);
        if(object->shortEnumeration&&*obtained>0)--*obtained;
        for(LONG i=0;i<*obtained;++i){
            auto& entry=object->children[start+i];
            if(object->invalidChild)result[i].vt=VT_EMPTY;
            else if(entry.object){result[i].vt=VT_DISPATCH;result[i].pdispVal=entry.object;entry.object->AddRef();}
            else {result[i].vt=VT_I4;result[i].lVal=object->duplicateIds?1:start+i+1;}
        }
        return object->enumerationResult;
    }
    // Every operation outside numeric role/state/count is forbidden by fixture.
    HRESULT STDMETHODCALLTYPE GetTypeInfoCount(UINT*) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE GetTypeInfo(UINT,LCID,ITypeInfo**) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE GetIDsOfNames(REFIID,LPOLESTR*,UINT,LCID,DISPID*) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE Invoke(DISPID,REFIID,LCID,WORD,DISPPARAMS*,VARIANT*,EXCEPINFO*,UINT*) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE get_accParent(IDispatch**) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE get_accChild(VARIANT,IDispatch**) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE get_accName(VARIANT,BSTR*) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE get_accValue(VARIANT,BSTR*) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE get_accDescription(VARIANT,BSTR*) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE get_accHelp(VARIANT,BSTR*) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE get_accHelpTopic(BSTR*,VARIANT,LONG*) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE get_accKeyboardShortcut(VARIANT,BSTR*) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE get_accFocus(VARIANT*) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE get_accSelection(VARIANT*) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE get_accDefaultAction(VARIANT,BSTR*) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE accSelect(LONG,VARIANT) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE accLocation(LONG*,LONG*,LONG*,LONG*,VARIANT) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE accNavigate(LONG,VARIANT,VARIANT*) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE accHitTest(LONG,LONG,VARIANT*) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE accDoDefaultAction(VARIANT) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE put_accName(VARIANT,BSTR) override{return Forbidden();}
    HRESULT STDMETHODCALLTYPE put_accValue(VARIANT,BSTR) override{return Forbidden();}
};

int main(){
    unsigned checks=0;
    auto require=[&](bool value){++checks;if(!value)throw std::runtime_error("msaa_fixture_check_failed");};
    auto inspect=[](Object* object){return MsaaMetadata(object,Object::Enumerate);};
    auto denied=[&](Object* object,const std::string& expected){
        try{inspect(object);}catch(const std::runtime_error& error){require(error.what()==expected);return;}
        throw std::runtime_error("msaa_fixture_should_reject");
    };
    try{
        auto root=Microsoft::WRL::Make<Object>(),text=Microsoft::WRL::Make<Object>();text->role=ROLE_SYSTEM_TEXT;
        root->children={{text.Get()},{nullptr,ROLE_SYSTEM_PUSHBUTTON,0},{nullptr,ROLE_SYSTEM_TEXT,STATE_SYSTEM_READONLY}};
        auto result=inspect(root.Get());
        require(result.nodes==4&&result.objects==2&&result.elements==2);
        require(result.textRoles==2&&result.readonlyTextRoles==1&&result.Complete());
        require(result.roles.at(ROLE_SYSTEM_CLIENT)==1&&result.roles.at(ROLE_SYSTEM_PUSHBUTTON)==1);
        // Partial or inconsistent COM results must not look like a negative tree.
        root->shortEnumeration=true;denied(root.Get(),"msaa_children_changed");root->shortEnumeration=false;
        root->enumerationResult=S_FALSE;denied(root.Get(),"msaa_children_changed");root->enumerationResult=S_OK;
        root->countResult=S_FALSE;denied(root.Get(),"msaa_child_count_unavailable");root->countResult=S_OK;
        root->countOverride=-1;denied(root.Get(),"msaa_child_count_unavailable");root->countOverride=LONG_MIN;
        root->roleResult=S_FALSE;denied(root.Get(),"msaa_role_unavailable");root->roleResult=S_OK;
        root->invalidChild=true;denied(root.Get(),"msaa_child_type_unavailable");root->invalidChild=false;
        root->children={{},{}};root->duplicateIds=true;
        denied(root.Get(),"msaa_child_type_unavailable");root->duplicateIds=false;
        root->children.clear();root->roleType=VT_BSTR;result=inspect(root.Get());
        require(result.unknownRoles==1&&result.roles.empty()&&!result.Complete());root->roleType=VT_I4;
        root->role=100000;result=inspect(root.Get());require(result.unknownRoles==1&&result.roles.empty());
        root->role=ROLE_SYSTEM_TEXT;root->stateType=VT_EMPTY;result=inspect(root.Get());
        require(result.textRoles==1&&result.unknownTextStates==1&&!result.Complete());
        root->role=ROLE_SYSTEM_CLIENT;root->stateType=VT_I4;
        // Shared/cyclic object identities cannot cause unbounded recursion.
        root->children={{root.Get()}};result=inspect(root.Get());
        require(result.nodes==2&&result.repeatedObjects==1&&!result.Complete());
        root->children={{text.Get()},{text.Get()}};result=inspect(root.Get());
        require(result.repeatedObjects==1&&!result.Complete());root->children.clear();
        std::vector<ComPtr<Object>> chain;
        for(unsigned i=0;i<18;++i)chain.push_back(Microsoft::WRL::Make<Object>());
        for(unsigned i=0;i<16;++i)chain[i]->children={{chain[i+1].Get()}};
        result=inspect(chain[0].Get());require(result.nodes==17&&result.Complete());
        chain[16]->children={{chain[17].Get()}};result=inspect(chain[0].Get());
        require(result.nodes==17&&result.depthLimited&&!result.Complete());
        root->children.resize(498);result=inspect(root.Get());require(result.nodes==499&&result.Complete());
        root->children.resize(499);result=inspect(root.Get());require(result.nodes==500&&result.nodeLimited&&!result.Complete());
        root->children.resize(600);result=inspect(root.Get());require(result.nodes==500&&result.nodeLimited&&!result.Complete());
        require(forbiddenCalls==0);
        std::cout<<"synthetic MSAA checks: "<<checks<<"; no windows, names, values or actions accessed\n";
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
