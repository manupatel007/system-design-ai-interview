from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeVar


class InterviewPlanValidationError(ValueError):
    pass


class InterviewPhase(StrEnum):
    INTRODUCTION = "introduction"
    REQUIREMENTS = "requirements"
    ESTIMATION = "estimation"
    HIGH_LEVEL_DESIGN = "high_level_design"
    DEEP_DIVE = "deep_dive"
    RELIABILITY_SCALE = "reliability_and_scale"
    WRAP_UP = "wrap_up"
    COMPLETE = "complete"


PHASE_SEQUENCE = (
    InterviewPhase.INTRODUCTION,
    InterviewPhase.REQUIREMENTS,
    InterviewPhase.ESTIMATION,
    InterviewPhase.HIGH_LEVEL_DESIGN,
    InterviewPhase.DEEP_DIVE,
    InterviewPhase.RELIABILITY_SCALE,
    InterviewPhase.WRAP_UP,
    InterviewPhase.COMPLETE,
)


class CandidateIntent(StrEnum):
    ANSWER = "answer"
    PARTIAL_ANSWER = "partial_answer"
    CLARIFICATION_REQUEST = "clarification_request"
    META_QUESTION = "meta_question"
    DIAGRAM_QUESTION = "diagram_question"
    DRAWING_EXPLANATION = "drawing_explanation"
    HELP_REQUEST = "help_request"
    UNCERTAIN = "uncertain"
    OFF_TOPIC = "off_topic"
    FINISH_REQUEST = "finish_request"


class InterviewAction(StrEnum):
    ACKNOWLEDGE = "acknowledge"
    PROBE = "probe"
    CLARIFY = "clarify"
    ANSWER_CANDIDATE = "answer_candidate"
    ASSIST = "assist"
    TRANSITION = "transition"
    COMPLETE = "complete"


class AssistancePolicy(StrEnum):
    STRICT = "strict"
    ADAPTIVE = "adaptive"
    GUIDED = "guided"


class AssistanceLevel(StrEnum):
    NUDGE = "nudge"
    CONCEPT = "concept"
    EXAMPLE = "example"
    REFERENCE = "reference"


@dataclass(frozen=True, slots=True)
class AssistanceTurn:
    policy: AssistancePolicy
    level: AssistanceLevel
    request_index: int
    scope_id: str
    topic: str
    object_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "policy": self.policy.value,
            "level": self.level.value,
            "requestIndex": self.request_index,
            "scopeId": self.scope_id,
            "topic": self.topic,
            "objectIds": list(self.object_ids),
        }


class CanvasProposalKind(StrEnum):
    NONE = "none"
    SCOPED = "scoped"
    REFERENCE = "reference_architecture"


class CanvasProposalNodeRole(StrEnum):
    CLIENT = "client"
    CDN = "cdn"
    LOAD_BALANCER = "load_balancer"
    GATEWAY = "gateway"
    SERVICE = "service"
    WORKER = "worker"
    QUEUE = "queue"
    STREAM = "stream"
    CACHE = "cache"
    DATABASE = "database"
    OBJECT_STORAGE = "object_storage"
    SEARCH = "search"
    OBSERVABILITY = "observability"
    EXTERNAL = "external"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class CanvasProposalNode:
    id: str
    label: str
    role: CanvasProposalNodeRole
    layer: int

    @classmethod
    def from_payload(cls, payload: object) -> CanvasProposalNode:
        values = _object(payload, "canvas proposal node")
        _keys(values, {"id", "label", "role", "layer"}, "canvas proposal node")
        return cls(
            id=_proposal_identifier(values.get("id"), "canvas proposal node id"),
            label=_required_string(
                values.get("label"), "canvas proposal node label", maximum=80
            ),
            role=_enum(
                CanvasProposalNodeRole,
                values.get("role"),
                "canvas proposal node role",
            ),
            layer=_bounded_integer(
                values.get("layer"),
                "canvas proposal node layer",
                minimum=0,
                maximum=6,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "role": self.role.value,
            "layer": self.layer,
        }


@dataclass(frozen=True, slots=True)
class CanvasProposalEdge:
    id: str
    label: str
    source_id: str
    target_id: str

    @classmethod
    def from_payload(cls, payload: object) -> CanvasProposalEdge:
        values = _object(payload, "canvas proposal edge")
        _keys(
            values,
            {"id", "label", "sourceId", "targetId"},
            "canvas proposal edge",
        )
        source_id = _proposal_identifier(
            values.get("sourceId"), "canvas proposal edge source id"
        )
        target_id = _proposal_identifier(
            values.get("targetId"), "canvas proposal edge target id"
        )
        if source_id == target_id:
            raise InterviewPlanValidationError(
                "canvas proposal edge endpoints must differ"
            )
        return cls(
            id=_proposal_identifier(values.get("id"), "canvas proposal edge id"),
            label=_string(
                values.get("label"), "canvas proposal edge label", maximum=80
            ),
            source_id=source_id,
            target_id=target_id,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "label": self.label,
            "sourceId": self.source_id,
            "targetId": self.target_id,
        }


@dataclass(frozen=True, slots=True)
class CanvasProposal:
    kind: CanvasProposalKind = CanvasProposalKind.NONE
    title: str = ""
    summary: str = ""
    nodes: tuple[CanvasProposalNode, ...] = ()
    edges: tuple[CanvasProposalEdge, ...] = ()

    @classmethod
    def from_payload(cls, payload: object) -> CanvasProposal:
        values = _object(payload, "canvasProposal")
        _keys(
            values,
            {"kind", "title", "summary", "nodes", "edges"},
            "canvasProposal",
        )
        kind = _enum(
            CanvasProposalKind,
            values.get("kind"),
            "canvas proposal kind",
        )
        title = _string(values.get("title"), "canvas proposal title", maximum=120)
        summary = _string(
            values.get("summary"), "canvas proposal summary", maximum=360
        )
        nodes = tuple(
            CanvasProposalNode.from_payload(item)
            for item in _list(values.get("nodes"), "canvas proposal nodes", maximum=12)
        )
        edges = tuple(
            CanvasProposalEdge.from_payload(item)
            for item in _list(values.get("edges"), "canvas proposal edges", maximum=18)
        )
        identifiers = [item.id for item in (*nodes, *edges)]
        if len(identifiers) != len(set(identifiers)):
            raise InterviewPlanValidationError(
                "canvas proposal entity ids must be unique"
            )
        if kind is CanvasProposalKind.NONE:
            if title or summary or nodes or edges:
                raise InterviewPlanValidationError(
                    "empty canvas proposal must not contain content"
                )
        elif not title:
            raise InterviewPlanValidationError(
                "canvas proposal title is required"
            )
        elif not nodes and not edges:
            raise InterviewPlanValidationError(
                "canvas proposal must contain a node or edge"
            )
        return cls(
            kind=kind,
            title=title,
            summary=summary,
            nodes=nodes,
            edges=edges,
        )

    @property
    def is_empty(self) -> bool:
        return self.kind is CanvasProposalKind.NONE

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "title": self.title,
            "summary": self.summary,
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
        }


class QuestionStatus(StrEnum):
    UNANSWERED = "unanswered"
    PARTIAL = "partial"
    ANSWERED = "answered"
    NOT_APPLICABLE = "not_applicable"


class Competency(StrEnum):
    REQUIREMENTS_SCOPE = "requirements_scope"
    CAPACITY_ESTIMATION = "capacity_estimation"
    API_DATA_MODEL = "api_and_data_model"
    ARCHITECTURE_FLOW = "architecture_and_data_flow"
    SCALABILITY = "scalability_and_bottlenecks"
    RELIABILITY = "reliability_and_failure_recovery"
    CONSISTENCY = "consistency_and_correctness"
    SECURITY_OBSERVABILITY = "security_privacy_and_observability"
    COMMUNICATION_TRADEOFFS = "communication_and_tradeoffs"


COMPETENCY_LABELS = {
    Competency.REQUIREMENTS_SCOPE: "Requirements and scope",
    Competency.CAPACITY_ESTIMATION: "Capacity estimation",
    Competency.API_DATA_MODEL: "API and data model",
    Competency.ARCHITECTURE_FLOW: "Architecture and data flow",
    Competency.SCALABILITY: "Scalability and bottlenecks",
    Competency.RELIABILITY: "Reliability and failure recovery",
    Competency.CONSISTENCY: "Consistency and correctness",
    Competency.SECURITY_OBSERVABILITY: "Security, privacy, and observability",
    Competency.COMMUNICATION_TRADEOFFS: "Communication and trade-offs",
}


class RubricLevel(StrEnum):
    NOT_OBSERVED = "not_observed"
    SOME_EVIDENCE = "some_evidence"
    DEMONSTRATED = "demonstrated"


RUBRIC_LEVEL_ORDER = {
    RubricLevel.NOT_OBSERVED: 0,
    RubricLevel.SOME_EVIDENCE: 1,
    RubricLevel.DEMONSTRATED: 2,
}


class EvidenceSource(StrEnum):
    TRANSCRIPT = "transcript"
    DIAGRAM = "diagram"
    COMBINED = "combined"


class CanvasReferenceKind(StrEnum):
    ISSUE = "issue"
    FOCUS = "focus"
    POSITIVE = "positive"


@dataclass(frozen=True, slots=True)
class CanvasReference:
    kind: CanvasReferenceKind
    label: str
    object_ids: tuple[str, ...]

    @classmethod
    def from_payload(cls, payload: object) -> CanvasReference:
        values = _object(payload, "canvas reference")
        _keys(values, {"kind", "label", "objectIds"}, "canvas reference")
        object_ids = tuple(
            _required_string(item, "canvas reference object id", maximum=120)
            for item in _list(
                values.get("objectIds"), "canvas reference object ids", maximum=8
            )
        )
        if not object_ids:
            raise InterviewPlanValidationError(
                "canvas reference objectIds must not be empty"
            )
        return cls(
            kind=_enum(
                CanvasReferenceKind,
                values.get("kind"),
                "canvas reference kind",
            ),
            label=_required_string(
                values.get("label"), "canvas reference label", maximum=160
            ),
            object_ids=object_ids,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "label": self.label,
            "objectIds": list(self.object_ids),
        }


@dataclass(frozen=True, slots=True)
class QuestionPlan:
    text: str = ""
    topic: str = ""
    expected_evidence: tuple[Competency, ...] = ()

    @classmethod
    def from_payload(cls, payload: object) -> QuestionPlan:
        values = _object(payload, "nextQuestion")
        _keys(values, {"text", "topic", "expectedEvidence"}, "nextQuestion")
        text = _string(values.get("text"), "nextQuestion.text", maximum=320)
        topic = _string(values.get("topic"), "nextQuestion.topic", maximum=80)
        expected_evidence = tuple(
            _enum(Competency, item, "nextQuestion.expectedEvidence")
            for item in _list(
                values.get("expectedEvidence"),
                "nextQuestion.expectedEvidence",
                maximum=4,
            )
        )
        if text and not topic:
            raise InterviewPlanValidationError("nextQuestion.topic is required when text is set")
        return cls(text=text, topic=topic, expected_evidence=expected_evidence)

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "topic": self.topic,
            "expectedEvidence": [item.value for item in self.expected_evidence],
        }


@dataclass(frozen=True, slots=True)
class EvidenceUpdate:
    competency: Competency
    summary: str
    source: EvidenceSource
    object_ids: tuple[str, ...] = ()

    @classmethod
    def from_payload(cls, payload: object) -> EvidenceUpdate:
        values = _object(payload, "evidence update")
        _keys(values, {"competency", "summary", "source", "objectIds"}, "evidence update")
        return cls(
            competency=_enum(Competency, values.get("competency"), "evidence competency"),
            summary=_required_string(values.get("summary"), "evidence summary", maximum=240),
            source=_enum(EvidenceSource, values.get("source"), "evidence source"),
            object_ids=tuple(
                _required_string(item, "evidence object id", maximum=120)
                for item in _list(values.get("objectIds"), "evidence object ids", maximum=12)
            ),
        )


@dataclass(frozen=True, slots=True)
class RubricUpdate:
    competency: Competency
    level: RubricLevel
    rationale: str

    @classmethod
    def from_payload(cls, payload: object) -> RubricUpdate:
        values = _object(payload, "rubric update")
        _keys(values, {"competency", "level", "rationale"}, "rubric update")
        return cls(
            competency=_enum(Competency, values.get("competency"), "rubric competency"),
            level=_enum(RubricLevel, values.get("level"), "rubric level"),
            rationale=_string(values.get("rationale"), "rubric rationale", maximum=240),
        )


@dataclass(frozen=True, slots=True)
class DecisionUpdate:
    topic: str
    choice: str
    rationale: str

    @classmethod
    def from_payload(cls, payload: object) -> DecisionUpdate:
        values = _object(payload, "decision update")
        _keys(values, {"topic", "choice", "rationale"}, "decision update")
        return cls(
            topic=_required_string(values.get("topic"), "decision topic", maximum=80),
            choice=_required_string(values.get("choice"), "decision choice", maximum=160),
            rationale=_string(values.get("rationale"), "decision rationale", maximum=240),
        )

    def to_dict(self) -> dict[str, str]:
        return {"topic": self.topic, "choice": self.choice, "rationale": self.rationale}


@dataclass(frozen=True, slots=True)
class FeedbackPlan:
    summary: str = ""
    strengths: tuple[str, ...] = ()
    improvements: tuple[str, ...] = ()
    not_discussed: tuple[str, ...] = ()

    @classmethod
    def from_payload(cls, payload: object) -> FeedbackPlan:
        values = _object(payload, "finalFeedback")
        _keys(
            values,
            {"summary", "strengths", "improvements", "notDiscussed"},
            "finalFeedback",
        )
        return cls(
            summary=_string(values.get("summary"), "feedback summary", maximum=600),
            strengths=_bounded_strings(values.get("strengths"), "feedback strengths"),
            improvements=_bounded_strings(
                values.get("improvements"), "feedback improvements"
            ),
            not_discussed=_bounded_strings(
                values.get("notDiscussed"), "feedback not discussed"
            ),
        )

    @property
    def is_empty(self) -> bool:
        return not (
            self.summary or self.strengths or self.improvements or self.not_discussed
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "summary": self.summary,
            "strengths": list(self.strengths),
            "improvements": list(self.improvements),
            "notDiscussed": list(self.not_discussed),
        }


@dataclass(frozen=True, slots=True)
class InterviewTurnPlan:
    candidate_intent: CandidateIntent
    action: InterviewAction
    question_status: QuestionStatus
    acknowledgement: str
    utterance: str
    evidence_updates: tuple[EvidenceUpdate, ...]
    rubric_updates: tuple[RubricUpdate, ...]
    assumptions: tuple[str, ...]
    decisions: tuple[DecisionUpdate, ...]
    covered_topics: tuple[str, ...]
    next_phase: InterviewPhase
    next_question: QuestionPlan
    final_feedback: FeedbackPlan
    canvas_references: tuple[CanvasReference, ...] = ()
    canvas_proposal: CanvasProposal = field(default_factory=CanvasProposal)

    def __post_init__(self) -> None:
        if self.utterance.count("?") > 1:
            raise InterviewPlanValidationError(
                "interviewer utterance must contain at most one question"
            )
        if self.next_question.text.count("?") > 1:
            raise InterviewPlanValidationError("nextQuestion must contain at most one question")

    @classmethod
    def from_payload(cls, payload: object) -> InterviewTurnPlan:
        values = _object(payload, "interview plan")
        expected = {
            "candidateIntent",
            "action",
            "questionStatus",
            "acknowledgement",
            "utterance",
            "evidenceUpdates",
            "rubricUpdates",
            "assumptions",
            "decisions",
            "coveredTopics",
            "nextPhase",
            "nextQuestion",
            "finalFeedback",
            "canvasReferences",
            "canvasProposal",
        }
        _keys(values, expected, "interview plan")
        return cls(
            candidate_intent=_enum(
                CandidateIntent, values.get("candidateIntent"), "candidate intent"
            ),
            action=_enum(InterviewAction, values.get("action"), "interview action"),
            question_status=_enum(
                QuestionStatus, values.get("questionStatus"), "question status"
            ),
            acknowledgement=_string(
                values.get("acknowledgement"), "acknowledgement", maximum=320
            ),
            utterance=_required_string(values.get("utterance"), "utterance", maximum=800),
            evidence_updates=tuple(
                EvidenceUpdate.from_payload(item)
                for item in _list(values.get("evidenceUpdates"), "evidenceUpdates", maximum=8)
            ),
            rubric_updates=tuple(
                RubricUpdate.from_payload(item)
                for item in _list(values.get("rubricUpdates"), "rubricUpdates", maximum=8)
            ),
            assumptions=_bounded_strings(values.get("assumptions"), "assumptions"),
            decisions=tuple(
                DecisionUpdate.from_payload(item)
                for item in _list(values.get("decisions"), "decisions", maximum=8)
            ),
            covered_topics=_bounded_strings(
                values.get("coveredTopics"), "coveredTopics", maximum_items=12, maximum=80
            ),
            next_phase=_enum(InterviewPhase, values.get("nextPhase"), "next phase"),
            next_question=QuestionPlan.from_payload(values.get("nextQuestion")),
            final_feedback=FeedbackPlan.from_payload(values.get("finalFeedback")),
            canvas_references=tuple(
                CanvasReference.from_payload(item)
                for item in _list(values.get("canvasReferences"), "canvasReferences", maximum=3)
            ),
            canvas_proposal=CanvasProposal.from_payload(
                values.get("canvasProposal")
            ),
        )


def _string_array_schema(maximum: int, *, max_length: int = 240) -> dict[str, object]:
    return {
        "type": "array",
        "maxItems": maximum,
        "items": {"type": "string", "maxLength": max_length},
    }


INTERVIEW_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidateIntent": {
            "type": "string",
            "enum": [item.value for item in CandidateIntent],
        },
        "action": {"type": "string", "enum": [item.value for item in InterviewAction]},
        "questionStatus": {
            "type": "string",
            "enum": [item.value for item in QuestionStatus],
        },
        "acknowledgement": {"type": "string", "maxLength": 320},
        "utterance": {"type": "string", "minLength": 1, "maxLength": 800},
        "canvasProposal": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": [item.value for item in CanvasProposalKind],
                },
                "title": {"type": "string", "maxLength": 120},
                "summary": {"type": "string", "maxLength": 360},
                "nodes": {
                    "type": "array",
                    "maxItems": 12,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 120,
                            },
                            "label": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 80,
                            },
                            "role": {
                                "type": "string",
                                "enum": [
                                    item.value for item in CanvasProposalNodeRole
                                ],
                            },
                            "layer": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 6,
                            },
                        },
                        "required": ["id", "label", "role", "layer"],
                    },
                },
                "edges": {
                    "type": "array",
                    "maxItems": 18,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 120,
                            },
                            "label": {"type": "string", "maxLength": 80},
                            "sourceId": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 120,
                            },
                            "targetId": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 120,
                            },
                        },
                        "required": ["id", "label", "sourceId", "targetId"],
                    },
                },
            },
            "required": ["kind", "title", "summary", "nodes", "edges"],
        },
        "canvasReferences": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [item.value for item in CanvasReferenceKind],
                    },
                    "label": {"type": "string", "minLength": 1, "maxLength": 160},
                    "objectIds": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "items": {"type": "string", "minLength": 1, "maxLength": 120},
                    },
                },
                "required": ["kind", "label", "objectIds"],
            },
        },
        "evidenceUpdates": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "competency": {
                        "type": "string",
                        "enum": [item.value for item in Competency],
                    },
                    "summary": {"type": "string", "minLength": 1, "maxLength": 240},
                    "source": {
                        "type": "string",
                        "enum": [item.value for item in EvidenceSource],
                    },
                    "objectIds": _string_array_schema(12, max_length=120),
                },
                "required": ["competency", "summary", "source", "objectIds"],
            },
        },
        "rubricUpdates": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "competency": {
                        "type": "string",
                        "enum": [item.value for item in Competency],
                    },
                    "level": {
                        "type": "string",
                        "enum": [item.value for item in RubricLevel],
                    },
                    "rationale": {"type": "string", "maxLength": 240},
                },
                "required": ["competency", "level", "rationale"],
            },
        },
        "assumptions": _string_array_schema(8),
        "decisions": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "topic": {"type": "string", "minLength": 1, "maxLength": 80},
                    "choice": {"type": "string", "minLength": 1, "maxLength": 160},
                    "rationale": {"type": "string", "maxLength": 240},
                },
                "required": ["topic", "choice", "rationale"],
            },
        },
        "coveredTopics": _string_array_schema(12, max_length=80),
        "nextPhase": {"type": "string", "enum": [item.value for item in InterviewPhase]},
        "nextQuestion": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "text": {"type": "string", "maxLength": 320},
                "topic": {"type": "string", "maxLength": 80},
                "expectedEvidence": {
                    "type": "array",
                    "maxItems": 4,
                    "items": {
                        "type": "string",
                        "enum": [item.value for item in Competency],
                    },
                },
            },
            "required": ["text", "topic", "expectedEvidence"],
        },
        "finalFeedback": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string", "maxLength": 600},
                "strengths": _string_array_schema(6),
                "improvements": _string_array_schema(6),
                "notDiscussed": _string_array_schema(6),
            },
            "required": ["summary", "strengths", "improvements", "notDiscussed"],
        },
    },
    "required": [
        "candidateIntent",
        "action",
        "questionStatus",
        "acknowledgement",
        "utterance",
        "canvasReferences",
        "canvasProposal",
        "evidenceUpdates",
        "rubricUpdates",
        "assumptions",
        "decisions",
        "coveredTopics",
        "nextPhase",
        "nextQuestion",
        "finalFeedback",
    ],
}


EnumType = TypeVar("EnumType", bound=StrEnum)


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InterviewPlanValidationError(f"{name} must be an object")
    return value


def _keys(values: dict[str, Any], expected: set[str], name: str) -> None:
    missing = expected - values.keys()
    extra = values.keys() - expected
    if missing:
        raise InterviewPlanValidationError(f"{name} is missing {sorted(missing)[0]}")
    if extra:
        raise InterviewPlanValidationError(f"{name} has unknown field {sorted(extra)[0]}")


def _list(value: object, name: str, *, maximum: int) -> list[object]:
    if not isinstance(value, list):
        raise InterviewPlanValidationError(f"{name} must be an array")
    if len(value) > maximum:
        raise InterviewPlanValidationError(f"{name} exceeds the limit of {maximum}")
    return value


def _bounded_integer(
    value: object,
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InterviewPlanValidationError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise InterviewPlanValidationError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _proposal_identifier(value: object, name: str) -> str:
    normalized = _required_string(value, name, maximum=120)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}", normalized) is None:
        raise InterviewPlanValidationError(
            f"{name} contains unsupported characters"
        )
    return normalized


def _string(value: object, name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise InterviewPlanValidationError(f"{name} must be a string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise InterviewPlanValidationError(f"{name} is too long")
    return normalized


def _required_string(value: object, name: str, *, maximum: int) -> str:
    normalized = _string(value, name, maximum=maximum)
    if not normalized:
        raise InterviewPlanValidationError(f"{name} cannot be empty")
    return normalized


def _bounded_strings(
    value: object,
    name: str,
    *,
    maximum_items: int = 8,
    maximum: int = 240,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            _required_string(item, name, maximum=maximum)
            for item in _list(value, name, maximum=maximum_items)
        )
    )


def _enum(enum_type: type[EnumType], value: object, name: str) -> EnumType:
    if not isinstance(value, str):
        raise InterviewPlanValidationError(f"{name} must be a string")
    try:
        return enum_type(value)
    except ValueError as error:
        raise InterviewPlanValidationError(f"{name} has an unsupported value") from error
