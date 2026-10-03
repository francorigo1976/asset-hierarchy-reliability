"""Excel / CSV export with validation gate and audit logging."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .audit import AuditTrail
from .templates import Template, get_template
from .validation import ValidationReport, validate_records

_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_REQUIRED_FILL = PatternFill("solid", fgColor="C00000")
_ERROR_FILL = PatternFill("solid", fgColor="FFC7CE")


class ExportBlocked(Exception):
    """Raised when validation errors prevent export and ``allow_errors`` is False."""

    def __init__(self, report: ValidationReport):
        super().__init__(f"{len(report.errors)} validation error(s); export blocked")
        self.report = report


@dataclass
class ExportResult:
    path: Path
    template: str
    rows: int
    report: ValidationReport


def _guard_formula(v: Any) -> Any:
    """Prevent spreadsheet formula injection from text values."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") and not _is_number(v):
        return "'" + v
    return v


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def export_excel(template: Template, rows: list[dict[str, Any]], report: ValidationReport, path: str | Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = template.sheet[:31]
    ws.append(template.columns)
    for c, f in enumerate(template.fields, start=1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = _REQUIRED_FILL if f.required else _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    for row in rows:
        ws.append([_guard_formula(row[col]) for col in template.columns])
    col_index = {name: i for i, name in enumerate(template.columns, start=1)}
    for issue in report.issues:
        if issue.severity == "error":
            ws.cell(row=issue.row + 1, column=col_index[issue.column]).fill = _ERROR_FILL
    for i, col in enumerate(template.columns, start=1):
        longest = max([len(col)] + [len(str(r[col])) for r in rows if r[col] is not None])
        ws.column_dimensions[get_column_letter(i)].width = min(longest + 2, 60)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    guide = wb.create_sheet("Field Guide")
    guide.append(["Column", "Source field", "Required", "Max length", "Default", "Allowed", "Description"])
    for c in guide[1]:
        c.font = Font(bold=True)
    for f in template.fields:
        guide.append([f.name, f.source or "(constant)", "Yes" if f.required else "No", f.max_len, f.default,
                      ", ".join(f.allowed) if f.allowed else None, f.description])

    if report.issues:
        sheet = wb.create_sheet("Validation")
        sheet.append(["Row", "Column", "Severity", "Message"])
        for c in sheet[1]:
            c.font = Font(bold=True)
        for i in report.issues:
            sheet.append([i.row, i.column, i.severity, i.message])

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def export_csv(template: Template, rows: list[dict[str, Any]], path: str | Path, delimiter: str = ",") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=delimiter)
        w.writerow(template.columns)
        for row in rows:
            w.writerow([_guard_formula(row[c]) for c in template.columns])
    return path


def export_records(
    template_key: str,
    records: Iterable[Mapping[str, Any]],
    path: str | Path,
    *,
    fmt: Optional[str] = None,
    allow_errors: bool = False,
    audit: Optional[AuditTrail] = None,
) -> ExportResult:
    """Validate and export canonical records using a named template.

    ``fmt`` is inferred from the file extension (.xlsx or .csv) when omitted.
    Validation errors block the export unless ``allow_errors`` is True (the
    problem cells are then highlighted in Excel output). Every attempt is audited.
    """
    template = get_template(template_key)
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".") or "xlsx").lower()
    if fmt not in ("xlsx", "csv"):
        raise ValueError(f"Unsupported format '{fmt}' (use xlsx or csv)")
    rows, report = validate_records(template, records)
    common = dict(template=template.key, system=template.system, rows=len(rows),
                  errors=len(report.errors), warnings=len(report.warnings), format=fmt)
    if report.errors and not allow_errors:
        if audit:
            audit.record("export_blocked", **common)
        raise ExportBlocked(report)
    out = export_excel(template, rows, report, path) if fmt == "xlsx" else export_csv(template, rows, path)
    if audit:
        audit.record("export", file=str(out), sha256=AuditTrail.file_sha256(out), **common)
    return ExportResult(out, template.key, len(rows), report)
