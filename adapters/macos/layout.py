# SPDX-License-Identifier: MIT
# Adapted from dustin573/wechat-mcp wechat_accessibility.py (MIT).
# Copyright (c) 2025 Banghao Chi, (c) 2026 Dustin Chan.
# See THIRD_PARTY_NOTICES.md for the original license and pinned commit.
import re
from axr.aet import AXRError

CHAT_TITLE_IDENTIFIER="big_title_line_h_view"
MESSAGE_LIST_IDENTIFIER="chat_message_list"
MESSAGE_BUBBLE_IDENTIFIER="chat_bubble_item_view"


def normalize_chat_title(name):
    # Original upstream group member-count suffix normalization.
    return re.sub(r"\(\d+\)$","",name.strip()).strip()


def selected_paths(nodes):
    """Use upstream identifiers, require uniqueness and refuse layout guesses."""
    titles=[n for n in nodes if n.get("role")=="AXStaticText" and n.get("identifier")==CHAT_TITLE_IDENTIFIER]
    messages=[n for n in nodes if n.get("role")=="AXList" and n.get("identifier")==MESSAGE_LIST_IDENTIFIER]
    if len(titles)!=1 or len(messages)!=1:
        raise AXRError("wechat_accessibility_tree_unavailable_or_ambiguous")
    return titles[0]["path"],messages[0]["path"]
