# SPDX-License-Identifier: MIT
"""Encrypted, bounded reply tasks. An inbox entry grants no disclosure or send."""
import uuid
from axr.aet import AXRError


class Inbox:
    def __init__(self, journal, guard, principal):
        self.journal, self.guard, self.principal = journal, guard, principal
        journal.db.execute('''CREATE TABLE IF NOT EXISTS reply_tasks(
            id TEXT PRIMARY KEY, principal TEXT, resource TEXT, version INTEGER,
            expires REAL, payload BLOB)''')

    def purge(self):
        self.journal.db.execute('DELETE FROM reply_tasks WHERE principal=? AND (expires<=? OR version!=?)',
                                (self.principal, self.journal.clock(), self.guard.version))

    def create(self, resource, context_id, job_id,origin='incoming_reply'):
        self.purge()
        count = self.journal.db.execute('SELECT count(*) FROM reply_tasks WHERE principal=?',
                                       (self.principal,)).fetchone()[0]
        if count >= 50:
            raise AXRError('reply_inbox_capacity_exhausted')
        task_id = str(uuid.uuid4())
        data = dict(id=task_id, principal=self.principal, resource=resource.key,
                    version=self.guard.version, expires=self.journal.clock()+300,
                    conversation_id=resource.conversation_id, context_id=context_id,
                    disclosure_job=job_id, draft_job=None,origin=origin)
        self.journal.db.execute('INSERT INTO reply_tasks VALUES(?,?,?,?,?,?)',
            (task_id, self.principal, resource.key, data['version'], data['expires'],
             self.journal.vault.seal(data, task_id+':reply-task')))
        return task_id

    def get(self, task_id):
        self.purge()
        row = self.journal.db.execute('SELECT * FROM reply_tasks WHERE id=? AND principal=?',
                                     (task_id, self.principal)).fetchone()
        if row is None:
            raise AXRError('reply_task_missing_expired_or_revoked')
        data = self.journal.vault.open(row['payload'], task_id+':reply-task')
        if any(data[k] != row[k] for k in ('id','principal','resource','version','expires')):
            raise AXRError('reply_task_binding_mismatch')
        return data

    def list(self):
        self.purge()
        rows = self.journal.db.execute('SELECT id FROM reply_tasks WHERE principal=? ORDER BY expires LIMIT 50',
                                       (self.principal,)).fetchall()
        return [self.get(row['id']) for row in rows]

    def finish(self, task_id, draft_job):
        data = self.get(task_id)
        if data['draft_job'] is not None and data['draft_job'] != draft_job:
            raise AXRError('reply_task_already_has_draft')
        data['draft_job'] = draft_job
        self.journal.db.execute('UPDATE reply_tasks SET payload=? WHERE id=? AND principal=?',
            (self.journal.vault.seal(data, task_id+':reply-task'), task_id, self.principal))
