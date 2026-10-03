"""In-memory hierarchy operations (port of the app's tree/FLOC logic)."""
from __future__ import annotations

import re
from typing import Iterable, Optional

from .models import Node, Project

FLOC_SEGMENT_LEN = 4
FLOC_SEGMENT_MAX = 5
FLOC_LABEL_LIMIT = 30
MAX_DEPTH = 50
_VOWELS = set("AEIOU")


class HierarchyError(ValueError):
    pass


def consonant_abbreviation(word: str, target: int) -> str:
    word = word.upper()
    if len(word) <= target:
        return word
    keep = min(3, target - 1)
    out = word[:keep]
    for ch in word[keep:]:
        if len(out) >= target:
            break
        if ch not in _VOWELS:
            out += ch
            break
    return out if len(out) >= target else word[:target]


def derive_floc_code(name: str, description: str, parent_name: str = "") -> str:
    source = (description or name or "").strip()
    if not source:
        return ""
    pn = (parent_name or "").strip()
    if pn and source.lower().startswith(pn.lower()):
        source = re.sub(r"^[\s\-:]+", "", source[len(pn):])
    parts = [p.strip() for p in re.split(r"\s+-\s+", source) if p.strip()]
    meaningful = parts[-1] if parts else source
    tokens = re.findall(r"[A-Za-z0-9]+", meaningful)
    if not tokens:
        return ""
    if len(tokens) == 1 and tokens[0].isdigit():
        return tokens[0][:FLOC_SEGMENT_MAX]
    if len(tokens) == 1 or (len(tokens) == 2 and tokens[1].isdigit()):
        word = tokens[0].upper()
        return word if len(word) <= FLOC_SEGMENT_LEN else consonant_abbreviation(word, FLOC_SEGMENT_LEN)
    first = tokens[0].upper()
    if len(first) >= FLOC_SEGMENT_LEN:
        return consonant_abbreviation(first, FLOC_SEGMENT_LEN)
    initials = "".join(t[0] for t in tokens).upper()[:FLOC_SEGMENT_LEN]
    if len(initials) < FLOC_SEGMENT_LEN and len(tokens[0]) > 1:
        padded = (first[0] + re.sub("[AEIOU]", "", first[1:]))[:FLOC_SEGMENT_LEN]
        if len(padded) > len(initials):
            initials = padded
    return initials


class Hierarchy:
    """Mutable view over one project's nodes. Persist with Store.save(h)."""

    def __init__(self, project: Project, nodes: Iterable[Node] = ()):
        self.project = project
        self.nodes: dict[str, Node] = {n.id: n for n in nodes}
        self.deleted_ids: set[str] = set()   # tombstones recorded this session

    # ---- lookup -------------------------------------------------------
    def get(self, node_id: Optional[str]) -> Optional[Node]:
        return self.nodes.get(node_id) if node_id else None

    def children(self, parent_id: Optional[str]) -> list[Node]:
        kids = [n for n in self.nodes.values() if n.parent_id == parent_id]
        return sorted(kids, key=lambda n: (n.sort_order, n.tag_number or n.name))

    def roots(self) -> list[Node]:
        """Roots include orphans whose parent is missing (never hide nodes)."""
        return sorted((n for n in self.nodes.values() if not n.parent_id or n.parent_id not in self.nodes),
                      key=lambda n: (n.sort_order, n.tag_number or n.name))

    def ordered(self) -> list[Node]:
        out: list[Node] = []

        def walk(pid: Optional[str]) -> None:
            for c in self.children(pid):
                out.append(c)
                walk(c.id)
        walk(None)
        return out

    def descendants(self, node_id: str) -> set[str]:
        found: set[str] = set()
        stack = [node_id]
        while stack:
            cur = stack.pop()
            for n in self.nodes.values():
                if n.parent_id == cur and n.id not in found:
                    found.add(n.id)
                    stack.append(n.id)
        return found

    def is_descendant(self, node_id: str, ancestor_id: str) -> bool:
        cur, hops = self.get(node_id), 0
        while cur and hops <= MAX_DEPTH:
            if cur.id == ancestor_id:
                return True
            cur, hops = self.get(cur.parent_id), hops + 1
        return False

    def ancestor_path(self, node_id: str) -> list[str]:
        parts, seen, cur = [], set(), self.get(node_id)
        while cur and cur.id not in seen and len(seen) <= MAX_DEPTH:
            seen.add(cur.id)
            parts.insert(0, cur.tag_number or cur.name)
            cur = self.get(cur.parent_id)
        return parts

    # ---- numbering ----------------------------------------------------
    def next_sort_order(self, parent_id: Optional[str]) -> int:
        sibs = [n.sort_order for n in self.nodes.values() if n.parent_id == parent_id]
        return (max(sibs) if sibs else 0) + 10

    def next_equipment_asset_id(self, candidate: str = "") -> str:
        used = {n.asset_id for n in self.nodes.values() if n.asset_id}
        if candidate and candidate not in used:
            return candidate
        prefix = self.project.prefix or self.project.site or "AST"
        while True:
            aid = f"{prefix}-{self.project.next_seq:04d}"
            self.project.next_seq += 1
            if aid not in used:
                return aid

    # ---- FLOC labels --------------------------------------------------
    def floc_segment(self, node: Node) -> str:
        explicit = re.sub(r"[^A-Za-z0-9]", "", node.floc_code or "")[:FLOC_SEGMENT_MAX].upper()
        if explicit:
            return explicit
        parent = self.get(node.parent_id)
        return derive_floc_code(node.name, node.description, (parent.name or parent.description) if parent else "")

    def floc_label(self, node: Node) -> str:
        """SAP TPLNR for a FLOC, or the nearest FLOC ancestor's TPLNR for equipment."""
        path, seen, cur = [], set(), node
        while cur and cur.id not in seen and len(seen) <= MAX_DEPTH:
            seen.add(cur.id)
            if cur.is_area:
                path.insert(0, self.floc_segment(cur))
            cur = self.get(cur.parent_id)
        if not path:
            return ""
        return (self.project.prefix or "SITE")[:FLOC_SEGMENT_MAX].upper() + "-" + "-".join(path)

    def unique_floc_code(self, base: str, parent_id: Optional[str], exclude_id: Optional[str] = None) -> str:
        base = (base or "").upper()
        if not base:
            return ""
        used = {self.floc_segment(n) for n in self.nodes.values()
                if n.is_area and n.parent_id == parent_id and n.id != exclude_id}
        if base not in used:
            return base
        stem = re.sub(r"\d+$", "", base)
        for i in range(2, 1000):
            cand = (stem[:FLOC_SEGMENT_MAX - len(str(i))] or base[:FLOC_SEGMENT_MAX - len(str(i))]) + str(i)
            if cand not in used:
                return cand
        return base

    # ---- mutation -----------------------------------------------------
    def add(self, *, parent_id: Optional[str] = None, is_area: bool = False, description: str = "",
            name: Optional[str] = None, **fields) -> Node:
        if parent_id is not None and parent_id not in self.nodes:
            parent_id = None   # never create an orphan
        parent = self.get(parent_id)
        if is_area and parent and not parent.is_area:
            raise HierarchyError("a Functional Location cannot sit under equipment")
        desc = (description or "").strip().upper()
        node = Node(project_id=self.project.id, parent_id=parent_id, is_area=is_area, description=desc,
                    name=((name if name is not None else desc.split("-")[0]).strip()).upper(), **fields)
        node.asset_id = fields.get("asset_id") or (
            self._floc_asset_id() if is_area else self.next_equipment_asset_id())
        node.sort_order = fields.get("sort_order") or self.next_sort_order(parent_id)
        if is_area:
            parent_name = (parent.name or parent.description) if parent else ""
            base = node.floc_code or derive_floc_code(node.name, node.description, parent_name)
            node.floc_code = self.unique_floc_code(base, parent_id)
        self.nodes[node.id] = node
        return node

    def _floc_asset_id(self) -> str:
        aid = f"{self.project.prefix or 'AST'}-{self.project.next_seq:04d}"
        self.project.next_seq += 1
        return aid

    def move(self, node_id: str, new_parent_id: Optional[str]) -> None:
        node = self.get(node_id)
        if not node:
            raise HierarchyError("unknown node")
        if new_parent_id is not None:
            parent = self.get(new_parent_id)
            if not parent:
                raise HierarchyError("unknown parent")
            if new_parent_id == node_id or self.is_descendant(new_parent_id, node_id):
                raise HierarchyError("move would create a cycle")
            if node.is_area and not parent.is_area:
                raise HierarchyError("a Functional Location cannot sit under equipment")
        node.parent_id = new_parent_id
        node.sort_order = self.next_sort_order(new_parent_id)

    def delete(self, node_id: str) -> list[Node]:
        """Delete a node and its subtree; ids are tombstoned so syncs can't resurrect them."""
        if node_id not in self.nodes:
            return []
        ids = {node_id} | self.descendants(node_id)
        removed = [self.nodes.pop(i) for i in ids if i in self.nodes]
        self.deleted_ids |= ids
        return removed

    def renumber(self, parent_id: Optional[str]) -> None:
        for i, n in enumerate(self.children(parent_id), start=1):
            n.sort_order = i * 10

    def repair(self) -> dict[str, str]:
        """Fix self-references, orphans and cycles by promoting offenders to root. Returns {id: reason}."""
        reasons: dict[str, str] = {}
        for n in self.nodes.values():
            if n.parent_id and n.parent_id == n.id:
                n.parent_id, reasons[n.id] = None, "self-reference"
        for n in self.nodes.values():
            if n.parent_id and n.parent_id not in self.nodes:
                n.parent_id, reasons[n.id] = None, "orphan"
        for n in self.nodes.values():
            if not n.parent_id:
                continue
            visited, prev, cur, hops = {n.id}, n, self.get(n.parent_id), 0
            while cur:
                hops += 1
                if cur.id in visited or hops > MAX_DEPTH:
                    prev.parent_id, reasons[prev.id] = None, "cycle"
                    break
                visited.add(cur.id)
                prev, cur = cur, self.get(cur.parent_id)
        return reasons
