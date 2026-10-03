"""SQLite persistence for projects, nodes and deletion tombstones."""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import asdict, fields
from pathlib import Path

from .hierarchy import Hierarchy
from .models import NODE_FIELDS, Node, Project

_SQL_TYPES = {bool: "INTEGER", int: "INTEGER"}


def _node_columns() -> str:
    cols = []
    for f in fields(Node):
        t = "INTEGER" if f.type in ("bool", "int") else "TEXT"
        cols.append(f"{f.name} {t}" + (" PRIMARY KEY" if f.name == "id" else ""))
    return ", ".join(cols)


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path), check_same_thread=False)  # web workers share it; calls are serialised by _lock
        self._lock = threading.RLock()
        self.db.row_factory = sqlite3.Row
        self.db.executescript(f"""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, site TEXT, client TEXT, auditor TEXT, prefix TEXT, next_seq INTEGER,
                sap_planning_plant TEXT, sap_maint_plant TEXT, sap_company_code TEXT, sap_cost_center TEXT,
                sap_structure TEXT, sap_work_center TEXT, sap_planner_group TEXT,
                sap_structure_indicator TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS nodes ({_node_columns()});
            CREATE INDEX IF NOT EXISTS idx_nodes_project ON nodes(project_id);
            CREATE TABLE IF NOT EXISTS deleted_nodes (
                node_id TEXT PRIMARY KEY, project_id TEXT, deleted_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """)

    def _save(self, h: Hierarchy) -> None:
        p = asdict(h.project)
        with self.db:
            self.db.execute(
                f"INSERT OR REPLACE INTO projects ({', '.join(p)}) VALUES ({', '.join('?' * len(p))})", list(p.values()))
            self.db.execute("DELETE FROM nodes WHERE project_id=?", (h.project.id,))
            for n in h.nodes.values():
                row = asdict(n)
                self.db.execute(
                    f"INSERT INTO nodes ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                    [int(v) if isinstance(v, bool) else v for v in row.values()])
            for nid in h.deleted_ids:
                self.db.execute("INSERT OR IGNORE INTO deleted_nodes (node_id, project_id) VALUES (?, ?)",
                                (nid, h.project.id))
            h.deleted_ids.clear()

    def _load(self, project_id: str) -> Hierarchy:
        row = self.db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise KeyError(project_id)
        project = Project(**dict(row))
        tombs = {r[0] for r in self.db.execute("SELECT node_id FROM deleted_nodes WHERE project_id=?", (project_id,))}
        nodes = []
        for r in self.db.execute("SELECT * FROM nodes WHERE project_id=?", (project_id,)):
            d = dict(r)
            if d["id"] in tombs:
                continue   # tombstoned rows never come back
            for name in ("is_area", "is_also_equipment", "isa_differential", "needs_catalog_review",
                         "sap_name_needs_review"):
                d[name] = bool(d[name])
            nodes.append(Node(**{k: d[k] for k in NODE_FIELDS}))
        return Hierarchy(project, nodes)

    def _list_projects(self) -> list[tuple[str, str]]:
        return [(r["id"], r["site"]) for r in self.db.execute("SELECT id, site FROM projects ORDER BY created_at")]

    def save(self, h: Hierarchy) -> None:
        with self._lock:
            self._save(h)

    def load(self, project_id: str) -> Hierarchy:
        with self._lock:
            return self._load(project_id)

    def list_projects(self) -> list[tuple[str, str]]:
        with self._lock:
            return self._list_projects()
