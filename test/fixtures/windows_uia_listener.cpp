// SPDX-License-Identifier: MIT
// Explicit manual device diagnostic. Never registered with CTest: no text,
// values, focus, input, OS settings, process memory or authority is accessed.
#define NOMINMAX
#include <windows.h>
#include <UIAutomation.h>
#include <oleacc.h>
#include <wrl/client.h>
#include <wrl/implements.h>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <string>
#include <thread>
using Microsoft::WRL::ComPtr;
class Sink final : public Microsoft::WRL::RuntimeClass<
    Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>,IUIAutomationStructureChangedEventHandler> {
    HRESULT STDMETHODCALLTYPE HandleStructureChangedEvent(IUIAutomationElement*,StructureChangeType,SAFEARRAY*) override {
        return S_OK; // Deliberately never inspect the event or sender.
    }
};
struct Counts { unsigned nodes=0,edits=0; };
static void Count(IUIAutomationTreeWalker* walker,IUIAutomationElement* element,unsigned depth,Counts& out){
    if(depth>16||out.nodes>=500)return;
    CONTROLTYPEID role=0;if(FAILED(element->get_CurrentControlType(&role)))throw 1;
    ++out.nodes;if(role==UIA_EditControlTypeId)++out.edits;
    ComPtr<IUIAutomationElement> child;if(FAILED(walker->GetFirstChildElement(element,&child)))throw 1;
    for(unsigned i=0;child&&i<500&&out.nodes<500;++i){
        Count(walker,child.Get(),depth+1,out);
        ComPtr<IUIAutomationElement> next;if(FAILED(walker->GetNextSiblingElement(child.Get(),&next)))throw 1;child=next;
    }
}
int main(int argc,char** argv){
    if(argc!=2&&(argc!=3||std::string(argv[2])!="--legacy-client"))return 2;
    const bool legacy=argc==3;
    HWND window=nullptr;
    try{std::size_t used=0;std::string arg=argv[1];auto value=std::stoull(arg,&used);
        if(used!=arg.size())return 2;window=reinterpret_cast<HWND>(static_cast<std::uintptr_t>(value));}
    catch(...){return 2;}
    if(!IsWindow(window)||!IsWindowVisible(window))return 2;
    HRESULT initialized=CoInitializeEx(nullptr,COINIT_MULTITHREADED);if(FAILED(initialized))return 2;
    int code=2;
    {
        ComPtr<IUIAutomation> automation;ComPtr<IUIAutomationElement> root;ComPtr<IUIAutomationTreeWalker> walker;
        auto sink=Microsoft::WRL::Make<Sink>();bool subscribed=false;
        try{
            if(FAILED(CoCreateInstance(CLSID_CUIAutomation,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&automation)))||
               FAILED(automation->ElementFromHandle(window,&root))||!root||
               FAILED(automation->get_ControlViewWalker(&walker))||!walker)throw 1;
            Counts before;Count(walker.Get(),root.Get(),0,before);
            ComPtr<IAccessible> accessible;LONG legacyChildren=-1;HRESULT legacyStatus=E_NOTIMPL;
            if(legacy){
                legacyStatus=AccessibleObjectFromWindow(window,OBJID_CLIENT,IID_IAccessible,
                    reinterpret_cast<void**>(accessible.GetAddressOf()));
                if(SUCCEEDED(legacyStatus)&&accessible)legacyStatus=accessible->get_accChildCount(&legacyChildren);
            }
            if(FAILED(automation->AddStructureChangedEventHandler(root.Get(),TreeScope_Subtree,nullptr,sink.Get())))throw 1;
            subscribed=true;
            std::this_thread::sleep_for(std::chrono::milliseconds(1500));
            ComPtr<IUIAutomationElement> refreshed;
            if(!IsWindow(window)||FAILED(automation->ElementFromHandle(window,&refreshed))||!refreshed)throw 1;
            Counts after;Count(walker.Get(),refreshed.Get(),0,after);
            if(FAILED(automation->RemoveStructureChangedEventHandler(root.Get(),sink.Get())))throw 1;
            subscribed=false;
            std::cout<<"{\"subscribed\":true,\"unsubscribed\":true,\"legacy_requested\":"<<(legacy?"true":"false")
                     <<",\"legacy_hresult\":"<<static_cast<long>(legacyStatus)<<",\"legacy_children\":"<<legacyChildren
                     <<",\"before_nodes\":"<<before.nodes
                     <<",\"before_edits\":"<<before.edits<<",\"after_nodes\":"<<after.nodes
                     <<",\"after_edits\":"<<after.edits<<",\"content_read\":false,\"input_performed\":false}"<<std::endl;
            code=0;
        }catch(...){std::cout<<"{\"error\":\"uia_listener_probe_failed\",\"content_read\":false,\"input_performed\":false}"<<std::endl;}
        if(subscribed&&automation)automation->RemoveStructureChangedEventHandler(root.Get(),sink.Get());
    }
    CoUninitialize();return code;
}
