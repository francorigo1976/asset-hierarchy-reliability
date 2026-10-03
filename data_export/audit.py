"""Append-only JSONL audit trail for exports and integrations."""
from __future__ import annotations

import getpass
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class AuditTrail:
    def __init__(self, path: str | Path = "export_audit.jsonl", user: Optional[str] = None):
        self.path = Path(path)
        self.user = user or getpass.getuser()

    def record(self, action: str, **details: Any) -> dict[str, Any]:
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "user": self.user, "action": action, **details}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
        return entry

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    @staticmethod
    def file_sha256(path: str | Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
