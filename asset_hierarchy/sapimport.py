"""Import an SAP LSMW upload workbook (ours or the client's) into a Hierarchy. Port of parseSapTemplate/applySapImport."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from openpyxl import load_workbook

from .hierarchy import Hierarchy
from .lsmw import EQ_SPEC, FL_SPEC

FL_SHEETS = ["New Functional Locations", "New FLOC", "Functional Locations", "FLOC"]
EQ_SHEETS = ["New Equipment", "Equipment", "New Equipment Master"]
LABELS = {"length", "description", "sample", "example", "field", "rcs rules"}
FL_LIMITS = {c: n for c, n, _ in FL_SPEC}
EQ_LIMITS = {c: n for c, n, _ in EQ_SPEC}
FL_FIELDS = "TPLNR PLTXT TPLMA TPLKZ FLTYP SWERK IWERK BUKRS KOSTL ARBPL INGRP EQFNR POSNR HERST TYPBZ SERGE BAUJJ MAPAR EQART RBNR".split()
EQ_FIELDS = ("LEGACYKEY EQUNR EQKTX EQTYP EQART HERST TYPBZ SERGE MAPAR BAUJJ EQFNR TIDNR TPLNR HEQUI RBNR "
             "SWERK IWERK BUKRS KOSTL ARBPL").split()


@dataclass
class ParsedTemplate:
    flocs: list[dict] = field(default_factory=list)
    equip: list[dict] = field(default_factory=list)
    project_fields: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    record_errors: list[tuple[str, str, str]] = field(default_factory=list)    # (kind, ref, message)
    record_warnings: list[tuple[str, str, str]] = field(default_factory=list)


def _sheet(wb, names):
    for n in names:
        if n in wb.sheetnames:
            return wb[n]
    low = {s.lower(): s for s in wb.sheetnames}
    for n in names:
        if n.lower() in low:
            return wb[low[n.lower()]]
    return None


def _rows(ws):
    return [["" if v is None else str(v).strip() for v in r] for r in ws.iter_rows(values_only=True)]


def _scan(rows, anchors, wanted, is_record):
    fr = next((i for i, r in enumerate(rows[:30]) if any(c.upper() in anchors for c in r)), -1)
    if fr < 0:
        return False, []
    cm: dict = {}
    for i, c in enumerate(rows[fr]):
        if c and c.upper() not in cm:
            cm[c.upper()] = i
    out = []
    for r in rows[fr + 1:]:
        if r and r[0].lower() in LABELS:
            continue
        rec = {f: (r[cm[f]] if f in cm and cm[f] < len(r) else "") for f in wanted}
        if is_record(rec):
            out.append(rec)
    return True, out


def parent_tplnr(t: str) -> Optional[str]:
    parts = t.split("-")
    return "-".join(parts[:-1]) if len(parts) > 1 else None


def parse_sap_template(path: str | Path) -> ParsedTemplate:
    wb = load_workbook(path, data_only=True)
    res = ParsedTemplate()
    fl, eq = _sheet(wb, FL_SHEETS), _sheet(wb, EQ_SHEETS)
    if not fl and not eq:
        res.errors.append("No 'New Functional Locations' or 'New Equipment' sheet found. Sheets: " + ", ".join(wb.sheetnames))
        return res
    if fl:
        ok, res.flocs = _scan(_rows(fl), {"TPLNR"}, FL_FIELDS, lambda r: bool(r["TPLNR"]))
        if not ok:
            res.errors.append(f"FL sheet '{fl.title}': missing required column TPLNR")
        elif res.flocs:
            f0 = res.flocs[0]
            res.project_fields = {"sap_maint_plant": f0["SWERK"], "sap_planning_plant": f0["IWERK"],
                                  "sap_company_code": f0["BUKRS"], "sap_cost_center": f0["KOSTL"],
                                  "sap_work_center": f0["ARBPL"], "sap_planner_group": f0["INGRP"],
                                  "sap_structure_indicator": f0["TPLKZ"]}
    if eq:
        ok, res.equip = _scan(_rows(eq), {"EQUNR", "EQKTX", "EQFNR"}, EQ_FIELDS,
                              lambda r: bool(r["EQKTX"] or r["EQFNR"] or r["TPLNR"]))
        if not ok:
            res.errors.append(f"EQ sheet '{eq.title}': missing EQKTX/EQUNR/EQFNR")
    ids, seen = {f["TPLNR"] for f in res.flocs}, set()
    for f in res.flocs:
        if f["TPLNR"] in seen:
            res.warnings.append(f"Duplicate FLOC label: {f['TPLNR']}")
        seen.add(f["TPLNR"])
        if f["TPLMA"] and f["TPLMA"] not in ids:
            res.warnings.append(f"FLOC {f['TPLNR']} references missing parent {f['TPLMA']} — derived from label")
    orphans = sum(1 for e in res.equip if not e["TPLNR"])
    if orphans:
        res.warnings.append(f"{orphans} equipment row(s) without a FLOC (TPLNR blank)")
    _validate(res)
    return res


def _validate(res: ParsedTemplate) -> None:
    ids = {f["TPLNR"] for f in res.flocs}
    for f in res.flocs:
        seen, cur = set(), f["TPLNR"]
        while cur:
            if cur in seen:
                res.record_errors.append(("floc", f["TPLNR"], "Circular parent reference"))
                break
            seen.add(cur)
            cur = parent_tplnr(cur)
        for code, lim in FL_LIMITS.items():
            if code in f and len(f[code]) > lim:
                res.record_warnings.append(("floc", f["TPLNR"], f"{code} exceeds SAP limit ({len(f[code])}/{lim})"))
    for e in res.equip:
        ref = e["EQFNR"] or e["EQKTX"] or "(no tag)"
        if not e["EQKTX"] and not (e["EQFNR"] or e["TIDNR"]):
            res.record_errors.append(("equip", ref, "Missing description (EQKTX) and tag (EQFNR)"))
        if e["TPLNR"] and e["TPLNR"] not in ids:
            res.record_warnings.append(("equip", ref, f"references FLOC {e['TPLNR']} not in this import"))
        for code, lim in EQ_LIMITS.items():
            if code in e and len(e[code]) > lim:
                res.record_warnings.append(("equip", ref, f"{code} exceeds SAP limit ({len(e[code])}/{lim})"))


def apply_sap_import(h: Hierarchy, parsed: ParsedTemplate, mode: str = "merge") -> dict:
    """Atomic: any exception restores the hierarchy exactly. 'merge' updates matches, 'new' only adds."""
    if parsed.errors or parsed.record_errors:
        raise ValueError("template has blocking errors: " + "; ".join(parsed.errors + [m for *_, m in parsed.record_errors]))
    snap_nodes, snap_proj = copy.deepcopy(h.nodes), copy.deepcopy(h.project.__dict__)
    try:
        return _apply(h, parsed, mode)
    except Exception:
        h.nodes = snap_nodes
        h.project.__dict__.update(snap_proj)
        raise


def _apply(h: Hierarchy, parsed: ParsedTemplate, mode: str) -> dict:
    stats = {"added": 0, "updated": 0, "skipped": 0, "warnings": list(parsed.warnings)}
    for k, v in parsed.project_fields.items():
        if v and not getattr(h.project, k):
            setattr(h.project, k, v)
    if parsed.flocs and not h.project.prefix:
        h.project.prefix = parsed.flocs[0]["TPLNR"].split("-")[0].upper()
    existing = {h.floc_label(n): n for n in h.nodes.values() if n.is_area} if mode == "merge" else {}
    by_tpl: dict = {}
    for f in sorted(parsed.flocs, key=lambda f: (f["TPLNR"].count("-"), f["TPLNR"])):
        also_eq = any(f[k] for k in ("HERST", "TYPBZ", "SERGE", "BAUJJ", "MAPAR"))
        node = existing.get(f["TPLNR"])
        if node:
            if f["PLTXT"]:
                node.description, node.name = f["PLTXT"].upper(), f["PLTXT"].split("-")[0].upper()
            if f["EQFNR"] and not node.tag_number:
                node.tag_number = f["EQFNR"]
            if f["RBNR"] and not node.catalog_code:
                node.catalog_code = f["RBNR"]
            if also_eq:
                node.is_also_equipment = True
                node.manufacturer, node.model = f["HERST"] or node.manufacturer, f["TYPBZ"] or node.model
                node.serial, node.year = f["SERGE"] or node.serial, f["BAUJJ"] or node.year
                node.tann_part_no = f["MAPAR"] or node.tann_part_no
            by_tpl[f["TPLNR"]] = node
            stats["updated"] += 1
            continue
        parent = by_tpl.get(f["TPLMA"] or parent_tplnr(f["TPLNR"]) or "")
        seg = f["TPLNR"].split("-")[-1]
        by_tpl[f["TPLNR"]] = h.add(
            parent_id=parent.id if parent else None, is_area=True, description=f["PLTXT"] or seg, status="imported",
            is_also_equipment=also_eq, floc_code=seg, tag_number=f["EQFNR"] if also_eq else "", catalog_code=f["RBNR"],
            manufacturer=f["HERST"], model=f["TYPBZ"], serial=f["SERGE"], year=f["BAUJJ"], tann_part_no=f["MAPAR"],
            sort_order=int(f["POSNR"]) if f["POSNR"].isdigit() and int(f["POSNR"]) > 0 else 0)
        stats["added"] += 1

    by_tag = {n.tag_number: n for n in by_tpl.values() if n.is_also_equipment and n.tag_number}
    by_key: dict = {}                       # LEGACYKEY (our asset_id) -> node, for HEQUI resolution
    existing_eq: dict = {}
    if mode == "merge":
        for n in h.nodes.values():
            if not n.is_area and n.tag_number:
                inst = h.get(n.parent_id)
                while inst and not inst.is_area:
                    inst = h.get(inst.parent_id)
                existing_eq[(n.tag_number, h.floc_label(inst) if inst else "")] = n
    hequi: list[tuple] = []
    for e in parsed.equip:
        tag = e["EQFNR"] or e["TIDNR"]
        if tag and tag in by_tag and by_tag[tag].is_also_equipment:
            stats["skipped"] += 1           # already created as a 1:1 FLOC+Equipment
            continue
        hit = existing_eq.get((tag, e["TPLNR"])) if tag else None
        if hit:
            if e["EQKTX"]:
                hit.description, hit.name = e["EQKTX"].upper(), e["EQKTX"].split("-")[0].upper()
            hit.manufacturer, hit.model = e["HERST"] or hit.manufacturer, e["TYPBZ"] or hit.model
            hit.serial, hit.year = e["SERGE"] or hit.serial, e["BAUJJ"] or hit.year
            hit.tann_part_no = e["MAPAR"] or hit.tann_part_no
            by_tag[tag] = hit
            if e["LEGACYKEY"]:
                by_key[e["LEGACYKEY"]] = hit
            if e["HEQUI"]:
                hequi.append((hit, e["HEQUI"]))
            stats["updated"] += 1
            continue
        flnode = by_tpl.get(e["TPLNR"]) or existing.get(e["TPLNR"])
        if not flnode and e["TPLNR"]:
            stats["warnings"].append(f"Equipment {tag or '(no tag)'} references unknown FLOC {e['TPLNR']}")
        used = {x.asset_id for x in h.nodes.values()}
        n = h.add(parent_id=flnode.id if flnode else None, description=e["EQKTX"] or tag or "EQUIPMENT",
                  status="imported", tag_number=tag, catalog_code=e["RBNR"], manufacturer=e["HERST"], model=e["TYPBZ"],
                  serial=e["SERGE"], year=e["BAUJJ"], tann_part_no=e["MAPAR"],
                  asset_id=e["LEGACYKEY"] if e["LEGACYKEY"] and e["LEGACYKEY"] not in used else "")
        if e["LEGACYKEY"]:
            by_key[e["LEGACYKEY"]] = n
        if tag:
            by_tag[tag] = n
        if e["HEQUI"]:
            hequi.append((n, e["HEQUI"]))
        stats["added"] += 1
    for n, ref in hequi:                    # sub-equipment: HEQUI references the parent's tag or legacy key
        parent = by_tag.get(ref) or by_key.get(ref)
        if parent and parent.id != n.id:
            n.parent_id = parent.id
    h.repair()
    return stats
