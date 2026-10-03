"""Turn hierarchy nodes into canonical records for the data_export templates."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from data_export import AuditTrail, export_records
from data_export.validation import validate_records
from data_export.templates import get_template

from .classify import auto_detect_catalog
from .hierarchy import Hierarchy
from .sapname import generate_sap_name

SAP_PM = {"floc": "sap_pm_functional_location", "equipment": "sap_pm_equipment"}


def build_records(h: Hierarchy, kind: str, system: str = "sap") -> list[dict]:
    """kind: 'floc' | 'equipment'. Canonical keys match data_export template Field.source values."""
    p, recs = h.project, []
    for n in h.ordered():
        if kind == "floc" and not n.is_area:
            continue
        if kind == "equipment" and not n.is_equipment_record:
            continue
        floc = h.floc_label(n)
        if kind == "floc":
            parent = h.get(n.parent_id)
            recs.append({"asset_id": floc, "description": n.description or n.name,
                         "parent_id": h.floc_label(parent) if parent and parent.is_area else "",
                         "plant": p.sap_maint_plant, "cost_center": p.sap_cost_center, "location_category": "L",
                         "criticality": ""})
        else:
            sn = generate_sap_name(n)
            det = auto_detect_catalog(n.description) if not n.catalog_code else None
            install = n if n.is_area else h.get(n.parent_id)
            recs.append({"asset_id": n.asset_id, "description": n.sap_name or (sn.sap_name if sn else n.description),
                         "asset_type": n.catalog_code or (det.catalog_code if det and det.catalog_code else "EQUIPMENT"),
                         "manufacturer": n.manufacturer, "model": n.model, "serial_number": n.serial,
                         "year_built": n.year, "parent_id": h.floc_label(install) if install else "",
                         "plant": p.sap_maint_plant, "site": p.sap_maint_plant, "cost_center": p.sap_cost_center})
    return recs


def export_nodes(h: Hierarchy, template_key: str, path: str | Path, *, audit: Optional[AuditTrail] = None,
                 allow_errors: bool = False):
    """Export a project to any data_export template (SAP PM, Maximo, Infor, eMaint, MC...)."""
    kind = "floc" if "functional_location" in template_key else "equipment"
    return export_records(template_key, build_records(h, kind), path, allow_errors=allow_errors, audit=audit)


def preflight(h: Hierarchy, template_key: str) -> dict:
    """Pre-upload validation summary (what the UI validation screen would show)."""
    kind = "floc" if "functional_location" in template_key else "equipment"
    _, rep = validate_records(get_template(template_key), build_records(h, kind))
    return {"rows": rep.row_count, "errors": [vars(i) for i in rep.errors], "warnings": [vars(i) for i in rep.warnings],
            "ok": rep.ok}
