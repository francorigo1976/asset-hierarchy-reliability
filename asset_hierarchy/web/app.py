"""Web UI + JSON API for the asset hierarchy. Run: uvicorn asset_hierarchy.web.app:app"""
from __future__ import annotations

import dataclasses
import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from data_export import AuditTrail, TEMPLATES
from data_export.exporter import ExportBlocked
from ..bridge import export_nodes, preflight
from ..classify import auto_detect_catalog
from ..hierarchy import Hierarchy, HierarchyError
from ..lsmw import export_lsmw
from ..models import NODE_FIELDS, Node, Project
from ..sapimport import apply_sap_import, parse_sap_template
from ..sapname import generate_sap_name
from ..store import Store

STATIC = Path(__file__).parent / "index.html"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EDITABLE = [f for f in NODE_FIELDS if f not in {"id", "project_id", "created_at", "updated_at", "sort_order"}]


class ProjectIn(BaseModel):
    site: str
    prefix: str = ""
    client: str = ""
    auditor: str = ""
    sap_planning_plant: str = ""
    sap_maint_plant: str = ""
    sap_company_code: str = ""
    sap_cost_center: str = ""
    sap_work_center: str = ""
    sap_planner_group: str = ""
    sap_structure: str = "floc-only"
    sap_structure_indicator: str = ""


class NodeIn(BaseModel):
    parent_id: Optional[str] = None
    is_area: bool = False
    description: str = ""
    fields: dict = {}


class MoveIn(BaseModel):
    parent_id: Optional[str] = None


def _name(node: Node) -> None:
    sn = generate_sap_name(node)
    if sn:
        node.sap_name, node.sap_name_long, node.sap_name_needs_review = sn.sap_name, sn.sap_name_long, sn.needs_review


def create_app(db_path: str = "hierarchy.sqlite", audit_path: str = "export_audit.jsonl",
               export_dir: Optional[str] = None) -> FastAPI:
    app = FastAPI(title="Asset Hierarchy")
    store = Store(db_path)
    audit = AuditTrail(audit_path)
    out_dir = Path(export_dir or tempfile.mkdtemp(prefix="exports_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    def load(pid: str) -> Hierarchy:
        try:
            return store.load(pid)
        except Exception:
            raise HTTPException(404, "project not found")

    def dump(h: Hierarchy) -> dict:
        return {"project": dataclasses.asdict(h.project),
                "nodes": [dict(dataclasses.asdict(n), floc_label=h.floc_label(n) if n.is_area else "")
                          for n in h.ordered()]}

    @app.get("/", response_class=HTMLResponse)
    def index():
        return STATIC.read_text(encoding="utf-8")

    @app.get("/api/templates")
    def templates():
        return [{"key": k, "name": getattr(t, "name", k)} for k, t in TEMPLATES.items()] + [
            {"key": "lsmw", "name": "SAP PM LSMW workbook (FL + EQ)"}]

    @app.get("/api/projects")
    def projects():
        return [{"id": i, "site": s} for i, s in store.list_projects()]

    @app.post("/api/projects")
    def new_project(p: ProjectIn):
        h = Hierarchy(Project(**p.model_dump()))
        store.save(h)
        return dump(h)

    @app.put("/api/projects/{pid}")
    def update_project(pid: str, p: ProjectIn):
        h = load(pid)
        for k, v in p.model_dump().items():
            setattr(h.project, k, v)
        store.save(h)
        return dump(h)

    @app.get("/api/projects/{pid}")
    def tree(pid: str):
        return dump(load(pid))

    @app.post("/api/projects/{pid}/nodes")
    def add_node(pid: str, n: NodeIn):
        h = load(pid)
        extra = {k: v for k, v in n.fields.items() if k in EDITABLE and k not in {"parent_id", "is_area", "description", "name"}}
        try:
            node = h.add(parent_id=n.parent_id, is_area=n.is_area, description=n.description, **extra)
        except HierarchyError as e:
            raise HTTPException(400, str(e))
        if not node.is_area and not node.catalog_code:
            d = auto_detect_catalog(node.description)
            if d and d.catalog_code:
                node.catalog_code, node.needs_catalog_review = d.catalog_code, d.needs_review
                node.isa_variable, node.isa_function, node.isa_differential = d.isa_variable, d.isa_function, d.isa_differential
        _name(node)
        store.save(h)
        return dump(h)

    @app.patch("/api/projects/{pid}/nodes/{nid}")
    def edit_node(pid: str, nid: str, fields: dict):
        h = load(pid)
        node = h.get(nid)
        if not node:
            raise HTTPException(404, "node not found")
        for k, v in fields.items():
            if k in EDITABLE and k not in {"parent_id", "is_area", "asset_id"}:
                setattr(node, k, v.upper() if k in {"description", "name"} and isinstance(v, str) else v)
        if "sap_name" not in fields:
            _name(node)
        store.save(h)
        return dump(h)

    @app.post("/api/projects/{pid}/nodes/{nid}/move")
    def move_node(pid: str, nid: str, m: MoveIn):
        h = load(pid)
        try:
            h.move(nid, m.parent_id)
        except HierarchyError as e:
            raise HTTPException(400, str(e))
        store.save(h)
        return dump(h)

    @app.delete("/api/projects/{pid}/nodes/{nid}")
    def delete_node(pid: str, nid: str):
        h = load(pid)
        if not h.get(nid):
            raise HTTPException(404, "node not found")
        h.delete(nid)
        store.save(h)
        return dump(h)

    @app.get("/api/projects/{pid}/preflight/{template}")
    def check(pid: str, template: str):
        h = load(pid)
        if template == "lsmw":
            res = export_lsmw(h, out_dir / f"{pid}_check.xlsx")
            return {"rows": res["flocs"] + res["equipment"], "errors": [], "ok": not res["violations"],
                    "warnings": [{"message": str(m)} for m in res["warnings"]] +
                                [{"message": str(v)} for v in res["violations"]], "truncations": res["truncations"]}
        if template not in TEMPLATES:
            raise HTTPException(404, "unknown template")
        return preflight(h, template)

    @app.get("/api/projects/{pid}/export/{template}")
    def export(pid: str, template: str, allow_errors: bool = False):
        h = load(pid)
        path = out_dir / f"{h.project.site or pid}_{template}.xlsx".replace(" ", "_")
        if template == "lsmw":
            res = export_lsmw(h, path)
            audit.record("export", template="lsmw", project=pid, flocs=res["flocs"], equipment=res["equipment"],
                         violations=len(res["violations"]), sha256=AuditTrail.file_sha256(path))
        elif template in TEMPLATES:
            try:
                export_nodes(h, template, path, audit=audit, allow_errors=allow_errors)
            except ExportBlocked as e:
                raise HTTPException(422, str(e))
        else:
            raise HTTPException(404, "unknown template")
        return FileResponse(path, media_type=XLSX, filename=path.name)

    @app.post("/api/projects/{pid}/import")
    async def import_template(pid: str, mode: str = "merge", dry_run: bool = False, file: UploadFile = File(...)):
        h = load(pid)
        tmp = out_dir / f"upload_{os.getpid()}_{file.filename}"
        tmp.write_bytes(await file.read())
        parsed = parse_sap_template(tmp)
        info = {"flocs": len(parsed.flocs), "equipment": len(parsed.equip), "errors": parsed.errors,
                "warnings": parsed.warnings,
                "record_errors": parsed.record_errors, "record_warnings": parsed.record_warnings}
        if dry_run:
            return info
        try:
            stats = apply_sap_import(h, parsed, mode)
        except ValueError as e:
            raise HTTPException(422, str(e))
        store.save(h)
        audit.record("import", project=pid, file=file.filename, mode=mode, sha256=AuditTrail.file_sha256(tmp),
                     added=stats["added"], updated=stats["updated"])
        return {**info, "stats": stats, **dump(h)}

    @app.get("/api/audit")
    def audit_log():
        return audit.entries()[-200:]

    return app


app = create_app(os.environ.get("HIERARCHY_DB", "hierarchy.sqlite"), os.environ.get("HIERARCHY_AUDIT", "export_audit.jsonl"))
