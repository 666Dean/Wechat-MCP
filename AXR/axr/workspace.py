# SPDX-License-Identifier: AGPL-3.0-only
"""Narrow workspace text broker with symlink checks and rollback versions."""
import os
import tempfile
from pathlib import Path
from .aet import AXRError, digest


class Workspace:
    def __init__(self, root, vault, backup_root, maximum=1024*1024):
        if Path(root).is_symlink():
            raise AXRError("invalid_workspace_root")
        self.root, self.backup_root = Path(root).resolve(strict=True), Path(backup_root)
        self.vault, self.maximum = vault, maximum
        if self.root.is_symlink() or not self.root.is_dir():
            raise AXRError("invalid_workspace_root")

    def path(self, name):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise AXRError("workspace_path_escape")
        candidate = self.root
        for part in relative.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise AXRError("workspace_symlink_denied")
        if self.root not in candidate.resolve().parents or candidate.suffix.lower() not in {".md", ".txt", ".csv", ".json"}:
            raise AXRError("workspace_type_or_path_denied")
        return candidate

    def write(self, action, check, epoch):
        target = self.path(action.payload["path"])
        data = action.payload["text"].encode("utf-8")
        if len(data) > self.maximum or not target.parent.exists():
            raise AXRError("workspace_size_or_parent_invalid")
        # Cooperative workspace safety. Hostile same-user path races require OS sandbox.
        if target.exists():
            old = target.read_bytes()
            if len(old) > self.maximum:
                raise AXRError("workspace_existing_file_too_large")
            self.backup_root.mkdir(exist_ok=True, parents=True, mode=0o700)
            backup = self.backup_root / (action.seal+".sealed")
            backup.write_bytes(self.vault.seal({"path": str(target), "text": old.decode("utf-8")}, action.seal))
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as f:
                temporary = Path(f.name)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            check()
            if self.path(action.payload["path"]) != target:
                raise AXRError("workspace_target_changed")
            os.replace(temporary, target)
            temporary = None
            verified = target.read_bytes() == data
            return {"epoch": epoch, "verified": verified, "evidence_digest": digest(data.hex())}
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
