# SPDX-License-Identifier: MIT
"""WeChat menu catalog. No chat contents, screen capture or arbitrary commands."""
import sys
from pathlib import Path
from axr.aet import AXRError, digest
from axr.host import Supervisor

APPLICATION_SCOPE = "axr:application-ui"
CATALOG = {
    "open_chat_selector": {"menu_path": ["文件", "发起会话"],
                           "window_title": "微信发起群聊", "window_subrole": "AXDialog"},
    "open_preferences": {"menu_path": ["微信", "设置"],
                         "window_title": "设置", "window_subrole": "AXStandardWindow"},
}


def validate_navigation(config):
    if not isinstance(config, dict) or set(config) != {"native_helper", "actions"}:
        raise AXRError("invalid_navigation_policy")
    actions = config["actions"]
    if not isinstance(actions, list) or not actions or any(not isinstance(a, str) or a not in CATALOG for a in actions) or len(set(actions)) != len(actions):
        raise AXRError("navigation_action_not_allowlisted")
    helper = config["native_helper"]
    if not isinstance(helper, str) or not Path(helper).is_absolute():
        raise AXRError("absolute_navigation_helper_required")
    return config


class NavigationAdapter:
    def __init__(self, config):
        self.config = validate_navigation(config)
        self.supervisor = Supervisor(timeout=12)

    def _request(self, operation, **args):
        if sys.platform != "darwin":
            raise AXRError("mac_navigation_platform_unavailable")
        result = self.supervisor.invoke([self.config["native_helper"]],
            {"op": operation, "bundle": "com.tencent.xinWeChat", **args})["result"]
        if "error" in result:
            raise AXRError(result["error"])
        return result

    def binding(self, command):
        if not isinstance(command, str) or command not in self.config["actions"] or command not in CATALOG:
            raise AXRError("navigation_action_not_allowlisted")
        status = self._request("status")
        if status.get("running") is not True or status.get("accessibility") is not True or type(status.get("pid")) is not int or status["pid"] <= 0:
            raise AXRError("navigation_application_unavailable")
        # PID is sealed at proposal time. Restart requires a new owner approval.
        return {"bundle": "com.tencent.xinWeChat", "pid": status["pid"], **CATALOG[command]}

    def execute(self, action, check, epoch):
        command = action.payload["command"]
        if command not in self.config["actions"] or command not in CATALOG or action.resource.conversation_id != APPLICATION_SCOPE:
            raise AXRError("navigation_scope_or_command_changed")
        binding = action.payload["navigation_binding"]
        expected = {"bundle": "com.tencent.xinWeChat", "pid": binding.get("pid"), **CATALOG[command]}
        if binding != expected or type(binding.get("pid")) is not int or binding["pid"] <= 0:
            raise AXRError("navigation_binding_changed")
        check()
        result = self._request("menu_navigate", expected_platform=action.resource.platform,
            expected_account=action.resource.account_id, expected_identity=APPLICATION_SCOPE,
            expected_pid=binding["pid"], navigation_binding=binding, guard_context=check.commit_proof())
        check()
        verified = result.get("pid") == binding["pid"] and result.get("window_verified") is True and result.get("content_read") is False and result.get("message_sent") is False and result.get("method") == "ax_menu"
        return {"epoch": epoch, "verified": verified, "evidence_digest": digest(result),
            "output": {"command": command, "window_verified": verified, "content_read": False,
                       "message_sent": False, "background": result.get("foreground") is False}}

    def cancel(self):
        self.supervisor.cancel()
