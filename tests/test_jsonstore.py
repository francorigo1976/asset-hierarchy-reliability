from asset_hierarchy import Hierarchy, Project
from asset_hierarchy.jsonstore import JsonStore


def test_roundtrip_and_tombstones(tmp_path):
    h = Hierarchy(Project(site="S", prefix="S"))
    a = h.add(is_area=True, description="Area")
    e = h.add(parent_id=a.id, description="pump")
    st = JsonStore(tmp_path / "s.json")
    st.save(h)
    h2 = JsonStore(tmp_path / "s.json").load(h.project.id)
    assert {n.id for n in h2.nodes.values()} == {a.id, e.id}
    h2.delete(e.id)
    st2 = JsonStore(tmp_path / "s.json")
    st2.save(h2)
    assert set(JsonStore(tmp_path / "s.json").load(h.project.id).nodes) == {a.id}
    assert st2.list_projects() == [(h.project.id, "S")]
