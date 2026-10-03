from __future__ import annotations

import uuid
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


@dataclass
class Project:
    site: str
    id: str = field(default_factory=_uuid)
    client: str = ""
    auditor: str = ""
    prefix: str = ""            # FLOC root segment, max 5 chars
    next_seq: int = 1
    sap_planning_plant: str = ""
    sap_maint_plant: str = ""
    sap_company_code: str = ""
    sap_cost_center: str = ""
    sap_structure: str = "floc-only"   # floc-only | one-to-one | structure-leaf
    sap_work_center: str = ""
    sap_planner_group: str = ""
    sap_structure_indicator: str = ""
    created_at: str = field(default_factory=_now)


@dataclass
class Node:
    """A Functional Location (is_area=True) or an Equipment record."""
    project_id: str
    id: str = field(default_factory=_uuid)
    parent_id: Optional[str] = None
    asset_id: str = ""
    name: str = ""
    description: str = ""
    is_area: bool = False
    is_also_equipment: bool = False     # SAP 1:1 FLOC + Equipment
    status: str = "manual"              # manual | queued | review | confirmed | imported
    tag_number: str = ""
    floc_code: str = ""
    catalog_code: str = ""              # ZCM code
    isa_variable: str = ""
    isa_function: str = ""
    isa_differential: bool = False
    needs_catalog_review: bool = False
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    year: str = ""
    rating: str = ""
    tann_part_no: str = ""
    notes: str = ""
    sort_order: int = 0
    sap_name: str = ""
    sap_name_long: str = ""
    sap_name_needs_review: bool = False
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @property
    def is_equipment_record(self) -> bool:
        return (not self.is_area) or self.is_also_equipment


NODE_FIELDS = [f.name for f in fields(Node)]
