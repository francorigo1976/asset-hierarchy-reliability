# Data Export & Integration Module

`data_export/` generates upload-ready files for enterprise systems, validates them first, and audits every export.

| System | Template keys |
|---|---|
| SAP AM (Asset Accounting) | `sap_am_asset` |
| SAP PM | `sap_pm_functional_location`, `sap_pm_equipment`, `sap_pm_bom` |
| SAP MM | `sap_mm_material` |
| IBM Maximo | `maximo_asset` |
| Infor EAM | `infor_eam_equipment` |
| eMaint | `emaint_asset` |
| Maintenance Connection | `maintenance_connection_asset` |

```python
from data_export import AuditTrail, export_records
res = export_records("sap_pm_equipment", records, "out/equipment.xlsx", audit=AuditTrail("out/audit.jsonl"))
```

- **Records** use canonical keys (`asset_id`, `description`, `parent_id`, `plant`, `criticality`, `part_number`, ...); each template's `Field.source` shows the mapping.
- **Validation** (required, max length, allowed values, duplicate keys, parent/self-parent checks) runs before export. Errors raise `ExportBlocked` unless `allow_errors=True`, in which case bad cells are highlighted and a `Validation` sheet is added.
- **Excel** output has a styled header (required columns in red), frozen panes, filters, and a `Field Guide` sheet. `.csv` is also supported. Text starting with `=`, `+`, `-`, `@` is neutralised against formula injection.
- **Audit**: append-only JSONL with timestamp, user, template, row/error counts, and file SHA-256; blocked attempts are logged too.

Column names are standard SAP technical fields / common CMMS import headers; confirm against your system's configured import layout before loading. Run tests with `pip install -r requirements.txt && pytest`.

## Python app core (`asset_hierarchy/`)

Python port of the HierarchyCapture domain logic, persisted in SQLite and wired to the export templates.

- `Hierarchy` – FLOC/equipment tree: ordering, SAP-style FLOC labels (`PREFIX-SEG-SEG`, 30-char limit), unique FLOC codes,
  asset-id minting, cycle-safe moves, subtree delete with tombstones, `repair()` for orphans/cycles.
- `Store` – SQLite persistence; tombstoned nodes never reload.
- `auto_detect_catalog` – ZCM/ISA classification from the description (subset of the app's lookup table; extend `CATALOG_LOOKUP`).
- `generate_sap_name` / `validate_sap_name` – deterministic 40-char SAP short names.
- `preflight(h, template)` / `export_nodes(h, template, path, audit=...)` – pre-upload validation and export to SAP PM,
  SAP AM/MM, Maximo, Infor EAM, eMaint, Maintenance Connection.

Not yet ported: browser UI, photos/voice, FMECA engine, cloud sync, SAP LSMW 16-row template layout, SAP template import.

## Exact LSMW export and template import

- `export_lsmw(h, path)` writes the client's SAP PM LSMW workbook layout (FL 56 columns, EQ 101 columns, field codes on row 7, lengths row 8, descriptions row 9, data from row 17).
- `parse_sap_template(path)` / `apply_sap_import(h, parsed, mode="merge"|"new")` read the same workbook back (round trip). Application is atomic: any failure restores the hierarchy.
- Sub-equipment links use HEQUI = parent `asset_id` (written as LEGACYKEY); import resolves HEQUI by tag or LEGACYKEY.
