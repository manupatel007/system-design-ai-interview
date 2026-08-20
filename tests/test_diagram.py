from __future__ import annotations

import json

import pytest

from voice_interviewer.diagram import DiagramSnapshot, DiagramValidationError
from voice_interviewer.llm.interviewer import GatewayInterviewLLM
from voice_interviewer.models import InterviewContext


def test_snapshot_validates_and_compacts_scene() -> None:
    snapshot = DiagramSnapshot.from_payload(_snapshot_payload())

    assert snapshot.revision == 4
    assert snapshot.nodes[0].label == "API"
    assert snapshot.edges[0].source_id == "api"
    assert snapshot.delta.summary == "Connected API to PostgreSQL"
    assert snapshot.prompt_dict() == {
        "revision": 4,
        "nodes": [
            {"id": "api", "role": "service", "shape": "rectangle", "label": "API"},
            {
                "id": "db",
                "role": "database",
                "shape": "ellipse",
                "label": "PostgreSQL",
            },
        ],
        "edges": [
            {"id": "api-db", "shape": "arrow", "from": "api", "to": "db", "label": "SQL"}
        ],
        "groups": [{"id": "backend", "members": ["api", "db", "api-db"]}],
        "assistantLayer": {"nodes": [], "edges": []},
        "selectedObjectIds": ["db"],
    }
    assert snapshot.glossary_terms()[:2] == ("PostgreSQL", "database")


def test_interviewer_context_contains_compact_diagram() -> None:
    snapshot = DiagramSnapshot.from_payload(_snapshot_payload())
    context = GatewayInterviewLLM.build_context(
        InterviewContext(session_id="test", transcript="I added the API.", diagram=snapshot)
    )
    payload = json.loads(context.split("\n", 1)[1])

    assert payload["diagramSnapshot"] == snapshot.prompt_dict()
    assert "x" not in payload["diagramSnapshot"]["nodes"][0]
    assert payload["diagramSnapshot"]["edges"][0]["from"] == "api"


def test_snapshot_separates_accepted_assistant_layer() -> None:
    payload = _snapshot_payload()
    payload["assistantLayer"] = {
        "nodes": [
            {
                "id": "ai-lb",
                "shape": "rectangle",
                "role": "load_balancer",
                "label": "Load Balancer",
                "x": 560,
                "y": 40,
                "width": 180,
                "height": 80,
                "groupIds": [],
            }
        ],
        "edges": [
            {
                "id": "ai-api-lb",
                "shape": "arrow",
                "label": "HTTPS",
                "sourceId": "api",
                "targetId": "ai-lb",
                "groupIds": [],
            }
        ],
    }
    payload["selectedObjectIds"] = ["ai-lb"]

    snapshot = DiagramSnapshot.from_payload(payload)

    assert [node.id for node in snapshot.nodes] == ["api", "db"]
    assert [node.id for node in snapshot.assistant_nodes] == ["ai-lb"]
    assert snapshot.all_object_ids == {
        "api",
        "db",
        "api-db",
        "ai-lb",
        "ai-api-lb",
    }
    assert snapshot.candidate_object_ids == {"api", "db", "api-db"}
    assert snapshot.prompt_dict()["assistantLayer"] == {
        "nodes": [
            {
                "id": "ai-lb",
                "role": "load_balancer",
                "shape": "rectangle",
                "label": "Load Balancer",
            }
        ],
        "edges": [
            {
                "id": "ai-api-lb",
                "shape": "arrow",
                "from": "api",
                "to": "ai-lb",
                "label": "HTTPS",
            }
        ],
    }
    assert "Load Balancer" in snapshot.glossary_terms()


def test_candidate_edge_may_connect_to_accepted_assistant_node() -> None:
    payload = _snapshot_payload()
    payload["assistantLayer"] = {
        "nodes": [
            {
                "id": "ai-lb",
                "shape": "rectangle",
                "role": "load_balancer",
                "label": "Load Balancer",
                "x": 560,
                "y": 40,
                "width": 180,
                "height": 80,
                "groupIds": [],
            }
        ],
        "edges": [],
    }
    payload["edges"][0]["targetId"] = "ai-lb"

    snapshot = DiagramSnapshot.from_payload(payload)

    assert snapshot.edges[0].target_id == "ai-lb"


def test_candidate_delta_cannot_claim_assistant_entity() -> None:
    payload = _snapshot_payload()
    payload["assistantLayer"] = {
        "nodes": [
            {
                "id": "ai-lb",
                "shape": "rectangle",
                "role": "load_balancer",
                "label": "Load Balancer",
                "x": 560,
                "y": 40,
                "width": 180,
                "height": 80,
                "groupIds": [],
            }
        ],
        "edges": [],
    }
    payload["delta"]["addedIds"] = ["ai-lb"]

    with pytest.raises(DiagramValidationError, match="unknown current entity"):
        DiagramSnapshot.from_payload(payload)


def test_snapshot_rejects_unknown_edge_endpoint() -> None:
    payload = _snapshot_payload()
    payload["edges"][0]["targetId"] = "missing"

    with pytest.raises(DiagramValidationError, match="unknown node"):
        DiagramSnapshot.from_payload(payload)


def test_snapshot_rejects_duplicate_ids() -> None:
    payload = _snapshot_payload()
    payload["edges"][0]["id"] = "api"

    with pytest.raises(DiagramValidationError, match="unique"):
        DiagramSnapshot.from_payload(payload)


def test_snapshot_rejects_bound_text_selection() -> None:
    payload = _snapshot_payload()
    payload["selectedObjectIds"] = ["db-label"]

    with pytest.raises(DiagramValidationError, match="unknown object"):
        DiagramSnapshot.from_payload(payload)


def test_snapshot_rejects_inconsistent_group_membership() -> None:
    payload = _snapshot_payload()
    payload["groups"][0]["memberIds"].remove("api-db")

    with pytest.raises(DiagramValidationError, match="memberships must agree"):
        DiagramSnapshot.from_payload(payload)


def test_snapshot_rejects_unsupported_version() -> None:
    payload = _snapshot_payload()
    payload["version"] = 2

    with pytest.raises(DiagramValidationError, match="unsupported diagram version"):
        DiagramSnapshot.from_payload(payload)


def test_snapshot_rejects_non_finite_geometry() -> None:
    payload = _snapshot_payload()
    payload["nodes"][0]["x"] = float("nan")

    with pytest.raises(DiagramValidationError, match="must be finite"):
        DiagramSnapshot.from_payload(payload)


def _snapshot_payload() -> dict[str, object]:
    return {
        "version": 1,
        "revision": 4,
        "nodes": [
            {
                "id": "api",
                "shape": "rectangle",
                "role": "service",
                "label": "API",
                "x": 20,
                "y": 40,
                "width": 180,
                "height": 80,
                "groupIds": ["backend"],
            },
            {
                "id": "db",
                "shape": "ellipse",
                "role": "database",
                "label": "PostgreSQL",
                "x": 320,
                "y": 40,
                "width": 180,
                "height": 80,
                "groupIds": ["backend"],
            },
        ],
        "edges": [
            {
                "id": "api-db",
                "shape": "arrow",
                "label": "SQL",
                "sourceId": "api",
                "targetId": "db",
                "groupIds": ["backend"],
            }
        ],
        "groups": [{"id": "backend", "memberIds": ["api", "db", "api-db"]}],
        "selectedObjectIds": ["db"],
        "delta": {
            "addedIds": ["api-db"],
            "updatedIds": [],
            "removedIds": [],
            "summary": "Connected API to PostgreSQL",
        },
    }
