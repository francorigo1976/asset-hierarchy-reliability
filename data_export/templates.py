"""Upload template definitions for SAP (AM/PM/MM) and CMMS systems.

Each template maps canonical internal record keys (``source``) to the target
system's column name, with required/length/allowed-value rules used by validation.
Column names follow the standard SAP technical field names and common CMMS import
headers; verify against your system's configured import layout before loading.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence


@dataclass(frozen=True)
class Field:
    name: str                       # target column header
    source: Optional[str] = None    # canonical key in the source record (None -> constant/default)
    required: bool = False
    max_len: Optional[int] = None
    default: Any = None
    allowed: Optional[Sequence[str]] = None
    transform: Optional[Callable[[Any], Any]] = None
    description: str = ""


@dataclass(frozen=True)
class Template:
    key: str
    system: str
    module: str
    sheet: str
    description: str
    fields: Sequence[Field] = field(default_factory=tuple)

    @property
    def columns(self) -> list[str]:
        return [f.name for f in self.fields]


def _upper(v: Any) -> Any:
    return str(v).strip().upper() if v is not None else v


def _sap_date(v: Any) -> Any:
    """Return YYYYMMDD for date/datetime/ISO strings (SAP internal format)."""
    if v in (None, ""):
        return v
    if hasattr(v, "strftime"):
        return v.strftime("%Y%m%d")
    return str(v).replace("-", "")[:8]


def _iso_date(v: Any) -> Any:
    if v in (None, ""):
        return v
    return v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v)[:10]


def _criticality_abc(v: Any) -> Any:
    return {"1": "A", "2": "B", "3": "C", "HIGH": "A", "MEDIUM": "B", "LOW": "C"}.get(str(v).strip().upper(), v)


TEMPLATES: dict[str, Template] = {}


def _register(t: Template) -> None:
    TEMPLATES[t.key] = t


_register(Template(
    "sap_am_asset", "SAP", "AM", "SAP AM - Asset Master",
    "SAP Asset Accounting master record upload (AS91-style)",
    (
        Field("ANLN1", "asset_id", True, 12, transform=_upper, description="Main asset number"),
        Field("ANLN2", None, False, 4, default="0", description="Asset subnumber"),
        Field("ANLKL", "asset_class", True, 8, description="Asset class"),
        Field("BUKRS", "company_code", True, 4, description="Company code"),
        Field("TXT50", "description", True, 50, description="Asset description"),
        Field("TXA50", "description_long", False, 50, description="Additional description"),
        Field("SERNR", "serial_number", False, 18, description="Serial number"),
        Field("INVNR", "inventory_number", False, 25, description="Inventory number"),
        Field("KOSTL", "cost_center", False, 10, description="Cost center"),
        Field("AKTIV", "install_date", False, 8, transform=_sap_date, description="Capitalization date YYYYMMDD"),
        Field("ANSWL", "acquisition_cost", False, None, description="Acquisition value"),
        Field("WAERS", "currency", False, 5, default="USD", description="Currency"),
    ),
))

_register(Template(
    "sap_pm_functional_location", "SAP", "PM", "SAP PM - Functional Locations",
    "SAP PM functional location master upload (IL01-style); hierarchy via TPLMA",
    (
        Field("TPLNR", "asset_id", True, 40, transform=_upper, description="Functional location"),
        Field("PLTXT", "description", True, 40, description="Description"),
        Field("FLTYP", "location_category", False, 1, default="M", description="Structure indicator category"),
        Field("TPLMA", "parent_id", False, 40, transform=_upper, description="Superior functional location"),
        Field("SWERK", "plant", True, 4, description="Maintenance plant"),
        Field("KOSTL", "cost_center", False, 10, description="Cost center"),
        Field("ABCKZ", "criticality", False, 1, transform=_criticality_abc, allowed=("A", "B", "C"),
              description="ABC indicator (criticality)"),
        Field("STORT", "location", False, 10, description="Location"),
    ),
))

_register(Template(
    "sap_pm_equipment", "SAP", "PM", "SAP PM - Equipment",
    "SAP PM equipment master upload (IE01-style)",
    (
        Field("EQUNR", "asset_id", True, 18, transform=_upper, description="Equipment number"),
        Field("EQKTX", "description", True, 40, description="Description"),
        Field("EQART", "asset_type", True, 10, description="Technical object type"),
        Field("HERST", "manufacturer", False, 30, description="Manufacturer"),
        Field("TYPBZ", "model", False, 20, description="Model number"),
        Field("SERGE", "serial_number", False, 30, description="Manufacturer serial number"),
        Field("BAUJJ", "year_built", False, 4, description="Year of construction"),
        Field("TPLNR", "parent_id", False, 40, transform=_upper, description="Functional location"),
        Field("SWERK", "plant", True, 4, description="Maintenance plant"),
        Field("ABCKZ", "criticality", False, 1, transform=_criticality_abc, allowed=("A", "B", "C"),
              description="ABC indicator"),
    ),
))

_register(Template(
    "sap_mm_material", "SAP", "MM", "SAP MM - Material Master",
    "SAP MM material master upload for spare parts / BOM components (MM01-style)",
    (
        Field("MATNR", "part_number", True, 18, transform=_upper, description="Material number"),
        Field("MAKTX", "description", True, 40, description="Material description"),
        Field("MTART", "material_type", True, 4, default="ERSA", description="Material type (ERSA = spare part)"),
        Field("MATKL", "material_group", False, 9, description="Material group"),
        Field("MEINS", "uom", True, 3, default="EA", description="Base unit of measure"),
        Field("WERKS", "plant", True, 4, description="Plant"),
        Field("MFRNR", "manufacturer", False, 10, description="Manufacturer"),
        Field("MFRPN", "manufacturer_part_number", False, 40, description="Manufacturer part number"),
        Field("STPRS", "unit_cost", False, None, description="Standard price"),
    ),
))

_register(Template(
    "sap_pm_bom", "SAP", "PM", "SAP PM - Equipment BOM",
    "SAP equipment BOM item upload (IB01-style); links equipment to MM materials",
    (
        Field("EQUNR", "asset_id", True, 18, transform=_upper, description="Equipment number"),
        Field("POSNR", "item_number", True, 4, description="BOM item number"),
        Field("IDNRK", "part_number", True, 18, transform=_upper, description="Component material"),
        Field("MENGE", "quantity", True, None, description="Component quantity"),
        Field("MEINS", "uom", False, 3, default="EA", description="Unit of measure"),
        Field("WERKS", "plant", True, 4, description="Plant"),
    ),
))

_register(Template(
    "maximo_asset", "IBM Maximo", "Asset", "ASSET",
    "IBM Maximo ASSET object structure import",
    (
        Field("ASSETNUM", "asset_id", True, 25, transform=_upper),
        Field("DESCRIPTION", "description", True, 100),
        Field("SITEID", "site", True, 8),
        Field("LOCATION", "location", False, 12),
        Field("PARENT", "parent_id", False, 25, transform=_upper),
        Field("ASSETTYPE", "asset_type", False, 15),
        Field("MANUFACTURER", "manufacturer", False, 30),
        Field("SERIALNUM", "serial_number", False, 30),
        Field("STATUS", "status", False, 20, default="OPERATING",
              allowed=("OPERATING", "NOT READY", "ACTIVE", "DECOMMISSIONED"), transform=_upper),
        Field("INSTALLDATE", "install_date", False, None, transform=_iso_date),
        Field("PRIORITY", "criticality", False, 3),
    ),
))

_register(Template(
    "infor_eam_equipment", "Infor EAM", "Equipment", "Equipment",
    "Infor EAM equipment upload",
    (
        Field("EQUIPMENTCODE", "asset_id", True, 30, transform=_upper),
        Field("EQUIPMENTDESC", "description", True, 80),
        Field("ORGANIZATION", "site", True, 15),
        Field("DEPARTMENT", "department", False, 15),
        Field("CLASS", "asset_class", False, 15),
        Field("PARENTCODE", "parent_id", False, 30, transform=_upper),
        Field("MANUFACTURER", "manufacturer", False, 30),
        Field("MODEL", "model", False, 30),
        Field("SERIALNUMBER", "serial_number", False, 30),
        Field("CRITICALITY", "criticality", False, 3),
        Field("INSTALLDATE", "install_date", False, None, transform=_iso_date),
    ),
))

_register(Template(
    "emaint_asset", "eMaint", "Assets", "Assets",
    "Fluke eMaint asset import",
    (
        Field("AssetID", "asset_id", True, 50, transform=_upper),
        Field("AssetName", "description", True, 100),
        Field("ParentAssetID", "parent_id", False, 50, transform=_upper),
        Field("AssetType", "asset_type", False, 30),
        Field("Site", "site", False, 30),
        Field("Manufacturer", "manufacturer", False, 50),
        Field("ModelNumber", "model", False, 50),
        Field("SerialNumber", "serial_number", False, 50),
        Field("Criticality", "criticality", False, 10),
        Field("InServiceDate", "install_date", False, None, transform=_iso_date),
    ),
))

_register(Template(
    "maintenance_connection_asset", "Maintenance Connection", "Assets", "Assets",
    "Maintenance Connection asset import",
    (
        Field("AssetNumber", "asset_id", True, 50, transform=_upper),
        Field("AssetDescription", "description", True, 100),
        Field("ParentAssetNumber", "parent_id", False, 50, transform=_upper),
        Field("Facility", "site", True, 30),
        Field("AssetClass", "asset_class", False, 30),
        Field("Manufacturer", "manufacturer", False, 50),
        Field("Model", "model", False, 50),
        Field("SerialNumber", "serial_number", False, 50),
        Field("Priority", "criticality", False, 10),
        Field("InstallDate", "install_date", False, None, transform=_iso_date),
    ),
))


def get_template(key: str) -> Template:
    try:
        return TEMPLATES[key]
    except KeyError:
        raise KeyError(f"Unknown template '{key}'. Available: {', '.join(sorted(TEMPLATES))}") from None


def list_templates(system: Optional[str] = None) -> list[Template]:
    return [t for t in TEMPLATES.values() if system is None or t.system.lower() == system.lower()]
