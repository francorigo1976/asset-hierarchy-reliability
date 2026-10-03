"""In-browser entry point (Pyodide): routes the UI's /api calls straight to Service, no HTTP server involved."""
from __future__ import annotations

import json
import re
from pathlib import Path

from data_export import AuditTrail
from .service import ApiError, Service
from .jsonstore import JsonStore

DATA = Path("/data")
DB, AUDIT, OUT = DATA / "hierarchy.json", DATA / "audit.jsonl", DATA / "exports"
_svc: Service | None = None


def start(db_text: str = "", audit_text: str = "") -> None:
    global _svc
    DATA.mkdir(parents=True, exist_ok=True)
    if db_text:
        DB.write_text(db_text, encoding="utf-8")
    if audit_text:
        AUDIT.write_text(audit_text, encoding="utf-8")
    _svc = Service(JsonStore(DB), AuditTrail(AUDIT, user="browser"), OUT)


def snapshot():
    """(state JSON, audit text) for the page to keep in localStorage."""
    return _svc.store.dumps(), AUDIT.read_text(encoding="utf-8") if AUDIT.exists() else ""


ROUTES = [  # (method, regex, handler(svc, m, query, body, file))
    ("GET", r"/api/templates", lambda s, m, q, b, f: s.templates()),
    ("GET", r"/api/projects", lambda s, m, q, b, f: s.projects()),
    ("POST", r"/api/projects", lambda s, m, q, b, f: s.new_project(b)),
    ("PUT", r"/api/projects/([^/]+)", lambda s, m, q, b, f: s.update_project(m[0], b)),
    ("GET", r"/api/projects/([^/]+)", lambda s, m, q, b, f: s.tree(m[0])),
    ("POST", r"/api/projects/([^/]+)/nodes", lambda s, m, q, b, f: s.add_node(m[0], b)),
    ("PATCH", r"/api/projects/([^/]+)/nodes/([^/]+)", lambda s, m, q, b, f: s.edit_node(m[0], m[1], b)),
    ("POST", r"/api/projects/([^/]+)/nodes/([^/]+)/move", lambda s, m, q, b, f: s.move_node(m[0], m[1], b.get("parent_id"))),
    ("DELETE", r"/api/projects/([^/]+)/nodes/([^/]+)", lambda s, m, q, b, f: s.delete_node(m[0], m[1])),
    ("GET", r"/api/projects/([^/]+)/preflight/([^/]+)", lambda s, m, q, b, f: s.check(m[0], m[1])),
    ("POST", r"/api/projects/([^/]+)/import", lambda s, m, q, b, f: s.import_template(
        m[0], f[0], f[1], q.get("mode", "merge"), q.get("dry_run") == "true")),
    ("GET", r"/api/audit", lambda s, m, q, b, f: s.audit_log()),
]


def handle(method: str, path: str, query_json: str = "{}", body_json: str = "null", filename: str = "", content=None):
    """Returns (status, payload_json_or_None, file_bytes_or_None, file_name)."""
    q, body = json.loads(query_json or "{}"), json.loads(body_json or "null") or {}
    try:
        em = re.fullmatch(r"/api/projects/([^/]+)/export/([^/]+)", path)
        if method == "GET" and em:
            p = _svc.export(em[1], em[2], q.get("allow_errors") == "true")
            return 200, None, p.read_bytes(), p.name
        for meth, rx, fn in ROUTES:
            m = re.fullmatch(rx, path)
            if meth == method and m:
                data = fn(_svc, m.groups(), q, body, (filename, bytes(content)) if content is not None else None)
                return 200, json.dumps(data), None, ""
        return 404, json.dumps({"detail": "not found"}), None, ""
    except ApiError as e:
        return e.status, json.dumps({"detail": e.detail}), None, ""
    except Exception as e:  # surface unexpected errors to the UI instead of hanging
        return 500, json.dumps({"detail": f"{type(e).__name__}: {e}"}), None, ""
