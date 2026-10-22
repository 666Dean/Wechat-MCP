// SPDX-License-Identifier: AGPL-3.0-only
#include "axr/Core.hpp"
#include "axr/Security.hpp"
#include "axr/TrustRoot.hpp"
#include "axr/WindowsHello.hpp"
#include "axr/WindowsAttestation.hpp"
#include "axr/WindowsOwnerSetup.hpp"
#include "axr/ProtectedStore.hpp"
#include "axr/Credentials.hpp"
#include <pybind11/functional.h>
#include "axr/Commit.h"
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
namespace py=pybind11;
using namespace Stellaria::AXR;
PYBIND11_MODULE(_axr_native,m) {
    m.attr("protocol_version")=ProtocolVersion;
#ifdef AXR_OWNER_DEPLOYMENT
    m.attr("owner_deployment")=true;
#else
    m.attr("owner_deployment")=false;
#endif
#ifdef AXR_SECURITY_RELEASE
    m.attr("security_release")=true;
#else
    m.attr("security_release")=false;
#endif
    py::class_<CredentialConsumer>(m,"CredentialConsumer")
      .def_property_readonly("identity",&CredentialConsumer::Identity)
      .def_property_readonly("resources",&CredentialConsumer::Resources)
      .def_property_readonly("operations",&CredentialConsumer::Operations)
      .def("use",[](CredentialConsumer& c,const std::string& resource,const std::string& op,const std::string& request,const std::function<void()>& check){return c.Use(ParseBounded(resource),op,ParseBounded(request),check).dump();});
    py::class_<ProtectedStore>(m,"ProtectedStore")
      .def(py::init<std::string>())
      .def("get",[](const ProtectedStore& s,const std::string& name){return py::bytes(s.Get(name));})
      .def("provision",[](const ProtectedStore& s,const std::string& name,py::bytes value){s.Put(name,std::string(value));});
    m.def("digest",&Digest);
    // One representation shared by Python signing/MAC and native consumers.
    m.def("wire_canonical",[](const std::string& value){return ParseBounded(value).dump();});
    m.def("constant_equal",&ConstantEqual);
    m.def("verify_root_signature",[](py::bytes key,py::bytes message,py::bytes signature){return VerifyRootSignature(std::string(key),std::string(message),std::string(signature));});
    m.def("verify_owner_signature",[](py::bytes key,py::bytes message,py::bytes signature){return VerifyOwnerSignature(std::string(key),std::string(message),std::string(signature));});
    m.def("verify_windows_hello_statement",[](py::bytes owner,py::bytes aik,py::bytes statement){return VerifyWindowsHelloStatement(std::string(owner),std::string(aik),std::string(statement));});
    m.def("verify_windows_hello_attestation",[](py::bytes owner,py::bytes statement,py::bytes chain,const std::vector<py::bytes>& roots){
        std::vector<std::string> pins;for(const auto& root:roots)pins.emplace_back(root);
        auto key=std::string(owner),blob=std::string(statement),certificates=std::string(chain);
        py::gil_scoped_release release;return VerifyWindowsHelloAttestation(key,blob,certificates,pins);});
    py::class_<WindowsHelloOwnerKey>(m,"WindowsHelloOwnerKey")
      .def(py::init([](py::bytes key){auto value=std::string(key);py::gil_scoped_release release;return std::make_unique<WindowsHelloOwnerKey>(std::move(value));}),py::arg("expected_public_key"))
      .def_property_readonly("public_key",[](const WindowsHelloOwnerKey& key){return py::bytes(key.PublicKey());})
      .def("attestation",[](const WindowsHelloOwnerKey& key){py::gil_scoped_release release;return key.Attestation().dump();})
      .def("sign",[](const WindowsHelloOwnerKey& key,py::bytes message){auto value=std::string(message);std::string signature;{py::gil_scoped_release release;signature=key.Sign(value);}return py::bytes(signature);});
    m.def("provision_windows_hello_owner",&WindowsHelloOwnerKey::Provision,py::arg("review"),py::arg("expires"),py::call_guard<py::gil_scoped_release>());
    m.def("exchange_windows_owner_setup",[](const std::string& sid,const std::string& challenge){
        auto value=ParseBounded(challenge);py::gil_scoped_release release;return ExchangeWindowsOwnerSetup(sid,value).dump();});
    py::class_<WindowsOwnerSetupClient>(m,"WindowsOwnerSetupClient")
      .def(py::init<>(),py::call_guard<py::gil_scoped_release>())
      .def_property_readonly("challenge",[](const WindowsOwnerSetupClient& client){return client.Challenge().dump();})
      .def("close",&WindowsOwnerSetupClient::Close)
      .def("respond",[](WindowsOwnerSetupClient& client,const std::string& response){auto value=ParseBounded(response);py::gil_scoped_release release;client.Respond(value);});
    py::class_<HardwareSigningKey>(m,"HardwareSigningKey")
      .def(py::init<std::string,bool,bool,bool>(),py::arg("name"),py::arg("create")=false,py::arg("user_presence")=false,py::arg("owner_interaction")=false)
      .def_property_readonly("public_key",[](const HardwareSigningKey& k){return py::bytes(k.PublicKey());})
      .def_property_readonly("provider",&HardwareSigningKey::Provider)
      .def("sign",[](const HardwareSigningKey& k,py::bytes data){return py::bytes(k.Sign(std::string(data)));});
    m.def("process_identity",[](unsigned long pid){return ProcessIdentity(pid).dump();});
    m.def("peer_identity",[](unsigned long long handle,bool serverPeer){return PeerIdentity(handle,serverPeer).dump();},py::arg("handle"),py::arg("server_peer")=false);
    m.def("hmac",[](py::bytes key,const std::string& data){return Hmac(std::string(key),data);});
    m.def("intent_seal",[](const std::string& a){return IntentSeal(ParseBounded(a));});
    m.def("check_commit",[](const std::string& path,const std::string& proof){return axr_check_commit(path.c_str(),proof.c_str())==1;});
    m.def("check_scoped_commit",[](const std::string& path,const std::string& proof,const std::string& scope){return axr_check_scoped_commit(path.c_str(),proof.c_str(),scope.c_str())==1;});
    m.def("verify_commit_permit",[](const std::string& e,py::bytes key,const std::string& root,const std::string& epoch,const std::string& nonce,const std::string& seal,const std::string& helper,double now){return VerifyCommitPermit(ParseBounded(e),std::string(key),root,epoch,nonce,seal,ParseBounded(helper),now);});
    m.def("validate_task_contract",[](const std::string& c){ValidateTaskContract(ParseBounded(c));});
    m.def("security_decision",[](const std::string& c,const std::string& a,const std::string& h,double now){return SecurityDecision(ParseBounded(c),ParseBounded(a),ParseBounded(h),now).dump();});
    m.def("containment_decision",[](const std::string& e,const std::string& d,unsigned count){return ContainmentDecision(e,d,count).dump();});
    m.def("valid_transition",&ValidTransition);
    m.def("encrypt",[](py::bytes key,py::bytes data,const std::string& binding){return py::bytes(Encrypt(std::string(key),std::string(data),binding));});
    m.def("decrypt",[](py::bytes key,py::bytes data,const std::string& binding){return py::bytes(Decrypt(std::string(key),std::string(data),binding));});
    m.def("durable_write",[](const std::string& path,py::bytes data){return DurableWrite(Utf8Path(path),std::string(data));});
    m.def("commit_record",[](const std::string& previous,const std::string& snapshot,const std::string& kind,double at){return CommitRecord(ParseBounded(previous),ParseBounded(snapshot),kind,at).dump();});
    m.def("verify_record",[](const std::string& record,const std::string& previous){return VerifyRecord(ParseBounded(record),ParseBounded(previous));});
    py::class_<Guard>(m,"Guard")
      .def(py::init([](const std::string& path,py::bytes key,bool migrate){return std::make_unique<Guard>(Utf8Path(path),std::string(key),migrate);}),py::arg("path"),py::arg("key"),py::arg("migrate_legacy")=false)
      .def_property_readonly("version",&Guard::Version)
      .def("issue_owner",[](Guard& g,const std::string& b,double now){return g.IssueOwner(ParseBounded(b),now);})
      .def("revoke_owner",&Guard::RevokeOwner)
      .def("revoke_scoped",&Guard::RevokeScoped)
      .def("check",[](const Guard& g,const std::string& a,double now){return g.Check(ParseBounded(a),now);})
      .def("consume",[](Guard& g,const std::string& a,double now){return g.Consume(ParseBounded(a),now).dump();})
      .def("execution_proof",[](const Guard& g,const std::string& a,const std::string& id,unsigned v,double now){return g.ExecutionProof(ParseBounded(a),id,v,now).dump();})
      .def("revalidate",[](const Guard& g,const std::string& a,const std::string& id,unsigned v,double now){g.Revalidate(ParseBounded(a),id,v,now);});
    py::enum_<WorkerProcessState>(m,"WorkerProcessState")
      .value("Stopped",WorkerProcessState::Stopped).value("Starting",WorkerProcessState::Starting)
      .value("Running",WorkerProcessState::Running).value("Canceling",WorkerProcessState::Canceling)
      .value("Exited",WorkerProcessState::Exited).value("Crashed",WorkerProcessState::Crashed).value("TimedOut",WorkerProcessState::TimedOut);
    py::class_<WorkerSupervisor>(m,"WorkerSupervisor").def(py::init<>())
      .def("start",[](WorkerSupervisor& w,const std::string& exe,const std::vector<std::string>& args,unsigned timeout){return w.Start(Utf8Path(exe),args,timeout);})
      .def("poll",&WorkerSupervisor::Poll).def("stop",&WorkerSupervisor::Stop).def_property_readonly("exit_code",&WorkerSupervisor::ExitCode);
}
