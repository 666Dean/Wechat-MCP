# SPDX-License-Identifier: MIT
"""Private recipient eligibility shared by setup and live owner scopes."""
SYSTEM_CONVERSATIONS=frozenset(('filehelper','weixin','fmessage','newsapp','medianote','floatbottle',
    'qmessage','qqmail','tmessage','feedsapp','notification_messages','notifymessage',
    'brandsessionholder','mphelper'))

def private_recipient(identity):
    return isinstance(identity,str) and bool(identity) and '@' not in identity and not identity.startswith('gh_') and identity not in SYSTEM_CONVERSATIONS
