"""Mapping and pre-upload validation of records against a template."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .templates import Template


@dataclass(frozen=True)
class ValidationIssue:
    row: int            # 1-based data row (header excluded)
    column: str
    severity: str       # "error" | "warning"
    message: str


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    row_count: int = 0

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def map_record(template: Template, record: Mapping[str, Any]) -> dict[str, Any]:
    """Map a canonical record to the template's columns, applying defaults and transforms."""
    out: dict[str, Any] = {}
    for f in template.fields:
        value = record.get(f.source) if f.source else None
        if _blank(value):
            value = f.default
        elif f.transform:
            value = f.transform(value)
        out[f.name] = value
    return out


def validate_records(template: Template, records: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], ValidationReport]:
    """Map and validate records. Returns (mapped_rows, report)."""
    rows: list[dict[str, Any]] = []
    report = ValidationReport()
    seen_keys: dict[tuple, int] = {}
    key_cols = [f.name for f in template.fields if f.required][:1] or [template.fields[0].name]
    # Natural key = first column, plus item number for BOM-style templates.
    names = set(template.columns)
    if "POSNR" in names:
        key_cols.append("POSNR")

    for n, rec in enumerate(records, start=1):
        row = map_record(template, rec)
        rows.append(row)
        for f in template.fields:
            v = row[f.name]
            if _blank(v):
                if f.required:
                    report.issues.append(ValidationIssue(n, f.name, "error", "required value missing"))
                continue
            if f.max_len is not None and len(str(v)) > f.max_len:
                report.issues.append(ValidationIssue(n, f.name, "error", f"length {len(str(v))} exceeds max {f.max_len}"))
            if f.allowed is not None and str(v) not in f.allowed:
                report.issues.append(ValidationIssue(n, f.name, "error", f"'{v}' not in allowed values {list(f.allowed)}"))
        key = tuple(row[c] for c in key_cols)
        if not any(_blank(k) for k in key):
            if key in seen_keys:
                report.issues.append(ValidationIssue(n, key_cols[0], "error", f"duplicate key {key} (first at row {seen_keys[key]})"))
            else:
                seen_keys[key] = n

    # Referential check: parent must exist within the batch (warning only; may exist in target system).
    if "parent_id" in {f.source for f in template.fields}:
        pcol = next(f.name for f in template.fields if f.source == "parent_id")
        ids = {r[template.fields[0].name] for r in rows}
        for n, r in enumerate(rows, start=1):
            p = r[pcol]
            if not _blank(p) and p not in ids:
                report.issues.append(ValidationIssue(n, pcol, "warning", f"parent '{p}' not in this batch; must already exist in target"))
        for n, r in enumerate(rows, start=1):
            if not _blank(r[pcol]) and r[pcol] == r[template.fields[0].name]:
                report.issues.append(ValidationIssue(n, pcol, "error", "record is its own parent"))
    report.row_count = len(rows)
    return rows, report
