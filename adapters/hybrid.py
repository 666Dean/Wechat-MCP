# SPDX-License-Identifier: MIT
"""Explicit WCDB reading plus independently qualified UI commits."""


class HybridAdapter:
    def __init__(self, database, ui):
        self.database, self.ui = database, ui

    def status(self):
        return {'mode': 'hybrid', 'read': self.database.status(), 'ui': self.ui.status(),
                'send_available': False, 'identity_assurance': 'stable_owner_witness_required'}

    def search(self, conversation_id, **options):
        return self.database.search(conversation_id, **options)

    def send(self, action, check, epoch):
        return self.ui.send(action, check, epoch)

    def cancel(self):
        try:
            self.ui.cancel()
        finally:
            self.database.cancel()

    def close(self):
        try:
            self.ui.close()
        finally:
            self.database.close()
