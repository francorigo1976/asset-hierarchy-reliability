import pytest

from asset_hierarchy import (Hierarchy, HierarchyError, Project, Store, auto_detect_catalog, export_nodes,
                             generate_sap_name, preflight, validate_sap_name)
from asset_hierarchy.hierarchy import consonant_abbreviation, derive_floc_code
from data_export import AuditTrail


def make():
    h = Hierarchy(Project(site="ACME", prefix="AP", sap_maint_plant="1000", sap_cost_center="1000100"))
    area = h.add(is_area=True, description="Production")
    sub = h.add(parent_id=area.id, is_area=True, description="Treater 2 - Penthouse")
    eq = h.add(parent_id=sub.id, description="pump-centrifugal-cw", tag_number="p-101", manufacturer="Grundfos", model="CR 15-4")
    return h, area, sub, eq


def test_floc_code_rules():
    assert consonant_abbreviation("PRODUCTION", 4) == "PROD"
    assert consonant_abbreviation("ACCUMULATOR", 4) == "ACCM"
    assert derive_floc_code("", "Treater 2 - Penthouse") == "PENT"
    assert derive_floc_code("", "MID-LINE TENSION CONTROL") == "MLTC"
    assert derive_floc_code("", "Treater 2 Penthouse", "Treater 2") == "PENT"


def test_labels_and_uppercase():
    h, area, sub, eq = make()
    assert eq.description == "PUMP-CENTRIFUGAL-CW"
    assert h.floc_label(sub) == "AP-PROD-PENT" and h.floc_label(eq) == "AP-PROD-PENT"
    assert len(h.floc_label(sub)) <= 30


def test_unique_floc_code_and_sort_order():
    h, area, *_ = make()
    a = h.add(parent_id=area.id, is_area=True, description="Penthouse")
    assert a.floc_code == "PENT2"        # PENT already used by a sibling
    assert [n.sort_order for n in h.children(area.id)] == sorted(n.sort_order for n in h.children(area.id))


def test_floc_cannot_sit_under_equipment_and_no_cycles():
    h, area, sub, eq = make()
    with pytest.raises(HierarchyError):
        h.add(parent_id=eq.id, is_area=True, description="bad")
    with pytest.raises(HierarchyError):
        h.move(area.id, sub.id)
    h.move(eq.id, area.id)
    assert eq.parent_id == area.id


def test_orphan_parent_lands_at_root_and_repair():
    h, area, sub, eq = make()
    assert h.add(parent_id="missing", description="x").parent_id is None
    eq.parent_id = "gone"; area.parent_id = area.id
    sub.parent_id = eq.id; eq.parent_id = sub.id        # 2-cycle
    r = h.repair()
    assert r[area.id] == "self-reference" and not any(n.parent_id == n.id for n in h.nodes.values())
    assert len(h.roots()) >= 1


def test_asset_ids_unique():
    h, *_ = make()
    ids = [n.asset_id for n in h.nodes.values() if not n.is_area]
    assert len(ids) == len(set(ids)) and h.next_equipment_asset_id().startswith("AP-")


def test_delete_tombstones_roundtrip(tmp_path):
    h, area, sub, eq = make()
    s = Store(tmp_path / "db.sqlite"); s.save(h)
    assert len(h.delete(sub.id)) == 2
    s.save(h)
    h2 = s.load(h.project.id)
    assert eq.id not in h2.nodes and area.id in h2.nodes and h2.project.site == "ACME"
    assert s.list_projects() == [(h.project.id, "ACME")]


def test_classification():
    d = auto_detect_catalog("TRANSMITTER-PRESSURE-RTO")
    assert (d.catalog_code, d.isa_variable, d.isa_function) == ("ZCM0097", "P", "T")
    assert auto_detect_catalog("VALVE-BALL-X").catalog_code == "ZCM0009"
    u = auto_detect_catalog("WIDGET-THING")
    assert u.catalog_code is None and u.needs_review and u.attempted == "WIDGET-THING or WIDGET"


def test_sap_name():
    h, _, _, eq = make()
    g = generate_sap_name(eq)
    assert g.sap_name.startswith("PMP CENT CW") and len(g.sap_name) <= 40 and validate_sap_name(g.sap_name)[0]
    assert generate_sap_name(h.roots()[0]) is None          # pure FLOC refused
    assert not validate_sap_name('lower "x"')[0]


def test_export_sap_pm_and_audit(tmp_path):
    h, *_ = make()
    pre = preflight(h, "sap_pm_equipment"); assert pre["ok"], pre
    audit = AuditTrail(tmp_path / "a.jsonl", user="t")
    r1 = export_nodes(h, "sap_pm_functional_location", tmp_path / "fl.xlsx", audit=audit)
    r2 = export_nodes(h, "sap_pm_equipment", tmp_path / "eq.xlsx", audit=audit)
    assert r1.rows == 2 and r2.rows == 1
    assert [e["template"] for e in audit.entries()] == ["sap_pm_functional_location", "sap_pm_equipment"]
    r3 = export_nodes(h, "maximo_asset", tmp_path / "mx.csv", allow_errors=True)   # site=plant mapped
    assert r3.rows == 1
