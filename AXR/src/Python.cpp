// SPDX-License-Identifier: AGPL-3.0-only
#include "axr/Core.hpp"
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
namespace py=pybind11;
using namespace Stellaria::AXR;
PYBIND11_MODULE(_axr_native,m) {
    m.attr("protocol_version")=ProtocolVersion;
    m.def("digest",&Digest);
    m.def("hmac",[](py::bytes key,const std::string& data){return Hmac(std::string(key),data);});
    m.def("intent_seal",[](const std::string& a){return IntentSeal(Json::parse(a));});
    m.def("valid_transition",&ValidTransition);
    m.def("encrypt",[](py::bytes key,py::bytes data,const std::string& binding){return py::bytes(Encrypt(std::string(key),std::string(data),binding));});
    m.def("decrypt",[](py::bytes key,py::bytes data,const std::string& binding){return py::bytes(Decrypt(std::string(key),std::string(data),binding));});
    m.def("durable_write",[](const std::string& path,py::bytes data){return DurableWrite(std::filesystem::u8path(path),std::string(data));});
    m.def("commit_record",[](const std::string& previous,const std::string& snapshot,const std::string& kind,double at){return CommitRecord(Json::parse(previous),Json::parse(snapshot),kind,at).dump();});
    m.def("verify_record",[](const std::string& record,const std::string& previous){return VerifyRecord(Json::parse(record),Json::parse(previous));});
    py::class_<Guard>(m,"Guard")
      .def(py::init([](const std::string& path,py::bytes key){return std::make_unique<Guard>(std::filesystem::u8path(path),std::string(key));}))
      .def_property_readonly("version",&Guard::Version)
      .def("issue_owner",[](Guard& g,const std::string& b,double now){return g.IssueOwner(Json::parse(b),now);})
      .def("revoke_owner",&Guard::RevokeOwner)
      .def("check",[](const Guard& g,const std::string& a,double now){return g.Check(Json::parse(a),now);})
      .def("consume",[](Guard& g,const std::string& a,double now){return g.Consume(Json::parse(a),now).dump();})
      .def("revalidate",[](const Guard& g,const std::string& a,const std::string& id,unsigned v,double now){g.Revalidate(Json::parse(a),id,v,now);});
    py::enum_<WorkerProcessState>(m,"WorkerProcessState")
      .value("Stopped",WorkerProcessState::Stopped).value("Starting",WorkerProcessState::Starting)
      .value("Running",WorkerProcessState::Running).value("Canceling",WorkerProcessState::Canceling)
      .value("Exited",WorkerProcessState::Exited).value("Crashed",WorkerProcessState::Crashed).value("TimedOut",WorkerProcessState::TimedOut);
    py::class_<WorkerSupervisor>(m,"WorkerSupervisor").def(py::init<>())
      .def("start",[](WorkerSupervisor& w,const std::string& exe,const std::vector<std::string>& args,unsigned timeout){return w.Start(std::filesystem::u8path(exe),args,timeout);})
      .def("poll",&WorkerSupervisor::Poll).def("stop",&WorkerSupervisor::Stop).def_property_readonly("exit_code",&WorkerSupervisor::ExitCode);
}
