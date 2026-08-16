from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

MAX_NODES = 250
MAX_EDGES = 500
MAX_GROUPS = 100
MAX_LABEL_LENGTH = 240
MAX_IDENTIFIER_LENGTH = 120
MAX_REFERENCES = MAX_NODES + MAX_EDGES + MAX_GROUPS


class DiagramValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DiagramNode:
    id: str
    shape: str
    role: str
    label: str
    x: int
    y: int
    width: int
    height: int
    group_ids: tuple[str, ...] = ()

    @classmethod
    def from_payload(cls, payload: object) -> DiagramNode:
        values = _object(payload, "diagram node")
        return cls(
            id=_identifier(values.get("id"), "node id"),
            shape=_short_string(values.get("shape"), "node shape", fallback="unknown"),
            role=_short_string(values.get("role"), "node role", fallback="component"),
            label=_label(values.get("label")),
            x=_integer(values.get("x"), "node x"),
            y=_integer(values.get("y"), "node y"),
            width=max(0, _integer(values.get("width"), "node width")),
            height=max(0, _integer(values.get("height"), "node height")),
            group_ids=_identifiers(
                values.get("groupIds"), "node group ids", maximum=MAX_GROUPS
            ),
        )

    def prompt_item(self) -> dict[str, str]:
        item = {"id": self.id, "role": self.role, "shape": self.shape}
        if self.label:
            item["label"] = self.label
        return item


@dataclass(frozen=True, slots=True)
class DiagramEdge:
    id: str
    shape: str
    label: str
    source_id: str | None
    target_id: str | None
    group_ids: tuple[str, ...] = ()

    @classmethod
    def from_payload(cls, payload: object) -> DiagramEdge:
        values = _object(payload, "diagram edge")
        return cls(
            id=_identifier(values.get("id"), "edge id"),
            shape=_short_string(values.get("shape"), "edge shape", fallback="arrow"),
            label=_label(values.get("label")),
            source_id=_optional_identifier(values.get("sourceId"), "edge source id"),
            target_id=_optional_identifier(values.get("targetId"), "edge target id"),
            group_ids=_identifiers(
                values.get("groupIds"), "edge group ids", maximum=MAX_GROUPS
            ),
        )

    def prompt_item(self) -> dict[str, str]:
        item = {"id": self.id, "shape": self.shape}
        if self.source_id:
            item["from"] = self.source_id
        if self.target_id:
            item["to"] = self.target_id
        if self.label:
            item["label"] = self.label
        return item


@dataclass(frozen=True, slots=True)
class DiagramGroup:
    id: str
    member_ids: tuple[str, ...]

    @classmethod
    def from_payload(cls, payload: object) -> DiagramGroup:
        values = _object(payload, "diagram group")
        return cls(
            id=_identifier(values.get("id"), "group id"),
            member_ids=_identifiers(
                values.get("memberIds"), "group member ids", maximum=MAX_NODES + MAX_EDGES
            ),
        )


@dataclass(frozen=True, slots=True)
class DiagramDelta:
    added_ids: tuple[str, ...] = ()
    updated_ids: tuple[str, ...] = ()
    removed_ids: tuple[str, ...] = ()
    summary: str = ""

    @classmethod
    def from_payload(cls, payload: object) -> DiagramDelta:
        if payload is None:
            return cls()
        values = _object(payload, "diagram delta")
        return cls(
            added_ids=_identifiers(
                values.get("addedIds"), "delta added ids", maximum=MAX_REFERENCES
            ),
            updated_ids=_identifiers(
                values.get("updatedIds"), "delta updated ids", maximum=MAX_REFERENCES
            ),
            removed_ids=_identifiers(
                values.get("removedIds"), "delta removed ids", maximum=MAX_REFERENCES
            ),
            summary=_label(values.get("summary")),
        )


@dataclass(frozen=True, slots=True)
class DiagramSnapshot:
    version: int
    revision: int
    nodes: tuple[DiagramNode, ...]
    edges: tuple[DiagramEdge, ...]
    groups: tuple[DiagramGroup, ...]
    selected_object_ids: tuple[str, ...]
    delta: DiagramDelta

    @classmethod
    def from_payload(cls, payload: object) -> DiagramSnapshot:
        values = _object(payload, "diagram snapshot")
        version = _integer(values.get("version", 1), "diagram version")
        if version != 1:
            raise DiagramValidationError(f"unsupported diagram version: {version}")
        nodes = tuple(
            DiagramNode.from_payload(item)
            for item in _bounded_list(values.get("nodes"), "nodes", MAX_NODES)
        )
        edges = tuple(
            DiagramEdge.from_payload(item)
            for item in _bounded_list(values.get("edges"), "edges", MAX_EDGES)
        )
        groups = tuple(
            DiagramGroup.from_payload(item)
            for item in _bounded_list(values.get("groups"), "groups", MAX_GROUPS)
        )
        object_ids = [node.id for node in nodes] + [edge.id for edge in edges]
        current_ids = object_ids + [group.id for group in groups]
        if len(current_ids) != len(set(current_ids)):
            raise DiagramValidationError("diagram entity ids must be unique")
        node_ids = {node.id for node in nodes}
        for edge in edges:
            for endpoint in (edge.source_id, edge.target_id):
                if endpoint and endpoint not in node_ids:
                    raise DiagramValidationError(
                        f"edge {edge.id} references unknown node {endpoint}"
                    )
        object_id_set = set(object_ids)
        group_id_set = {group.id for group in groups}
        group_memberships: set[tuple[str, str]] = set()
        for group in groups:
            for member_id in group.member_ids:
                if member_id not in object_id_set:
                    raise DiagramValidationError(
                        f"group {group.id} references unknown object {member_id}"
                    )
                group_memberships.add((group.id, member_id))
        object_memberships: set[tuple[str, str]] = set()
        for diagram_object in (*nodes, *edges):
            for group_id in diagram_object.group_ids:
                if group_id not in group_id_set:
                    raise DiagramValidationError(
                        f"object {diagram_object.id} references unknown group {group_id}"
                    )
                object_memberships.add((group_id, diagram_object.id))
        if group_memberships != object_memberships:
            raise DiagramValidationError("diagram group memberships must agree")
        selected_object_ids = _identifiers(
            values.get("selectedObjectIds"),
            "selected object ids",
            maximum=MAX_NODES + MAX_EDGES,
        )
        unknown_selections = set(selected_object_ids) - object_id_set
        if unknown_selections:
            raise DiagramValidationError(
                f"selection references unknown object {sorted(unknown_selections)[0]}"
            )
        delta = DiagramDelta.from_payload(values.get("delta"))
        current_id_set = set(current_ids)
        for identifier in (*delta.added_ids, *delta.updated_ids):
            if identifier not in current_id_set:
                raise DiagramValidationError(
                    f"diagram delta references unknown current entity {identifier}"
                )
        if current_id_set.intersection(delta.removed_ids):
            raise DiagramValidationError("removed diagram entities must not remain in the snapshot")
        delta_sets = [set(delta.added_ids), set(delta.updated_ids), set(delta.removed_ids)]
        if any(delta_sets[left] & delta_sets[right] for left in range(3) for right in range(left)):
            raise DiagramValidationError("diagram delta categories must be disjoint")
        return cls(
            version=version,
            revision=max(0, _integer(values.get("revision", 0), "diagram revision")),
            nodes=nodes,
            edges=edges,
            groups=groups,
            selected_object_ids=selected_object_ids,
            delta=delta,
        )

    def prompt_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "nodes": [node.prompt_item() for node in self.nodes],
            "edges": [edge.prompt_item() for edge in self.edges],
            "groups": [
                {"id": group.id, "members": list(group.member_ids)} for group in self.groups
            ],
            "selectedObjectIds": list(self.selected_object_ids),
        }

    def glossary_terms(self) -> tuple[str, ...]:
        selected = set(self.selected_object_ids)
        ordered_nodes = sorted(self.nodes, key=lambda node: node.id not in selected)
        terms: list[str] = []
        for node in ordered_nodes:
            if node.label:
                terms.append(node.label)
            if node.role not in {"component", "annotation"}:
                terms.append(node.role.replace("_", " "))
        return tuple(dict.fromkeys(terms))


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DiagramValidationError(f"{name} must be an object")
    return value


def _bounded_list(value: object, name: str, maximum: int) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DiagramValidationError(f"{name} must be an array")
    if len(value) > maximum:
        raise DiagramValidationError(f"{name} exceeds the limit of {maximum}")
    return value


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiagramValidationError(f"{name} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > MAX_IDENTIFIER_LENGTH:
        raise DiagramValidationError(f"{name} is too long")
    return normalized


def _optional_identifier(value: object, name: str) -> str | None:
    return None if value is None else _identifier(value, name)


def _identifiers(value: object, name: str, *, maximum: int) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise DiagramValidationError(f"{name} must be an array")
    if len(value) > maximum:
        raise DiagramValidationError(f"{name} exceeds the limit of {maximum}")
    return tuple(dict.fromkeys(_identifier(item, name) for item in value))


def _short_string(value: object, name: str, *, fallback: str) -> str:
    if value is None:
        return fallback
    if not isinstance(value, str):
        raise DiagramValidationError(f"{name} must be a string")
    normalized = value.strip() or fallback
    if len(normalized) > MAX_IDENTIFIER_LENGTH:
        raise DiagramValidationError(f"{name} is too long")
    return normalized


def _label(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DiagramValidationError("diagram label must be a string")
    return value.strip()[:MAX_LABEL_LENGTH]


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DiagramValidationError(f"{name} must be numeric")
    if isinstance(value, float) and not math.isfinite(value):
        raise DiagramValidationError(f"{name} must be finite")
    return round(value)
