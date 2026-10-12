# SPDX-License-Identifier: MIT
"""Validate application controls before opening adapters or listener threads."""
from axr.aet import AXRError
import math


def validate_controls(config):
    if not isinstance(config,dict):raise AXRError('invalid_wechat_policy')
    if 'account_review' in config:
        review=config['account_review']
        if not isinstance(review,dict) or type(review.get('enabled')) is not bool:
            raise AXRError('account_review_control_requires_boolean')
        if review.get('enabled'):
            if (config.get('mode')!='wcdb' or type(review.get('max_pages')) is not int or
                    not 1<=review['max_pages']<=8192 or type(review.get('snapshot_until')) is not int or
                    review['snapshot_until']<0 or type(review.get('deadline')) not in (int,float) or
                    not math.isfinite(review['deadline']) or review['deadline']<=0):
                raise AXRError('account_review_budget_invalid')
    for section,names in (('listener',('listen','wake_agent','auto_execute','start_from_now','all_incoming')),('runner',('enabled',))):
        controls=config.get(section,{})
        if not isinstance(controls,dict):raise AXRError('invalid_wechat_controls')
        for name in names:
            if name in controls and type(controls[name]) is not bool:
                # A signed JSON string "false" must never become a truthy opt-in.
                raise AXRError('wechat_control_requires_boolean')
    if "navigation" in config:
        from adapters.macos.navigation import validate_navigation, APPLICATION_SCOPE
        validate_navigation(config["navigation"])
        if any(b.get("conversation_id") == APPLICATION_SCOPE for b in config.get("conversations", [])):
            raise AXRError('reserved_application_navigation_scope')
    return config
