// SPDX-License-Identifier: MIT
// Synthetic providers and SAFEARRAYs only. Never discovers real windows.
#include "../../adapters/windows/UiaTree.hpp"
#include <iostream>
#include <map>
#include <string>
#include <atomic>
#include <chrono>
#include <thread>

// Explicit local integration check, never selected by CTest. Own blank window
// only; the owner thread pumps messages while the MTA queries metadata.
static int OwnedWindow(){
    HWND window=CreateWindowExW(WS_EX_NOACTIVATE,L"STATIC",L"",WS_POPUP|WS_VISIBLE,
        0,0,120,60,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
    if(!window)return 2;
    if(!CreateWindowExW(0,L"EDIT",L"",WS_CHILD|WS_VISIBLE,0,0,80,30,window,nullptr,GetModuleHandleW(nullptr),nullptr)){
        DestroyWindow(window);return 2;
    }
    std::atomic<bool> done=false;bool verified=false;
    std::thread worker([&]{
        const auto initialized=CoInitializeEx(nullptr,COINIT_MULTITHREADED);
        if(SUCCEEDED(initialized)){
            try{
                Microsoft::WRL::ComPtr<IUIAutomation> automation;
                Microsoft::WRL::ComPtr<IUIAutomationElement> root;
                Microsoft::WRL::ComPtr<IUIAutomationTreeWalker> walker;
                if(FAILED(CoCreateInstance(CLSID_CUIAutomation,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&automation)))||
                    FAILED(automation->ElementFromHandle(window,&root))||!root||
                    FAILED(automation->get_ControlViewWalker(&walker))||!walker)throw std::runtime_error("fixture_uia_unavailable");
                WeChat::UiaTree tree(automation.Get(),walker.Get());const auto children=tree.Children(root);
                CONTROLTYPEID role=0;
                verified=children.size()==1&&SUCCEEDED(children[0]->get_CurrentControlType(&role))&&role==UIA_EditControlTypeId;
            }catch(...){verified=false;}
            CoUninitialize();
        }
        done=true;
    });
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(12);
    while(!done){
        if(std::chrono::steady_clock::now()>=deadline)ExitProcess(2);
        MSG message;while(PeekMessageW(&message,nullptr,0,0,PM_REMOVE)){TranslateMessage(&message);DispatchMessageW(&message);}
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    worker.join();DestroyWindow(window);
    std::cout<<"{\"owned_blank_window_verified\":"<<(verified?"true":"false")
             <<",\"real_wechat_accessed\":false,\"content_read\":false,\"input_performed\":false}\n";
    return verified?0:2;
}

struct Node {int value=0;explicit operator bool() const{return value!=0;}};
struct Provider {
    std::map<int,int> parents,first,next,identities;
    std::string failure;
    unsigned reads=0;
    auto Key(Node node){
        ++reads;if(failure=="key")throw std::runtime_error("uia_runtime_identity_unavailable");
        return std::vector<LONG>{42,identities.contains(node.value)?identities.at(node.value):node.value};
    }
    Node Parent(Node node){++reads;if(failure=="parent")throw std::runtime_error("uia_parent_unavailable");return {parents[node.value]};}
    auto Children(){return WeChat::UiaChildren(Node{1},[&](Node n){return Key(n);},[&](Node n){return Parent(n);},
        [&](Node n){++reads;if(failure=="first")throw std::runtime_error("uia_children_unavailable");return Node{first[n.value]};},
        [&](Node n){++reads;if(failure=="next")throw std::runtime_error("uia_children_unavailable");return Node{next[n.value]};});}
};

int main(int argc,char** argv){
    if(argc==2&&std::string(argv[1])=="--owned-window")return OwnedWindow();
    if(argc!=1)return 2;
    unsigned checks=0;
    auto require=[&](bool value){++checks;if(!value)throw std::runtime_error("uia_traversal_test_failed");};
    auto denied=[&](auto action,const std::string& expected){
        try{action();}catch(const std::runtime_error& e){require(e.what()==expected);return;}
        throw std::runtime_error("uia_traversal_should_reject");
    };
    auto array=[&](SAFEARRAY* value,bool valid){
        try{
            if(valid){const auto id=WeChat::UiaRuntimeId(value);require(!id.empty());}
            else denied([&]{WeChat::UiaRuntimeId(value);},"uia_runtime_identity_unavailable");
        }catch(...){if(value)SafeArrayDestroy(value);throw;}
        if(value)require(SUCCEEDED(SafeArrayDestroy(value)));
    };
    try{
        Provider p;p.first[1]=2;p.parents={{2,1},{3,1}};p.next[2]=3;
        auto children=p.Children();require(children.size()==2&&children[0].value==2&&children[1].value==3);
        p.parents={{2,4},{4,1},{3,1}};children=p.Children();require(children.size()==2); // Filtered raw ancestor.
        p.parents[3]=9;denied([&]{p.Children();},"uia_tree_boundary_changed");
        p.first[1]=3;denied([&]{p.Children();},"uia_tree_boundary_changed");
        p.first[1]=1;denied([&]{p.Children();},"uia_sibling_cycle");
        p.first[1]=2;p.parents={{2,1},{3,1},{4,1}};p.next={{2,3},{3,4}};p.identities[4]=2;
        denied([&]{p.Children();},"uia_sibling_cycle"); // Distinct wrappers, same runtime identity.
        p.identities.clear();p.next={{2,2}};denied([&]{p.Children();},"uia_sibling_cycle");
        p.next.clear();p.parents={{2,3},{3,2}};denied([&]{p.Children();},"uia_parent_cycle");
        p.parents={{2,3},{3,4}};p.identities[4]=2;denied([&]{p.Children();},"uia_parent_cycle");
        p.identities.clear();p.parents={{2,1}};
        for(const auto& failure:{"key","parent","first","next"}){
            p.failure=failure;const std::string expected=failure==std::string("key")?"uia_runtime_identity_unavailable":
                failure==std::string("parent")?"uia_parent_unavailable":"uia_children_unavailable";
            denied([&]{p.Children();},expected);
        }
        p.failure.clear();p.first[1]=0;require(p.Children().empty());
        p.parents.clear();for(int id=2;id<=65;++id)p.parents[id]=id-1;
        auto key=[&](Node n){return p.Key(n);};auto parent=[&](Node n){return p.Parent(n);};
        require(WeChat::UiaWithin(Node{1},Node{64},key,parent));
        denied([&]{WeChat::UiaWithin(Node{1},Node{65},key,parent);},"uia_parent_budget_exceeded");
        require(!WeChat::UiaWithin(Node{99},Node{1},key,parent));
        p.first[1]=2;p.parents.clear();p.next.clear();
        for(int id=2;id<=501;++id){p.parents[id]=1;if(id<501)p.next[id]=id+1;}
        require(p.Children().size()==500);
        p.next[501]=502;p.parents[502]=1;denied([&]{p.Children();},"uia_children_budget_exceeded");
        array(nullptr,false);array(SafeArrayCreateVector(VT_I4,0,0),false);
        array(SafeArrayCreateVector(VT_I4,0,65),false);array(SafeArrayCreateVector(VT_UI4,0,2),false);
        SAFEARRAYBOUND bounds[2]={{2,0},{2,0}};array(SafeArrayCreate(VT_I4,2,bounds),false);
        array(SafeArrayCreateVector(VT_I4,5,2),true);
        auto id=SafeArrayCreateVector(VT_I4,0,3);LONG expected[]={42,-7,1234};
        for(LONG index=0;index<3;++index)require(SUCCEEDED(SafeArrayPutElement(id,&index,&expected[index])));
        require(WeChat::UiaRuntimeId(id)==std::vector<LONG>({42,-7,1234}));array(id,true);
        std::cout<<"synthetic UIA traversal checks: "<<checks<<"; no real windows or content accessed\n";
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
