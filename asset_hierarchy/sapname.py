"""Deterministic SAP short-description (<=40, ALL CAPS) generator. Port of generateSapName."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .models import Node

SAP_NAME_MAX = 40

# House abbreviations (subset of the app's frozen dictionary) + client terms.
ABBREV = {
    "PUMP": "PMP", "VALVE": "VLV", "MOTOR": "MTR", "COMPRESSOR": "COMP", "CONVEYOR": "CONV", "GEARBOX": "GBX",
    "BLOWER": "BLWR", "GENERATOR": "GEN", "TRANSFORMER": "XFMR", "TRANSMITTER": "XMTR", "INSTRUMENT": "INST",
    "EXCHANGER": "EXCH", "VESSEL": "VSL", "TANK": "TNK", "BOILER": "BLR", "COOLER": "CLR", "HEATER": "HTR",
    "CONDENSER": "COND", "TOWER": "TWR", "AGITATOR": "AGIT", "FILTER": "FLTR", "STRAINER": "STRN",
    "ACTUATOR": "ACT", "COUPLING": "CPLG", "BEARING": "BRG", "CONTROLLER": "CTLR", "INDICATOR": "IND",
    "GAUGE": "GA", "SENSOR": "SNSR", "DETECTOR": "DET", "SWITCH": "SW", "SWITCHGEAR": "SWGR",
    "PANEL": "PNL", "CENTRIFUGAL": "CENT", "RECIPROCATING": "RECIP", "ROTARY": "ROT", "ELECTRIC": "ELEC",
    "HYDRAULIC": "HYD", "PNEUMATIC": "PNEU", "MECHANICAL": "MECH", "HORIZONTAL": "HORIZ", "VERTICAL": "VERT",
    "PRESSURE": "PRESS", "TEMPERATURE": "TEMP", "LEVEL": "LVL", "FLOW": "FLO", "VIBRATION": "VIB",
    "SAFETY": "SFTY", "RELIEF": "RLF", "ISOLATION": "ISOL", "CONTROL": "CTRL", "CHECK": "CHK", "BUTTERFLY": "BFLY",
    "STAINLESS": "SS", "STEEL": "STL", "EMERGENCY": "EMRG", "STANDBY": "STBY", "SUPPLY": "SPLY", "RETURN": "RTN",
    "DISCHARGE": "DISCH", "SUCTION": "SCTN", "WATER": "WTR", "STEAM": "STM", "CHEMICAL": "CHEM",
    "ASSEMBLY": "ASSY", "SYSTEM": "SYS", "PACKAGE": "PKG", "STATION": "STN", "COOLING": "CLG",
    "HEATING": "HTG", "EXHAUST": "EXH", "NITROGEN": "N2", "OXYGEN": "O2", "HYDROGEN": "H2",
}
CLIENT_ABBR = {
    "STAINLESS STEEL": "SS", "CARBON STEEL": "CS", "ASSEMBLY": "ASSY", "BEARING": "BRG", "DIAMETER": "DIA",
    "DISCHARGE": "DISCH", "FLANGE": "FLG", "FLANGED": "FLGD", "GALVANIZED": "GALV", "HOUSING": "HSNG",
    "INSTRUMENT": "INST", "MAXIMUM": "MAX", "MINIMUM": "MIN", "PRESSURE": "PRESS", "TEMPERATURE": "TEMP",
    "THREADED": "THD", "TUBING": "TBG", "VALVE": "VLV", "CARBON DIOXIDE": "CO2", "CAST IRON": "CI",
    "REVOLUTIONS PER MINUTE": "RPM", "POUNDS PER SQUARE INCH": "PSI", "NATIONAL PIPE THREAD": "NPT",
}
SUSPECT = {"EXTRA HARD PLASTIC W", "MECH STRGTH"}


def _nk(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[-,]", " ", s.upper())).strip()


def _build() -> tuple[dict[str, str], int]:
    merged: dict[str, str] = {}
    for src in (ABBREV, CLIENT_ABBR):      # one word -> one abbreviation, else fail loudly
        for w, a in src.items():
            k = _nk(w)
            if k in merged and merged[k] != a:
                raise ValueError(f"abbreviation conflict for {k}: {merged[k]} vs {a}")
            merged[k] = a
    return merged, max(len(k.split()) for k in merged)


_MERGED, _MAXW = _build()


def _clean(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").replace('"', "''").replace(";", " ")).strip().upper()


@dataclass
class SapName:
    sap_name: str
    sap_name_long: Optional[str]
    needs_review: bool


def is_sap_eligible(node: Node) -> bool:
    return node.is_equipment_record


def generate_sap_name(node: Node) -> Optional[SapName]:
    if not is_sap_eligible(node):
        return None
    desc = (node.description or "").strip()
    tokens = [t for t in re.split(r"[\s,\-]+", (desc or node.name or "").replace('"', "''")) if t]
    out, suspect, i = [], False, 0
    while i < len(tokens):
        if re.search(r"\d", tokens[i]):
            out.append(tokens[i].upper()); i += 1; continue
        for n in range(min(_MAXW, len(tokens) - i), 0, -1):
            key = _nk(" ".join(tokens[i:i + n]))
            if key in _MERGED:
                out.append(_MERGED[key]); suspect |= key in SUSPECT; i += n
                break
        else:
            out.append(tokens[i].upper()); i += 1
    core = " ".join(out).upper()
    mfr, pn = _clean(node.manufacturer), _clean(node.tann_part_no or node.model)
    appendix = " ".join(x for x in (mfr, pn) if x)
    long_parts, name, overflow = [], core, False
    if appendix:
        if mfr and len(core) + 1 + len(appendix) <= SAP_NAME_MAX:
            name = core + " " + appendix
        else:
            long_parts.append(appendix)
    if len(name) > SAP_NAME_MAX:
        overflow = True
        words, kept = name.split(" "), []
        for k, w in enumerate(words):
            if len(" ".join(kept + [w])) <= SAP_NAME_MAX:
                kept.append(w)
            else:
                long_parts.insert(0, " ".join(words[k:]))
                break
        name = " ".join(kept)
    return SapName(name, " ".join(long_parts) or None, suspect or overflow or not desc)


def validate_sap_name(s: str) -> tuple[bool, list[str]]:
    issues = []
    if len(s) > SAP_NAME_MAX:
        issues.append(f"Over 40 chars ({len(s)})")
    if s != s.upper():
        issues.append("Must be ALL CAPS")
    if '"' in s:
        issues.append("No double-quotes — use two single quotes for inches")
    if ";" in s:
        issues.append("No semicolons")
    return (not issues, issues)
