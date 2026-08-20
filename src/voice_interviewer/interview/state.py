from __future__ import annotations

from dataclasses import dataclass, field

from voice_interviewer.interview.models import (
    COMPETENCY_LABELS,
    AssistanceLevel,
    AssistancePolicy,
    AssistanceTurn,
    CandidateIntent,
    Competency,
    DecisionUpdate,
    EvidenceSource,
    FeedbackPlan,
    InterviewAction,
    InterviewPhase,
    QuestionStatus,
    RubricLevel,
)


@dataclass(slots=True)
class EvidenceRecord:
    id: str
    turn: int
    competency: Competency
    summary: str
    source: EvidenceSource
    object_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "turn": self.turn,
            "competency": self.competency.value,
            "summary": self.summary,
            "source": self.source.value,
            "objectIds": list(self.object_ids),
        }


@dataclass(slots=True)
class RubricEntry:
    competency: Competency
    level: RubricLevel = RubricLevel.NOT_OBSERVED
    rationale: str = ""
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "competency": self.competency.value,
            "label": COMPETENCY_LABELS[self.competency],
            "level": self.level.value,
            "rationale": self.rationale,
            "evidenceIds": list(self.evidence_ids),
        }


@dataclass(slots=True)
class QuestionState:
    id: str
    text: str
    topic: str
    expected_evidence: tuple[Competency, ...]
    asked_turn: int
    status: QuestionStatus = QuestionStatus.UNANSWERED

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "text": self.text,
            "topic": self.topic,
            "expectedEvidence": [item.value for item in self.expected_evidence],
            "askedTurn": self.asked_turn,
            "status": self.status.value,
        }


@dataclass(slots=True)
class TurnRecord:
    turn: int
    phase: InterviewPhase
    candidate: str
    interviewer: str
    intent: CandidateIntent
    action: InterviewAction
    question_status: QuestionStatus

    def to_dict(self) -> dict[str, object]:
        return {
            "turn": self.turn,
            "phase": self.phase.value,
            "candidate": self.candidate,
            "interviewer": self.interviewer,
            "intent": self.intent.value,
            "action": self.action.value,
            "questionStatus": self.question_status.value,
        }


def _rubric() -> dict[Competency, RubricEntry]:
    return {item: RubricEntry(competency=item) for item in Competency}


@dataclass(slots=True)
class InterviewState:
    problem: str | None = None
    assistance_policy: AssistancePolicy = AssistancePolicy.ADAPTIVE
    assistance_history: list[AssistanceTurn] = field(default_factory=list)
    _assistance_counts: dict[str, int] = field(default_factory=dict, repr=False)
    phase: InterviewPhase = InterviewPhase.INTRODUCTION
    turn_index: int = 0
    phase_turns: int = 0
    current_question: QuestionState | None = None
    assumptions: list[str] = field(default_factory=list)
    decisions: list[DecisionUpdate] = field(default_factory=list)
    covered_topics: list[str] = field(default_factory=list)
    evidence: list[EvidenceRecord] = field(default_factory=list)
    rubric: dict[Competency, RubricEntry] = field(default_factory=_rubric)
    history: list[TurnRecord] = field(default_factory=list)
    phase_history: list[InterviewPhase] = field(
        default_factory=lambda: [InterviewPhase.INTRODUCTION]
    )
    feedback: FeedbackPlan | None = None
    completed: bool = False

    def preview_assistance(
        self,
        object_ids: tuple[str, ...] = (),
    ) -> AssistanceTurn:
        normalized_ids = tuple(sorted(dict.fromkeys(object_ids)))[:8]
        scope_base = (
            self.current_question.id if self.current_question else self.phase.value
        )
        scope_id = (
            f"{scope_base}:{','.join(normalized_ids)}"
            if normalized_ids
            else scope_base
        )
        request_index = self._assistance_counts.get(scope_id, 0) + 1
        topic = (
            self.current_question.topic
            if self.current_question
            else self.phase.value.replace("_", " ")
        )
        return AssistanceTurn(
            policy=self.assistance_policy,
            level=self._assistance_level(request_index),
            request_index=request_index,
            scope_id=scope_id,
            topic=topic,
            object_ids=normalized_ids,
        )

    def record_assistance(self, assistance: AssistanceTurn) -> None:
        self._assistance_counts[assistance.scope_id] = assistance.request_index
        self.assistance_history.append(assistance)
        if len(self.assistance_history) > 40:
            del self.assistance_history[:-40]
            active_scopes = {
                item.scope_id for item in self.assistance_history
            }
            self._assistance_counts = {
                scope_id: count
                for scope_id, count in self._assistance_counts.items()
                if scope_id in active_scopes
            }

    def _assistance_level(self, request_index: int) -> AssistanceLevel:
        if self.assistance_policy is AssistancePolicy.STRICT:
            return AssistanceLevel.NUDGE
        if self.assistance_policy is AssistancePolicy.GUIDED:
            return (
                AssistanceLevel.CONCEPT
                if request_index == 1
                else AssistanceLevel.EXAMPLE
            )
        if request_index == 1:
            return AssistanceLevel.NUDGE
        if request_index == 2:
            return AssistanceLevel.CONCEPT
        return AssistanceLevel.EXAMPLE

    def prompt_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "turnIndex": self.turn_index,
            "phaseTurns": self.phase_turns,
            "assistancePolicy": self.assistance_policy.value,
            "recentAssistance": [
                item.to_dict() for item in self.assistance_history[-12:]
            ],
            "currentQuestion": (
                self.current_question.to_dict() if self.current_question else None
            ),
            "assumptions": list(self.assumptions),
            "decisions": [item.to_dict() for item in self.decisions],
            "coveredTopics": list(self.covered_topics),
            "rubric": [entry.to_dict() for entry in self.rubric.values()],
            "recentEvidence": [item.to_dict() for item in self.evidence[-12:]],
            "recentTurns": [item.to_dict() for item in self.history[-6:]],
            "phaseHistory": [item.value for item in self.phase_history],
            "completed": self.completed,
        }

    def client_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "turnIndex": self.turn_index,
            "assistancePolicy": self.assistance_policy.value,
            "assistanceCount": len(self.assistance_history),
            "recentAssistance": [
                item.to_dict() for item in self.assistance_history[-12:]
            ],
            "currentQuestion": (
                self.current_question.to_dict() if self.current_question else None
            ),
            "assumptions": list(self.assumptions),
            "decisions": [item.to_dict() for item in self.decisions],
            "coveredTopics": list(self.covered_topics),
            "rubric": [entry.to_dict() for entry in self.rubric.values()],
            "evidence": [item.to_dict() for item in self.evidence[-20:]],
            "evidenceCount": len(self.evidence),
            "phaseHistory": [item.value for item in self.phase_history],
            "completed": self.completed,
            "feedback": self.feedback.to_dict() if self.feedback else None,
        }
