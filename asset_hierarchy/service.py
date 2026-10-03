"""Transport-independent application service. Used by the FastAPI app and by the in-browser (Pyodide) build."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Optional

from data_export import AuditTrail, TEMPLATES
from data_export.exporter import ExportBlocked
from .bridge import export_nodes, preflight
from .classify import auto_detect_catalog
from .hierarchy import Hierarchy, HierarchyError
from .lsmw import export_lsmw
from .models import NODE_FIELDS, Node, Project
from .sapimport import apply_sap_import, parse_sap_template
from .sapname import generate_sap_name

EDITABLE = [f for f in NODE_FIELDS if f not in {"id", "project_id", "created_at", "updated_at", "sort_order"}]
PROJECT_FIELDS = ["site", "prefix", "client", "auditor", "sap_planning_plant", "sap_maint_plant", "sap_company_code",
                  "sap_cost_center", "sap_work_center", "sap_planner_group", "sap_structure", "sap_structure_indicator"]


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def apply_names(node: Node) -> None:
    sn = generate_sap_name(node)
    if sn:
        node.sap_name, node.sap_name_long, node.sap_name_needs_review = sn.sap_name, sn.sap_name_long, sn.needs_review


class Service:
    def __init__(self, store, audit: AuditTrail, out_dir: Path):
        self.store, self.audit, self.out_dir = store, audit, Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def load(self, pid: str) -> Hierarchy:
        try:
            return self.store.load(pid)
        except Exception:
            raise ApiError(404, "project not found")

    @staticmethod
    def dump(h: Hierarchy) -> dict:
        return {"project": dataclasses.asdict(h.project),
                "nodes": [dict(dataclasses.asdict(n), floc_label=h.floc_label(n) if n.is_area else "")
                          for n in h.ordered()]}

    def templates(self):
        return [{"key": k, "name": getattr(t, "name", k)} for k, t in TEMPLATES.items()] + [
            {"key": "lsmw", "name": "SAP PM LSMW workbook (FL + EQ)"}]

    def projects(self):
        return [{"id": i, "site": s} for i, s in self.store.list_projects()]

    def new_project(self, data: dict):
        h = Hierarchy(Project(**{k: v for k, v in data.items() if k in PROJECT_FIELDS}))
        self.store.save(h)
        return self.dump(h)

    def update_project(self, pid: str, data: dict):
        h = self.load(pid)
        for k, v in data.items():
            if k in PROJECT_FIELDS:
                setattr(h.project, k, v)
        self.store.save(h)
        return self.dump(h)

    def tree(self, pid: str):
        return self.dump(self.load(pid))

    def add_node(self, pid: str, data: dict):
        h = self.load(pid)
        skip = {"parent_id", "is_area", "description", "name"}
        extra = {k: v for k, v in (data.get("fields") or {}).items() if k in EDITABLE and k not in skip}
        try:
            node = h.add(parent_id=data.get("parent_id"), is_area=bool(data.get("is_area")),
                         description=data.get("description", ""), **extra)
        except HierarchyError as e:
            raise ApiError(400, str(e))
        if not node.is_area and not node.catalog_code:
            d = auto_detect_catalog(node.description)
            if d and d.catalog_code:
                node.catalog_code, node.needs_catalog_review = d.catalog_code, d.needs_review
                node.isa_variable, node.isa_function, node.isa_differential = d.isa_variable, d.isa_function, d.isa_differential
        apply_names(node)
        self.store.save(h)
        return self.dump(h)

    def edit_node(self, pid: str, nid: str, fields: dict):
        h = self.load(pid)
        node = h.get(nid)
        if not node:
            raise ApiError(404, "node not found")
        for k, v in fields.items():
            if k in EDITABLE and k not in {"parent_id", "is_area", "asset_id"}:
                setattr(node, k, v.upper() if k in {"description", "name"} and isinstance(v, str) else v)
        if "sap_name" not in fields:
            apply_names(node)
        self.store.save(h)
        return self.dump(h)

    def move_node(self, pid: str, nid: str, parent_id: Optional[str]):
        h = self.load(pid)
        try:
            h.move(nid, parent_id)
        except HierarchyError as e:
            raise ApiError(400, str(e))
        self.store.save(h)
        return self.dump(h)

    def delete_node(self, pid: str, nid: str):
        h = self.load(pid)
        if not h.get(nid):
            raise ApiError(404, "node not found")
        h.delete(nid)
        self.store.save(h)
        return self.dump(h)

    def check(self, pid: str, template: str):
        h = self.load(pid)
        if template == "lsmw":
            res = export_lsmw(h, self.out_dir / f"{pid}_check.xlsx")
            return {"rows": res["flocs"] + res["equipment"], "errors": [], "ok": not res["violations"],
                    "warnings": [{"message": str(m)} for m in res["warnings"]] +
                                [{"message": str(v)} for v in res["violations"]], "truncations": res["truncations"]}
        if template not in TEMPLATES:
            raise ApiError(404, "unknown template")
        return preflight(h, template)

    def export(self, pid: str, template: str, allow_errors: bool = False) -> Path:
        h = self.load(pid)
        path = self.out_dir / f"{h.project.site or pid}_{template}.xlsx".replace(" ", "_")
        if template == "lsmw":
            res = export_lsmw(h, path)
            self.audit.record("export", template="lsmw", project=pid, flocs=res["flocs"], equipment=res["equipment"],
                              violations=len(res["violations"]), sha256=AuditTrail.file_sha256(path))
        elif template in TEMPLATES:
            try:
                export_nodes(h, template, path, audit=self.audit, allow_errors=allow_errors)
            except ExportBlocked as e:
                raise ApiError(422, str(e))
        else:
            raise ApiError(404, "unknown template")
        return path

    def import_template(self, pid: str, filename: str, content: bytes, mode: str = "merge", dry_run: bool = False):
        h = self.load(pid)
        tmp = self.out_dir / f"upload_{Path(filename).name}"
        tmp.write_bytes(content)
        parsed = parse_sap_template(tmp)
        info = {"flocs": len(parsed.flocs), "equipment": len(parsed.equip), "errors": parsed.errors,
                "warnings": parsed.warnings, "record_errors": parsed.record_errors,
                "record_warnings": parsed.record_warnings}
        if dry_run:
            return info
        try:
            stats = apply_sap_import(h, parsed, mode)
        except ValueError as e:
            raise ApiError(422, str(e))
        self.store.save(h)
        self.audit.record("import", project=pid, file=filename, mode=mode, sha256=AuditTrail.file_sha256(tmp),
                          added=stats["added"], updated=stats["updated"])
        return {**info, "stats": stats, **self.dump(h)}

    def audit_log(self):
        return self.audit.entries()[-200:]
