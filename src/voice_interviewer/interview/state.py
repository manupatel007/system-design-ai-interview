from __future__ import annotations

from dataclasses import dataclass, field

from voice_interviewer.interview.models import (
    COMPETENCY_LABELS,
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

    def prompt_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "turnIndex": self.turn_index,
            "phaseTurns": self.phase_turns,
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
