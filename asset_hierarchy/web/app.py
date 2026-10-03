"""Web UI + JSON API for the asset hierarchy. Run: uvicorn asset_hierarchy.web.app:app"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from data_export import AuditTrail
from ..service import ApiError, Service
from ..store import Store

STATIC = Path(__file__).parent / "index.html"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def create_app(db_path: str = "hierarchy.sqlite", audit_path: str = "export_audit.jsonl",
               export_dir: Optional[str] = None) -> FastAPI:
    app = FastAPI(title="Asset Hierarchy")
    svc = Service(Store(db_path), AuditTrail(audit_path), Path(export_dir or tempfile.mkdtemp(prefix="exports_")))

    def call(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except ApiError as e:
            raise HTTPException(e.status, e.detail)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return STATIC.read_text(encoding="utf-8")

    @app.get("/api/templates")
    def templates():
        return svc.templates()

    @app.get("/api/projects")
    def projects():
        return svc.projects()

    @app.post("/api/projects")
    def new_project(p: dict):
        return call(svc.new_project, p)

    @app.put("/api/projects/{pid}")
    def update_project(pid: str, p: dict):
        return call(svc.update_project, pid, p)

    @app.get("/api/projects/{pid}")
    def tree(pid: str):
        return call(svc.tree, pid)

    @app.post("/api/projects/{pid}/nodes")
    def add_node(pid: str, n: dict):
        return call(svc.add_node, pid, n)

    @app.patch("/api/projects/{pid}/nodes/{nid}")
    def edit_node(pid: str, nid: str, fields: dict):
        return call(svc.edit_node, pid, nid, fields)

    @app.post("/api/projects/{pid}/nodes/{nid}/move")
    def move_node(pid: str, nid: str, m: dict):
        return call(svc.move_node, pid, nid, m.get("parent_id"))

    @app.delete("/api/projects/{pid}/nodes/{nid}")
    def delete_node(pid: str, nid: str):
        return call(svc.delete_node, pid, nid)

    @app.get("/api/projects/{pid}/preflight/{template}")
    def check(pid: str, template: str):
        return call(svc.check, pid, template)

    @app.get("/api/projects/{pid}/export/{template}")
    def export(pid: str, template: str, allow_errors: bool = False):
        path = call(svc.export, pid, template, allow_errors)
        return FileResponse(path, media_type=XLSX, filename=path.name)

    @app.post("/api/projects/{pid}/import")
    async def import_template(pid: str, mode: str = "merge", dry_run: bool = False, file: UploadFile = File(...)):
        return call(svc.import_template, pid, file.filename or "upload.xlsx", await file.read(), mode, dry_run)

    @app.get("/api/audit")
    def audit_log():
        return svc.audit_log()

    return app


app = create_app(os.environ.get("HIERARCHY_DB", "hierarchy.sqlite"), os.environ.get("HIERARCHY_AUDIT", "export_audit.jsonl"))
