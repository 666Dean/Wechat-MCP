# SPDX-License-Identifier: MIT
"""Scoped AX/UIA input and optional local OCR preview; no blind send fallback."""
import sys
import time
from axr.aet import AXRError, digest
from axr.host import Supervisor


class UIAdapter:
    def __init__(self, config):
        self.config=config
        self.bindings={b["conversation_id"]:b for b in config["conversations"]}
        self.supervisor=Supervisor(timeout=35 if any(b.get("read_method")=="ocr" for b in self.bindings.values()) else 10)
        self.pid=None

    def _request(self, operation, **args):
        request={"op":operation,"expected_platform":"wechat",**args}
        if sys.platform=="darwin":
            request["bundle"]="com.tencent.xinWeChat"
        else:
            request["executable_hash"]=self.config.get("executable_hash","")
        result=self.supervisor.invoke([self.config["native_helper"]],request)["result"]
        if "error" in result:
            raise AXRError(result["error"])
        return result

    def status(self):
        native=self._request("status")
        if sys.platform=="darwin" and native.get("running") and native.get("accessibility"):
            # Bind both probes to one process epoch. Counts do not qualify a send.
            capability=self._request("capabilities",expected_pid=native["pid"])
            native["capabilities"]=capability
            native["ui_structure_state"]=("inspection_incomplete" if capability["truncated"] else
                "no_editable_controls" if capability["editable_nodes"]==0 else "candidate_controls_unqualified")
            if capability["editable_nodes"]==0:
                visual=self._request("visual_capabilities",expected_pid=native["pid"])
                native["visual_capabilities"]=visual
                # Old helpers' field names remain readable, but these legacy
                # flags cannot prove modern screen protection or capture success.
                candidates=visual.get("capture_policy_candidates",visual.get("capture_candidates",0))
                legacy=visual.get("legacy_nonsharing_windows",visual.get("protected_windows",0))
                native["ocr_state"]=("permission_required" if not visual["screen_capture_permission"] else
                    "capture_policy_unqualified" if candidates==0 else
                    "legacy_window_sharing_unqualified" if legacy>0 else "visible_identity_qualification_required")
        return {**native,"mode":"ui","coverage":"current_visible_authorized_chat",
                "background_read":"client_dependent","send_available":False,
                "identity_assurance":"stable_owner_witness_required"}

    def structure(self):
        return self._request("structure")

    def search(self, conversation_id, *, query="",sender=None,since=0,until=2**63-1,after=None,limit=20,guard_context=None):
        binding=self.bindings.get(conversation_id)
        if binding is None:
            raise AXRError("conversation_not_authorized")
        identity=binding.get("identity_witness")
        method=binding.get("read_method","ax")
        if method not in {"ax","ocr"}:raise AXRError("read_method_unqualified")
        if method=="ocr":
            if sys.platform!="darwin":raise AXRError("local_ocr_platform_unavailable")
            if not guard_context:raise AXRError("broker_commit_proof_required")
            if sender is not None or since or until<2**63-1 or after is not None:
                raise AXRError("ocr_sender_time_or_cursor_unavailable")
            result=self._request("read_ocr",expected_pid=binding["visual_binding"]["pid"],
                visual_binding=binding["visual_binding"],expected_title=binding["display_name"],
                expected_account=self.config["account_id"],expected_identity=conversation_id,guard_context=guard_context)
            lines=result["lines"]
            messages=[{"reference":digest([conversation_id,result["pid"],i,line["text"]]),"text":line["text"],
                "confidence":line["confidence"],"created":None,"sender":None,"outgoing":None,"observed_at":time.time(),
                "identity_assurance":result["identity_assurance"],"ocr":True}
                for i,line in enumerate(lines) if line["text"] and query in line["text"]]
            return {"messages":messages[:limit],"cursor":None,"has_more":len(messages)>limit,
                "coverage":"owner_bound_visible_ocr_regions","complete_history":False,"background":not result.get("foreground",True),"preview_only":True}
        if not identity or identity.get("platform_verified") is not True:
            raise AXRError("stable_account_and_conversation_witness_required_for_read")
        if not guard_context:raise AXRError("broker_commit_proof_required")
        structure=self.structure()
        if sys.platform=="darwin":
            from .macos.layout import selected_paths
            header,message_path=selected_paths(structure["nodes"])
        else:
            layout=binding.get("layout")
            if not layout:
                raise AXRError("windows_layout_not_owner_verified")
            header,message_path=layout["header_path"],layout["messages_path"]
        result=self._request("read",path=message_path,header_path=header,
            expected_title=binding["display_name"],expected_pid=structure["pid"],
            account_path=identity["account_path"],identity_path=identity["conversation_path"],
            expected_account=self.config["account_id"],expected_identity=conversation_id,guard_context=guard_context)
        messages=[]
        for node in result["nodes"]:
            identifier=node.get("identifier","")
            if sys.platform=="darwin" and identifier!="chat_bubble_item_view":
                continue
            if sys.platform!="darwin" and node.get("role")!="Text":
                continue
            text=node.get("value","")
            if not text or query not in text:
                continue
            # UI has no qualified sender/time/global ID witness. Never invent those.
            ref=digest([conversation_id,result["pid"],node["path"],text])
            if sender is not None or since or until<2**63-1:
                raise AXRError("ui_sender_or_time_filter_unavailable")
            messages.append({"reference":ref,"text":text,"created":None,"sender":None,
                "outgoing":None,"observed_at":time.time(),"text_truncated":bool(node.get("truncated")),
                "identity_assurance":"owner_verified_platform_witness"})
        return {"messages":messages[:limit],"cursor":None,"has_more":len(messages)>limit,
                "coverage":"current_visible_chat","complete_history":False,
                "background":not result.get("foreground",True),"preview_only":True}

    def send(self, action, check, epoch):
        binding=self.bindings[action.resource.conversation_id]
        identity=binding.get("identity_witness")
        if not identity or not identity.get("platform_verified",False):
            raise AXRError("stable_target_identity_not_qualified_preview_only")
        structure=self.structure()
        layout=binding["layout"]
        method=layout.get("send_method","ax_press")
        if method not in {"ax_press","pid_return"} or (sys.platform!="darwin" and method!="ax_press"):
            raise AXRError("send_method_unqualified")
        if method=="pid_return" and layout.get("return_sends_message") is not True:
            raise AXRError("return_send_semantics_unqualified")
        check()
        result=self._request("send_text",expected_pid=structure["pid"],
            expected_title=binding["display_name"],path=layout["input_path"],
            header_path=layout["header_path"],send_path=layout.get("send_path"),send_method=method,
            return_sends_message=layout.get("return_sends_message",False),
            messages_path=layout["messages_path"],account_path=identity["account_path"],
            identity_path=identity["conversation_path"],expected_account=action.resource.account_id,
            expected_identity=action.resource.conversation_id,text=action.payload["text"],guard_context=check.commit_proof())
        return {"epoch":epoch,"verified":result.get("verified") is True,
                "evidence_digest":digest(result)}

    def cancel(self):
        self.supervisor.cancel()

    def close(self):
        self.cancel()
