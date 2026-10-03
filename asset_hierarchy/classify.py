"""Structural ZCM classification: first two hyphen segments, then the first segment alone.

Port of the app's CATALOG_LOOKUP (subset; extend CATALOG_LOOKUP as needed).
Entries: key -> (ZCM code, ISA variable, ISA function, differential)."""
from __future__ import annotations

from dataclasses import dataclass

_I = ("", "", False)
CATALOG_LOOKUP: dict[str, tuple[str, str, str, bool]] = {}


def _add(code: str, keys, v: str = "", f: str = "", d: bool = False) -> None:
    for k in keys.split():
        CATALOG_LOOKUP[k] = (code, v, f, d)


# Instruments: transmitters / indicators / switches / elements / controllers
for var, word in (("P", "PRESSURE"), ("T", "TEMPERATURE"), ("L", "LEVEL"), ("F", "FLOW")):
    _add("ZCM0097", f"TRANSMITTER-{word} {word}-TRANSMITTER", var, "T")
    _add("ZCM0053", f"INDICATOR-{word} {word}-INDICATOR {word}-GAUGE GAUGE-{word}", var, "I")
    _add("ZCM0053", f"SWITCH-{word} {word}-SWITCH", var, "S")
    _add("ZCM0025", f"{word}-CONTROLLER CONTROLLER-{word}", var, "C")
_add("ZCM0097", "TEMPERATURE-ELEMENT ELEMENT-TEMPERATURE THERMOCOUPLE THERMOWELL RTD", "T", "E")
_add("ZCM0097", "FLOW-ELEMENT ELEMENT-FLOW ORIFICE-PLATE", "F", "E")
_add("ZCM0097", "TRANSMITTER-VIBRATION", "V", "T")
# Valves
_add("ZCM0009", "VALVE-BALL BALL-VALVE"); _add("ZCM0016", "VALVE-BUTTERFLY BUTTERFLY-VALVE")
_add("ZCM0019", "VALVE-CHECK CHECK-VALVE NON-RETURN NRV"); _add("ZCM0030", "VALVE-DIAPHRAGM DIAPHRAGM-VALVE")
_add("ZCM0045", "VALVE-GATE GATE-VALVE"); _add("ZCM0046", "VALVE-GLOBE GLOBE-VALVE")
_add("ZCM0066", "VALVE-NEEDLE NEEDLE-VALVE"); _add("ZCM0070", "VALVE-PINCH PINCH-VALVE")
_add("ZCM0072", "VALVE-PLUG PLUG-VALVE")
_add("ZCM0076", "VALVE-RELIEF RELIEF-VALVE VALVE-SAFETY SAFETY-VALVE PRESSURE-RELIEF PSV PRV")
_add("ZCM0091", "VALVE-SOLENOID SOLENOID-VALVE"); _add("ZCM0101", "VALVE")
# Pumps / conveyors / heat
_add("ZCM0017", "PUMP-CENTRIFUGAL CENTRIFUGAL-PUMP"); _add("ZCM0077", "PUMP-PC PUMP-MONO PROGRESSIVE-CAVITY")
_add("ZCM0079", "PUMP-RECIPROCATING PUMP-PISTON"); _add("ZCM0083", "PUMP-ROTARY PUMP-GEAR PUMP-LOBE PUMP-SCREW")
_add("ZCM0094", "PUMP-SUMP SUMP-PUMP"); _add("ZCM0099", "PUMP-VACUUM VACUUM-PUMP"); _add("ZCM0060", "PUMP")
_add("ZCM0010", "CONVEYOR-BELT BELT-CONVEYOR"); _add("ZCM0018", "CONVEYOR-CHAIN"); _add("ZCM0086", "CONVEYOR-SCREW")
_add("ZCM0073", "CONVEYOR-PNEUMATIC"); _add("ZCM0026", "CONVEYOR"); _add("ZCM0014", "BUCKET-ELEVATOR")
_add("ZCM0047", "HEAT-EXCHANGER CONDENSER COOLER ECONOMISER"); _add("ZCM0027", "COOLING-TOWER")
_add("ZCM0093", "PRESSURE-VESSEL STORAGE-TANK TANK VESSEL SILO")
# Single-segment fallbacks
for code, keys in {
    "ZCM0001": "ABSORBER", "ZCM0002": "ACCUMULATOR", "ZCM0003": "ACTUATOR", "ZCM0005": "AGITATOR",
    "ZCM0006": "ANALYSER ANALYZER", "ZCM0011": "BLENDER", "ZCM0012": "BLOWER", "ZCM0013": "BOILER",
    "ZCM0020": "CHILLER", "ZCM0022": "COLUMN TOWER", "ZCM0023": "COMPRESSOR", "ZCM0033": "DRYER",
    "ZCM0034": "DUST-COLLECTOR", "ZCM0038": "EXTRUDER", "ZCM0039": "FAN", "ZCM0041": "FILTER SEPARATOR STRAINER",
    "ZCM0044": "FURNACE KILN", "ZCM0049": "HOSE", "ZCM0050": "HVAC AHU", "ZCM0054": "UPS",
    "ZCM0059": "METER", "ZCM0061": "MIXER", "ZCM0063": "MCC", "ZCM0064": "GEARBOX GEAR-REDUCER",
    "ZCM0065": "MOTOR", "ZCM0067": "OVEN", "ZCM0071": "PIPE PIPING", "ZCM0075": "GENERATOR",
    "ZCM0078": "REACTOR", "ZCM0087": "SCRUBBER", "ZCM0095": "SWITCHGEAR BREAKER PANEL",
    "ZCM0098": "TURBINE", "ZCM0104": "SCALE WEIGHING", "ZCM0106": "RTO OXIDIZER OXIDISER",
}.items():
    _add(code, keys)
_add("ZCM0025", "CONTROLLER PLC DCS SCADA CONTROL", "", "C")
_add("ZCM0053", "GAUGE INDICATOR INSTRUMENT SWITCH")
_add("ZCM0097", "TRANSMITTER SENSOR", "", "T")


@dataclass
class Detection:
    catalog_code: str | None = None
    isa_variable: str = ""
    isa_function: str = ""
    isa_differential: bool = False
    needs_review: bool = False
    matched_on: str | None = None
    attempted: str = ""


def auto_detect_catalog(description: str) -> Detection:
    segs = [s for s in (description or "").upper().split("-") if s]
    if not segs:
        return Detection()
    keys = ([f"{segs[0]}-{segs[1]}"] if len(segs) >= 2 else []) + [segs[0]]
    for k in keys:
        if k in CATALOG_LOOKUP:
            code, v, f, d = CATALOG_LOOKUP[k]
            return Detection(code, v, f, d, matched_on=k)
    return Detection(needs_review=True, attempted=" or ".join(keys))


# ZCM profile descriptions (subset) — used for the SAP object type (EQART) column.
ZCM_DESC = {
    "ZCM0001": "Absorber", "ZCM0002": "Accumulator", "ZCM0003": "Actuator", "ZCM0005": "Agitator",
    "ZCM0006": "Analytical Instruments", "ZCM0009": "Valve Ball", "ZCM0010": "Conveyor Belt", "ZCM0011": "Blender",
    "ZCM0012": "Blower", "ZCM0013": "Boiler", "ZCM0014": "Bucket Elevator", "ZCM0016": "Valve Butterfly",
    "ZCM0017": "Pump Centrifugal", "ZCM0018": "Conveyor Chain", "ZCM0019": "Valve Check", "ZCM0020": "Chillers",
    "ZCM0022": "Columns", "ZCM0023": "Compressors", "ZCM0025": "Controls", "ZCM0026": "Conveyor (General)",
    "ZCM0027": "Cooling Towers", "ZCM0030": "Valve Diaphram", "ZCM0033": "Dryers", "ZCM0034": "Dust Collector",
    "ZCM0038": "Extruders", "ZCM0039": "Fans", "ZCM0041": "Filters/Seperators", "ZCM0044": "Furnances/Kilns",
    "ZCM0045": "Valve Gate", "ZCM0046": "Valve Globe", "ZCM0047": "Heat Exchangers", "ZCM0049": "Hoses",
    "ZCM0050": "HVAC", "ZCM0053": "Instrumentation (General)", "ZCM0054": "Inverter Battery",
    "ZCM0059": "Meters (Instruments)", "ZCM0060": "Pump Misc", "ZCM0061": "Mixers",
    "ZCM0063": "Motor Control Centers (MCC's)", "ZCM0064": "Gear Reducer", "ZCM0065": "Motors & Engines",
    "ZCM0066": "Valve Needle", "ZCM0067": "Ovens", "ZCM0070": "Valve Pinch", "ZCM0071": "Piping",
    "ZCM0072": "Valve Plug", "ZCM0073": "Conveyor Pneumatic", "ZCM0075": "Power Generation Equipment",
    "ZCM0076": "Valve Pressure Relief", "ZCM0077": "Pump Progressive Cavity", "ZCM0078": "Reactors",
    "ZCM0079": "Pump Reciprocating", "ZCM0083": "Pump Rotary", "ZCM0086": "Conveyor Screw", "ZCM0087": "Scrubbers",
    "ZCM0091": "Valve Solenoid", "ZCM0093": "Pressure Vessels/Storage Tanks", "ZCM0094": "Pump Sump",
    "ZCM0095": "Switch Gear", "ZCM0097": "Transmitters/Sensors", "ZCM0098": "Turbines", "ZCM0099": "Pump Vacuum",
    "ZCM0101": "Valves (General)", "ZCM0104": "Weighing Systems/Equipment", "ZCM0106": "RTO Oxidizer",
}
