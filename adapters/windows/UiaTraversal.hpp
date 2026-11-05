// SPDX-License-Identifier: MIT
#pragma once
#include <set>
#include <stdexcept>
#include <vector>

namespace WeChat {
// Provider-independent traversal logic; tests use only synthetic identities.
// Failures propagate. Never turn an unreadable/cyclic branch into an empty tree.
template<class Node,class Key,class Parent>
bool UiaWithin(Node root,Node child,Key key,Parent parent){
    const auto bound=key(root);
    using Identity=decltype(key(root));std::set<Identity> visited;
    for(unsigned depth=0;child&&depth<64;++depth){
        auto identity=key(child);
        if(identity==bound)return true;
        if(!visited.insert(identity).second)throw std::runtime_error("uia_parent_cycle");
        child=parent(child);
    }
    if(child)throw std::runtime_error("uia_parent_budget_exceeded");
    return false;
}

template<class Node,class Key,class Parent,class First,class Next>
std::vector<Node> UiaChildren(Node root,Key key,Parent parent,First first,Next next){
    std::vector<Node> result;
    using Identity=decltype(key(root));std::set<Identity> seen;
    const auto bound=key(root);
    for(Node child=first(root);child;child=next(child)){
        if(result.size()>=500)throw std::runtime_error("uia_children_budget_exceeded");
        auto identity=key(child);
        if(identity==bound||!seen.insert(identity).second)throw std::runtime_error("uia_sibling_cycle");
        if(!UiaWithin(root,child,key,parent))throw std::runtime_error("uia_tree_boundary_changed");
        result.push_back(child);
    }
    return result;
}
}
