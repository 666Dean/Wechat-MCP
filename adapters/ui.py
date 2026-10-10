# SPDX-License-Identifier: MIT
"""Swift/macOS and native UIA/Windows adapters. No coordinate/OCR send fallback."""
import sys
import time
from axr.aet import AXRError, digest
from axr.host import Supervisor


class UIAdapter:
    def __init__(self, config):
        self.config=config
        self.bindings={b["conversation_id"]:b for b in config["conversations"]}
        self.supervisor=Supervisor(timeout=10)
        self.pid=None

    def _request(self, operation, **args):
        request={"op":operation,**args}
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
        return {**native,"mode":"ui","coverage":"current_visible_authorized_chat",
                "background_read":"client_dependent","send_available":False,
                "identity_assurance":"stable_owner_witness_required"}

    def structure(self):
        return self._request("structure",allow_labels=[b["display_name"] for b in self.bindings.values()])

    def search(self, conversation_id, *, query="",sender=None,since=0,until=2**63-1,after=None,limit=20,guard_context=None):
        binding=self.bindings.get(conversation_id)
        if binding is None:
            raise AXRError("conversation_not_authorized")
        identity=binding.get("identity_witness")
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
                "outgoing":None,"observed_at":time.time(),"identity_assurance":"display_name_only"})
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
        check()
        result=self._request("send_text",expected_pid=structure["pid"],
            expected_title=binding["display_name"],path=layout["input_path"],
            header_path=layout["header_path"],send_path=layout["send_path"],
            messages_path=layout["messages_path"],account_path=identity["account_path"],
            identity_path=identity["conversation_path"],expected_account=action.resource.account_id,
            expected_identity=action.resource.conversation_id,text=action.payload["text"],guard_context=check.commit_proof())
        return {"epoch":epoch,"verified":result.get("verified") is True,
                "evidence_digest":digest(result)}

    def cancel(self):
        self.supervisor.cancel()

    def close(self):
        self.cancel()
