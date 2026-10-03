"""Dependency-free store with the same interface as Store; state is one JSON document (used in the browser build)."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .hierarchy import Hierarchy
from .models import NODE_FIELDS, Node, Project


class JsonStore:
    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path else None
        self.data = {"projects": {}, "nodes": {}, "deleted": {}}
        if self.path and self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def dumps(self) -> str:
        return json.dumps(self.data)

    def save(self, h: Hierarchy) -> None:
        pid = h.project.id
        self.data["projects"][pid] = asdict(h.project)
        self.data["nodes"][pid] = [asdict(n) for n in h.nodes.values()]
        self.data["deleted"].setdefault(pid, [])
        self.data["deleted"][pid] = sorted(set(self.data["deleted"][pid]) | h.deleted_ids)
        h.deleted_ids.clear()
        if self.path:
            self.path.write_text(self.dumps(), encoding="utf-8")

    def load(self, project_id: str) -> Hierarchy:
        p = self.data["projects"][project_id]          # KeyError -> "project not found"
        tombs = set(self.data["deleted"].get(project_id, []))
        nodes = [Node(**{k: d[k] for k in NODE_FIELDS if k in d}) for d in self.data["nodes"].get(project_id, [])
                 if d["id"] not in tombs]
        return Hierarchy(Project(**p), nodes)

    def list_projects(self) -> list[tuple[str, str]]:
        return [(i, p["site"]) for i, p in sorted(self.data["projects"].items(), key=lambda kv: kv[1]["created_at"])]
