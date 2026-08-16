from __future__ import annotations

from collections import deque

import pytest

from voice_interviewer.diagram import DiagramSnapshot
from voice_interviewer.errors import LLMProviderError
from voice_interviewer.interview.engine import StructuredInterviewEngine
from voice_interviewer.interview.models import (
    CandidateIntent,
    Competency,
    DecisionUpdate,
    EvidenceSource,
    EvidenceUpdate,
    FeedbackPlan,
    InterviewAction,
    InterviewPhase,
    InterviewPlanValidationError,
    InterviewTurnPlan,
    QuestionPlan,
    QuestionStatus,
    RubricLevel,
    RubricUpdate,
)
from voice_interviewer.llm.mock import MockInterviewLLM
from voice_interviewer.models import InterviewContext


@pytest.mark.asyncio
async def test_mock_interview_progresses_from_evidence_not_random_questions() -> None:
    engine = StructuredInterviewEngine(MockInterviewLLM())
    engine.configure("Design a URL shortener")

    started = await engine.start(_context())
    requirements = await engine.respond(
        _context(
            "Users create short links, and redirects need low latency and high availability."
        )
    )
    estimation = await engine.respond(
        _context("We expect 10 million redirects daily and about 100 writes per second.")
    )

    assert started.state["phase"] == "requirements"
    assert requirements.state["phase"] == "estimation"
    assert "scope and quality constraints" in requirements.text
    assert estimation.state["phase"] == "high_level_design"
    assert estimation.state["evidenceCount"] == 2
    rubric = {item["competency"]: item for item in estimation.state["rubric"]}
    assert rubric["requirements_scope"]["level"] == "demonstrated"
    assert rubric["capacity_estimation"]["level"] == "some_evidence"


@pytest.mark.asyncio
async def test_irrelevant_answer_keeps_current_thread() -> None:
    engine = StructuredInterviewEngine(MockInterviewLLM())
    engine.configure("Design a URL shortener")
    await engine.start(_context())

    result = await engine.respond(_context("Bananas are my favorite fruit."))

    assert result.state["phase"] == "requirements"
    assert result.state["currentQuestion"]["status"] == "unanswered"
    assert "scope" in result.text.lower()
    assert "database" not in result.text.lower()


@pytest.mark.asyncio
async def test_diagram_visibility_question_is_answered_without_provider_call() -> None:
    planner = ScriptedLLM([_start_plan()])
    engine = StructuredInterviewEngine(planner)
    engine.configure("Design a URL shortener")
    started = await engine.start(_context())
    question_id = started.state["currentQuestion"]["id"]

    result = await engine.respond(
        _context("Can you see my diagram?", diagram=_diagram())
    )

    assert planner.calls == 1
    assert "Yes—I can see API, Redis, PostgreSQL" in result.text
    assert "API connected to Redis" in result.text
    assert result.state["currentQuestion"]["id"] == question_id
    assert engine.state.history[-1].intent is CandidateIntent.DIAGRAM_QUESTION


@pytest.mark.asyncio
async def test_state_tracks_assumptions_decisions_evidence_and_adjacent_phase() -> None:
    planner = ScriptedLLM(
        [
            _start_plan(),
            _plan(
                utterance="That scope is clear. What scale should we support?",
                question_status=QuestionStatus.ANSWERED,
                next_phase=InterviewPhase.ESTIMATION,
                next_question=QuestionPlan(
                    "What scale should we support?",
                    "capacity estimation",
                    (Competency.CAPACITY_ESTIMATION,),
                ),
                evidence_updates=(
                    EvidenceUpdate(
                        Competency.REQUIREMENTS_SCOPE,
                        "Redirects require low latency.",
                        EvidenceSource.TRANSCRIPT,
                    ),
                ),
                rubric_updates=(
                    RubricUpdate(
                        Competency.REQUIREMENTS_SCOPE,
                        RubricLevel.DEMONSTRATED,
                        "Candidate scoped latency.",
                    ),
                ),
                assumptions=("Reads dominate writes",),
                decisions=(
                    DecisionUpdate("retention", "one year", "Matches product policy"),
                ),
                covered_topics=("requirements", "latency"),
            ),
        ]
    )
    engine = StructuredInterviewEngine(planner)
    engine.configure("Design a URL shortener")
    await engine.start(_context())

    result = await engine.respond(_context("Redirects need low latency; reads dominate writes."))

    assert result.state["phase"] == "estimation"
    assert result.state["assumptions"] == ["Reads dominate writes"]
    assert result.state["decisions"][0]["choice"] == "one year"
    assert result.state["coveredTopics"] == [
        "requirements",
        "latency",
        "capacity estimation",
    ]
    assert result.state["evidence"][0]["summary"] == "Redirects require low latency."


@pytest.mark.asyncio
async def test_phase_gate_rejects_unjustified_phase_skip() -> None:
    planner = ScriptedLLM(
        [
            _start_plan(),
            _plan(
                utterance="Let's jump to architecture.",
                next_phase=InterviewPhase.HIGH_LEVEL_DESIGN,
            ),
        ]
    )
    engine = StructuredInterviewEngine(planner)
    engine.configure("Design a URL shortener")
    await engine.start(_context())

    result = await engine.respond(_context("I have not clarified anything yet."))

    assert result.state["phase"] == "requirements"
    assert result.state["phaseHistory"] == ["introduction", "requirements"]


@pytest.mark.asyncio
async def test_diagram_shape_alone_does_not_upgrade_rubric() -> None:
    planner = ScriptedLLM(
        [
            _start_plan(),
            _plan(
                utterance="I see Redis. What scale should we support?",
                question_status=QuestionStatus.ANSWERED,
                next_phase=InterviewPhase.ESTIMATION,
                next_question=QuestionPlan(
                    "What scale should we support?",
                    "capacity estimation",
                    (Competency.CAPACITY_ESTIMATION,),
                ),
                evidence_updates=(
                    EvidenceUpdate(
                        Competency.REQUIREMENTS_SCOPE,
                        "A Redis shape exists on the canvas.",
                        EvidenceSource.DIAGRAM,
                        ("cache",),
                    ),
                ),
                rubric_updates=(
                    RubricUpdate(
                        Competency.REQUIREMENTS_SCOPE,
                        RubricLevel.DEMONSTRATED,
                        "A component was drawn.",
                    ),
                ),
            ),
        ]
    )
    engine = StructuredInterviewEngine(planner)
    engine.configure("Design a URL shortener")
    await engine.start(_context())

    result = await engine.respond(
        _context("I added a box.", diagram=_diagram())
    )

    rubric = {item["competency"]: item for item in result.state["rubric"]}
    assert result.state["evidenceCount"] == 1
    assert rubric["requirements_scope"]["level"] == "not_observed"
    assert result.state["phase"] == "requirements"


def test_plan_rejects_multiple_spoken_questions() -> None:
    with pytest.raises(InterviewPlanValidationError, match="at most one question"):
        _plan(utterance="Why Redis? How will you invalidate it?")


@pytest.mark.asyncio
async def test_provider_failure_does_not_partially_mutate_state() -> None:
    planner = FailsAfterStartLLM()
    engine = StructuredInterviewEngine(planner)
    engine.configure("Design a URL shortener")
    started = await engine.start(_context())
    question_id = started.state["currentQuestion"]["id"]

    with pytest.raises(LLMProviderError, match="invalid plan"):
        await engine.respond(_context("Redirects need low latency."))

    state = engine.state.client_dict()
    assert state["turnIndex"] == 0
    assert state["evidenceCount"] == 0
    assert state["currentQuestion"]["id"] == question_id


@pytest.mark.asyncio
async def test_final_feedback_distinguishes_observed_and_not_discussed() -> None:
    engine = StructuredInterviewEngine(MockInterviewLLM())
    engine.configure("Design a URL shortener")
    await engine.start(_context())
    await engine.respond(
        _context("Users create links, and redirects require low latency and high availability.")
    )

    result = await engine.finalize(_context())

    assert result.state["phase"] == "complete"
    assert result.state["completed"] is True
    assert result.feedback is not None
    assert "Requirements and scope" in result.feedback.strengths
    assert "Capacity estimation" in result.feedback.not_discussed
    assert result.state["currentQuestion"] is None


class ScriptedLLM:
    def __init__(self, plans: list[InterviewTurnPlan]) -> None:
        self.plans = deque(plans)
        self.calls = 0

    async def plan(self, context: InterviewContext) -> InterviewTurnPlan:
        self.calls += 1
        return self.plans.popleft()

    async def respond(self, context: InterviewContext) -> str:
        return (await self.plan(context)).utterance


class FailsAfterStartLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def plan(self, context: InterviewContext) -> InterviewTurnPlan:
        self.calls += 1
        if self.calls == 1:
            return _start_plan()
        raise LLMProviderError("invalid plan")

    async def respond(self, context: InterviewContext) -> str:
        return (await self.plan(context)).utterance


def _context(
    transcript: str = "", *, diagram: DiagramSnapshot | None = None
) -> InterviewContext:
    return InterviewContext(
        session_id="interview-test",
        problem="Design a URL shortener",
        transcript=transcript,
        diagram=diagram,
    )


def _start_plan() -> InterviewTurnPlan:
    return _plan(
        utterance="What requirements would you clarify first?",
        action=InterviewAction.TRANSITION,
        question_status=QuestionStatus.NOT_APPLICABLE,
        next_phase=InterviewPhase.REQUIREMENTS,
        next_question=QuestionPlan(
            "What requirements would you clarify first?",
            "requirements",
            (Competency.REQUIREMENTS_SCOPE,),
        ),
    )


def _plan(
    *,
    utterance: str,
    action: InterviewAction = InterviewAction.PROBE,
    question_status: QuestionStatus = QuestionStatus.UNANSWERED,
    next_phase: InterviewPhase = InterviewPhase.REQUIREMENTS,
    next_question: QuestionPlan | None = None,
    evidence_updates: tuple[EvidenceUpdate, ...] = (),
    rubric_updates: tuple[RubricUpdate, ...] = (),
    assumptions: tuple[str, ...] = (),
    decisions: tuple[DecisionUpdate, ...] = (),
    covered_topics: tuple[str, ...] = (),
) -> InterviewTurnPlan:
    return InterviewTurnPlan(
        candidate_intent=CandidateIntent.ANSWER,
        action=action,
        question_status=question_status,
        acknowledgement="",
        utterance=utterance,
        evidence_updates=evidence_updates,
        rubric_updates=rubric_updates,
        assumptions=assumptions,
        decisions=decisions,
        covered_topics=covered_topics,
        next_phase=next_phase,
        next_question=next_question or QuestionPlan(),
        final_feedback=FeedbackPlan(),
    )


def _diagram() -> DiagramSnapshot:
    return DiagramSnapshot.from_payload(
        {
            "version": 1,
            "revision": 4,
            "nodes": [
                _node("api", "service", "API"),
                _node("cache", "cache", "Redis"),
                _node("db", "database", "PostgreSQL"),
            ],
            "edges": [
                {
                    "id": "api-cache",
                    "shape": "arrow",
                    "label": "lookup",
                    "sourceId": "api",
                    "targetId": "cache",
                    "groupIds": [],
                }
            ],
            "groups": [],
            "selectedObjectIds": ["cache"],
            "delta": {
                "addedIds": ["api", "cache", "db", "api-cache"],
                "updatedIds": [],
                "removedIds": [],
                "summary": "Added API, Redis, and PostgreSQL",
            },
        }
    )


def _node(identifier: str, role: str, label: str) -> dict[str, object]:
    return {
        "id": identifier,
        "shape": "rectangle",
        "role": role,
        "label": label,
        "x": 0,
        "y": 0,
        "width": 160,
        "height": 80,
        "groupIds": [],
    }
