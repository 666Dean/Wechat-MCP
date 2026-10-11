# SPDX-License-Identifier: MIT
"""Validate application controls before opening adapters or listener threads."""
from axr.aet import AXRError


def validate_controls(config):
    if not isinstance(config,dict):raise AXRError('invalid_wechat_policy')
    for section,names in (('listener',('listen','wake_agent','auto_execute')),('runner',('enabled',))):
        controls=config.get(section,{})
        if not isinstance(controls,dict):raise AXRError('invalid_wechat_controls')
        for name in names:
            if name in controls and type(controls[name]) is not bool:
                # A signed JSON string "false" must never become a truthy opt-in.
                raise AXRError('wechat_control_requires_boolean')
    return config
