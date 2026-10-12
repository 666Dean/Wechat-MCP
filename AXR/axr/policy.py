# SPDX-License-Identifier: AGPL-3.0-only
"""Owner-sealed local configuration; agent input never becomes policy."""
import json
import hmac
import os
from pathlib import Path
from .aet import AXRError,canonical,digest
from .storage import SecretStore,private_directory,Vault
from .guard import Guard
from .journal import Journal
from . import _axr_native as native

class OwnerStore:
    def __init__(self,directory,*,provision=False):
        self.directory=private_directory(directory)
        self.secrets=SecretStore("Stellaria.AXR."+digest(str(self.directory)))
        if provision:
            for name in ("authority","journal"):
                try:self.secrets.get(name)
                except AXRError:self.secrets.provision(name,os.urandom(32))
        self.key=self.secrets.get("authority")
        self.vault=Vault(self.secrets.get("journal"))
        self.guard=Guard(self.directory/"guard.sqlite3",self.key)
        self.journal=Journal(self.directory/"journal.sqlite3",self.vault)

    def seal_config(self,value):
        encoded=canonical({"version":1,"policy":value})
        document=canonical({"body":json.loads(encoded),"mac":hmac.new(self.key,encoded,"sha256").hexdigest()})
        if not native.durable_write(str(self.directory/"policy.sealed.json"),document):
            raise AXRError("policy_durable_write_failed")

    def config(self):
        try:
            path=self.directory/"policy.sealed.json"
            if path.is_symlink() or path.stat().st_size>512*1024:raise ValueError()
            document=json.loads(path.read_bytes());body=document["body"]
            if body["version"]!=1 or not hmac.compare_digest(document["mac"],hmac.new(self.key,canonical(body),"sha256").hexdigest()):raise ValueError()
            return body["policy"]
        except Exception as exc:raise AXRError("owner_policy_missing_or_tampered") from exc

    def close(self):
        self.journal.close();self.guard.close()
