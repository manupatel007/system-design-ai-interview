from __future__ import annotations

from collections import deque

import pytest

from voice_interviewer.diagram import DiagramSnapshot
from voice_interviewer.errors import LLMProviderError
from voice_interviewer.interview.engine import StructuredInterviewEngine
from voice_interviewer.interview.models import (
    AssistanceLevel,
    CandidateIntent,
    CanvasProposal,
    CanvasProposalEdge,
    CanvasProposalKind,
    CanvasProposalNode,
    CanvasProposalNodeRole,
    CanvasReference,
    CanvasReferenceKind,
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
async def test_mock_interviewer_points_to_unlabelled_relationships() -> None:
    engine = StructuredInterviewEngine(MockInterviewLLM())
    engine.configure("Design a URL shortener")
    await engine.start(_context())
    await engine.respond(
        _context(
            "Users create short links, and redirects need low latency and high availability."
        )
    )
    await engine.respond(
        _context("We expect 10 million redirects daily and 100 writes per second.")
    )

    result = await engine.respond(
        _context(
            "The client sends a request to the API, which calls Redis and PostgreSQL.",
            diagram=_diagram(edge_label=""),
        )
    )

    assert result.state["phase"] == "high_level_design"
    assert result.canvas_references[0].object_ids == ("api-cache",)
    assert "highlighted relationships" in result.text


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


@pytest.mark.asyncio
async def test_canvas_references_keep_only_current_diagram_ids() -> None:
    planner = ScriptedLLM(
        [
            _start_plan(),
            _plan(
                utterance="The highlighted relation is not labelled. What does it carry?",
                canvas_references=(
                    CanvasReference(
                        CanvasReferenceKind.ISSUE,
                        "Protocol is not labelled",
                        ("api-cache", "invented-edge", "api-cache"),
                    ),
                    CanvasReference(
                        CanvasReferenceKind.FOCUS,
                        "Unknown target",
                        ("missing",),
                    ),
                ),
            ),
        ]
    )
    engine = StructuredInterviewEngine(planner)
    engine.configure("Design a URL shortener")
    await engine.start(_context())

    result = await engine.respond(
        _context("The API calls Redis.", diagram=_diagram())
    )

    assert len(result.canvas_references) == 1
    assert result.canvas_references[0].object_ids == ("api-cache",)
    assert result.canvas_references[0].label == "Protocol is not labelled"


@pytest.mark.asyncio
async def test_adaptive_help_is_scoped_progressive_and_not_evidence() -> None:
    unsafe_help_plan = _plan(
        utterance="Start with one constraint. What would you try next?",
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
                "Model-supplied help",
                EvidenceSource.TRANSCRIPT,
            ),
        ),
        rubric_updates=(
            RubricUpdate(
                Competency.REQUIREMENTS_SCOPE,
                RubricLevel.DEMONSTRATED,
                "Model supplied the reasoning.",
            ),
        ),
        assumptions=("Assistant supplied this assumption",),
        covered_topics=("assistant coaching",),
    )
    planner = ScriptedLLM(
        [
            _start_plan(),
            unsafe_help_plan,
            _plan(utterance="Use one design principle. How would you apply it?"),
            _plan(utterance="Try one bounded example. How would you adapt it?"),
        ]
    )
    engine = StructuredInterviewEngine(planner)
    engine.configure("Design a URL shortener", "adaptive")
    started = await engine.start(_context())
    question_id = started.state["currentQuestion"]["id"]

    first = await engine.respond(
        _context(
            "I need a hint.",
            diagram=_diagram(),
            selected_object_ids=("cache", "api"),
        )
    )
    second = await engine.respond(
        _context(
            "Can you give me more help?",
            diagram=_diagram(),
            selected_object_ids=("api", "cache"),
        )
    )
    new_scope = await engine.respond(
        _context(
            "Please help me with this part.",
            diagram=_diagram(),
            selected_object_ids=("db",),
        )
    )

    assert first.assistance is not None
    assert second.assistance is not None
    assert new_scope.assistance is not None
    assert first.assistance.level is AssistanceLevel.NUDGE
    assert second.assistance.level is AssistanceLevel.CONCEPT
    assert new_scope.assistance.level is AssistanceLevel.NUDGE
    assert first.assistance.object_ids == ("api", "cache")
    assert first.canvas_references[0].object_ids == ("api", "cache")
    assert first.canvas_references[0].kind is CanvasReferenceKind.FOCUS
    assert first.state["currentQuestion"]["id"] == question_id
    assert second.state["currentQuestion"]["id"] == question_id
    assert new_scope.state["phase"] == "requirements"
    assert new_scope.state["evidenceCount"] == 0
    assert new_scope.state["assumptions"] == []
    assert engine.state.phase_turns == 0
    assert engine.state.history[-1].intent is CandidateIntent.HELP_REQUEST
    assert engine.state.history[-1].action is InterviewAction.ASSIST
    assert [item["requestIndex"] for item in new_scope.state["recentAssistance"]] == [
        1,
        2,
        1,
    ]
    first_help_context = planner.contexts[1]
    assert first_help_context.turn_mode == "help"
    assert first_help_context.runtime_directive["assistance"]["level"] == "nudge"
    assert first_help_context.runtime_directive["assistance"]["objectIds"] == [
        "api",
        "cache",
    ]


@pytest.mark.parametrize(
    ("policy", "expected_levels"),
    [
        ("strict", (AssistanceLevel.NUDGE, AssistanceLevel.NUDGE)),
        ("guided", (AssistanceLevel.CONCEPT, AssistanceLevel.EXAMPLE)),
    ],
)
@pytest.mark.asyncio
async def test_help_policy_controls_disclosure_depth(
    policy: str,
    expected_levels: tuple[AssistanceLevel, AssistanceLevel],
) -> None:
    engine = StructuredInterviewEngine(MockInterviewLLM())
    engine.configure("Design a URL shortener", policy)
    await engine.start(_context())

    first = await engine.respond(
        _context(
            "I want some help.",
            diagram=_diagram(),
            selected_object_ids=("cache",),
        )
    )
    second = await engine.respond(
        _context(
            "Can I have another hint?",
            diagram=_diagram(),
            selected_object_ids=("cache",),
        )
    )

    assert first.assistance is not None
    assert second.assistance is not None
    assert (first.assistance.level, second.assistance.level) == expected_levels
    assert first.canvas_references[0].object_ids == ("cache",)
    assert first.canvas_references[0].kind is CanvasReferenceKind.FOCUS
    assert first.state["assistancePolicy"] == policy
    assert first.state["evidenceCount"] == 0


@pytest.mark.asyncio
async def test_scoped_draw_request_filters_and_bounds_provider_proposal() -> None:
    proposal = CanvasProposal(
        kind=CanvasProposalKind.REFERENCE,
        title="Oversized provider proposal",
        summary="The reducer must constrain this to a scoped addition.",
        nodes=(
            CanvasProposalNode(
                "api",
                "Invented replacement API",
                CanvasProposalNodeRole.SERVICE,
                0,
            ),
            CanvasProposalNode(
                "suggested-cache",
                "Read Cache",
                CanvasProposalNodeRole.CACHE,
                1,
            ),
            CanvasProposalNode(
                "suggested-worker",
                "Async Worker",
                CanvasProposalNodeRole.WORKER,
                2,
            ),
        ),
        edges=(
            CanvasProposalEdge(
                "cache-flow",
                "lookup",
                "cache",
                "suggested-cache",
            ),
            CanvasProposalEdge(
                "missing-flow",
                "invalid",
                "suggested-cache",
                "missing-node",
            ),
            CanvasProposalEdge(
                "worker-flow",
                "async",
                "suggested-cache",
                "suggested-worker",
            ),
        ),
    )
    planner = ScriptedLLM(
        [
            _start_plan(),
            _plan(
                utterance="I've previewed one addition. What would you change?",
                canvas_proposal=proposal,
            ),
        ]
    )
    engine = StructuredInterviewEngine(planner)
    engine.configure("Design a URL shortener", "adaptive")
    started = await engine.start(_context())
    question_id = started.state["currentQuestion"]["id"]

    result = await engine.respond(
        _context(
            "What should I draw here?",
            diagram=_diagram(),
            selected_object_ids=("cache",),
        )
    )

    assert result.canvas_proposal is not None
    assert result.canvas_proposal.kind is CanvasProposalKind.SCOPED
    assert [node.id for node in result.canvas_proposal.nodes] == [
        "suggested-cache"
    ]
    assert [edge.id for edge in result.canvas_proposal.edges] == ["cache-flow"]
    assert result.assistance is not None
    assert result.assistance.level is AssistanceLevel.NUDGE
    assert result.state["currentQuestion"]["id"] == question_id
    assert result.state["canvasProposalCount"] == 1
    assert result.state["evidenceCount"] == 0
    help_context = planner.contexts[1]
    directive = help_context.runtime_directive["canvasProposal"]
    assert directive["kind"] == "scoped"
    assert directive["maxNodes"] == 1
    assert directive["anchorObjectIds"] == ["cache"]


@pytest.mark.asyncio
async def test_mock_canvas_help_builds_on_kept_ai_component() -> None:
    engine = StructuredInterviewEngine(MockInterviewLLM())
    engine.configure("Design a URL shortener", "adaptive")
    await engine.start(_context())

    first = await engine.respond(
        _context(
            "What should I draw here?",
            diagram=_client_only_diagram(),
            selected_object_ids=("client",),
        )
    )
    second = await engine.respond(
        _context(
            "What should I draw next?",
            diagram=_diagram_with_assistant(),
            selected_object_ids=("ai-lb",),
        )
    )

    assert first.canvas_proposal is not None
    assert first.canvas_proposal.nodes[0].role is CanvasProposalNodeRole.LOAD_BALANCER
    assert second.canvas_proposal is not None
    assert second.canvas_proposal.nodes[0].role is CanvasProposalNodeRole.SERVICE
    assert second.canvas_proposal.edges[0].source_id == "ai-lb"


@pytest.mark.asyncio
async def test_scoped_draw_request_can_extend_accepted_ai_layer() -> None:
    proposal = CanvasProposal(
        kind=CanvasProposalKind.SCOPED,
        title="Continue the request path",
        nodes=(
            CanvasProposalNode(
                "suggested-api",
                "Application Service",
                CanvasProposalNodeRole.SERVICE,
                1,
            ),
        ),
        edges=(
            CanvasProposalEdge(
                "lb-api",
                "route",
                "ai-lb",
                "suggested-api",
            ),
        ),
    )
    planner = ScriptedLLM(
        [
            _start_plan(),
            _plan(
                utterance="The request path can continue from the load balancer.",
                canvas_proposal=proposal,
            ),
        ]
    )
    engine = StructuredInterviewEngine(planner)
    engine.configure("Design a URL shortener", "adaptive")
    await engine.start(_context())

    result = await engine.respond(
        _context(
            "What should I draw next?",
            diagram=_diagram_with_assistant(),
            selected_object_ids=("ai-lb",),
        )
    )

    assert result.assistance is not None
    assert result.assistance.object_ids == ("ai-lb",)
    assert result.canvas_proposal is not None
    assert result.canvas_proposal.edges[0].source_id == "ai-lb"
    assert planner.contexts[1].diagram is not None
    assert planner.contexts[1].diagram.prompt_dict()["assistantLayer"]["nodes"][0][
        "id"
    ] == "ai-lb"


@pytest.mark.asyncio
async def test_accepted_ai_layer_cannot_become_candidate_evidence() -> None:
    planner = ScriptedLLM(
        [
            _start_plan(),
            _plan(
                utterance="Please explain your own architecture choices.",
                evidence_updates=(
                    EvidenceUpdate(
                        Competency.ARCHITECTURE_FLOW,
                        "A load balancer is visible.",
                        EvidenceSource.DIAGRAM,
                        ("ai-lb",),
                    ),
                ),
                rubric_updates=(
                    RubricUpdate(
                        Competency.ARCHITECTURE_FLOW,
                        RubricLevel.SOME_EVIDENCE,
                        "The architecture contains a load balancer.",
                    ),
                ),
            ),
        ]
    )
    engine = StructuredInterviewEngine(planner)
    engine.configure("Design a URL shortener")
    await engine.start(_context())

    result = await engine.respond(
        _context(
            "I am still thinking.",
            diagram=_diagram_with_assistant(),
        )
    )

    assert result.state["evidenceCount"] == 0
    architecture = next(
        entry
        for entry in result.state["rubric"]
        if entry["competency"] == "architecture_and_data_flow"
    )
    assert architecture["level"] == "not_observed"


@pytest.mark.asyncio
async def test_explicit_reference_request_returns_complete_mock_architecture() -> None:
    engine = StructuredInterviewEngine(MockInterviewLLM())
    engine.configure("Design a URL shortener", "strict")
    started = await engine.start(_context())
    question_id = started.state["currentQuestion"]["id"]

    result = await engine.respond(
        _context("Show me a complete reference architecture.")
    )

    assert result.assistance is not None
    assert result.assistance.level is AssistanceLevel.REFERENCE
    assert result.canvas_proposal is not None
    assert result.canvas_proposal.kind is CanvasProposalKind.REFERENCE
    assert len(result.canvas_proposal.nodes) == 9
    assert len(result.canvas_proposal.edges) == 9
    assert result.state["currentQuestion"]["id"] == question_id
    assert result.state["phase"] == "requirements"
    assert result.state["canvasProposalCount"] == 1
    assert "not the only correct answer" in result.text


@pytest.mark.asyncio
async def test_unsolicited_canvas_proposal_is_not_emitted_or_remembered() -> None:
    proposal = CanvasProposal(
        kind=CanvasProposalKind.SCOPED,
        title="Unsolicited",
        nodes=(
            CanvasProposalNode(
                "unsolicited-cache",
                "Cache",
                CanvasProposalNodeRole.CACHE,
                1,
            ),
        ),
    )
    planner = ScriptedLLM(
        [
            _start_plan(),
            _plan(
                utterance="Let's continue with requirements.",
                canvas_proposal=proposal,
            ),
        ]
    )
    engine = StructuredInterviewEngine(planner)
    engine.configure("Design a URL shortener")
    await engine.start(_context())

    result = await engine.respond(
        _context("Users need low-latency redirects.")
    )

    assert result.canvas_proposal is None
    assert result.state["canvasProposalCount"] == 0
    assert result.state["recentCanvasProposals"] == []


@pytest.mark.asyncio
async def test_voice_trigger_runs_persistent_guided_takeover_to_completion() -> None:
    engine = StructuredInterviewEngine(MockInterviewLLM())
    engine.configure("Design a URL shortener")
    started = await engine.start(_context())
    question_id = started.state["currentQuestion"]["id"]

    result = await engine.respond(_context("Please walk me through this design step by step."))

    assert result.canvas_proposal is not None
    assert result.canvas_proposal_auto_accept is True
    assert result.state["guidedTakeover"]["active"] is True
    assert result.state["guidedTakeover"]["scoringPaused"] is True
    assert result.state["guidedTakeover"]["currentStep"] == 1
    assert result.state["currentQuestion"]["id"] == question_id
    assert result.state["phase"] == "requirements"
    assert result.state["evidenceCount"] == 0

    for expected_step, command in zip(
        (2, 3, 4),
        ("please continue", "go on", "proceed"),
        strict=True,
    ):
        result = await engine.respond(_context(command))
        assert result.canvas_proposal is not None
        assert result.canvas_proposal_auto_accept is True
        assert result.state["guidedTakeover"]["currentStep"] == expected_step
        assert result.state["currentQuestion"]["id"] == question_id
        assert result.state["evidenceCount"] == 0

    completed = await engine.respond(_context("next step"))

    assert completed.canvas_proposal is None
    assert completed.state["guidedTakeover"]["active"] is False
    assert completed.state["guidedTakeover"]["status"] == "completed"
    assert completed.state["guidedTakeover"]["scoringPaused"] is False
    assert completed.state["currentQuestion"]["id"] == question_id
    assert "explain the request path" in completed.text.lower()


@pytest.mark.asyncio
async def test_guided_explanations_do_not_advance_or_mutate_canvas() -> None:
    engine = StructuredInterviewEngine(MockInterviewLLM())
    engine.configure("Design a URL shortener")
    started = await engine.start(_context())
    question_id = started.state["currentQuestion"]["id"]
    first = await engine.start_guided_takeover(_context())
    proposal_count = first.state["canvasProposalCount"]

    why = await engine.guided_takeover_command(_context(), "why")
    alternative = await engine.guided_takeover_command(_context(), "alternative")
    handed_back = await engine.guided_takeover_command(_context(), "take_back")

    assert why.canvas_proposal is None
    assert alternative.canvas_proposal is None
    assert why.state["guidedTakeover"]["currentStep"] == 1
    assert alternative.state["canvasProposalCount"] == proposal_count
    assert handed_back.state["guidedTakeover"]["active"] is False
    assert handed_back.state["guidedTakeover"]["status"] == "handed_back"
    assert handed_back.state["currentQuestion"]["id"] == question_id
    assert handed_back.state["evidenceCount"] == 0


@pytest.mark.asyncio
async def test_guided_takeover_builds_on_accepted_assistant_layer() -> None:
    engine = StructuredInterviewEngine(MockInterviewLLM())
    engine.configure("Design a URL shortener")
    await engine.start(_context())

    first = await engine.start_guided_takeover(
        _context(
            diagram=_client_only_diagram(),
            selected_object_ids=("client",),
        ),
        scope="selection",
    )
    second = await engine.guided_takeover_command(
        _context(
            diagram=_diagram_with_assistant(),
            selected_object_ids=("ai-lb",),
        ),
        "continue",
    )

    assert first.canvas_proposal is not None
    assert first.canvas_proposal.edges[0].source_id == "client"
    assert second.canvas_proposal is not None
    assert second.canvas_proposal.nodes[0].role is CanvasProposalNodeRole.SERVICE
    assert second.canvas_proposal.edges[0].source_id == "ai-lb"
    assert second.canvas_anchor_ids == ("ai-lb",)


@pytest.mark.asyncio
async def test_guided_takeover_retries_invalid_canvas_proposal_once() -> None:
    planner = ScriptedLLM(
        [
            _start_plan(),
            _plan(utterance="I could not produce the step."),
            _plan(utterance="The retry was also empty."),
        ]
    )
    engine = StructuredInterviewEngine(planner)
    engine.configure("Design a URL shortener")
    await engine.start(_context())

    result = await engine.start_guided_takeover(_context())

    assert planner.calls == 3
    assert result.canvas_proposal is None
    assert result.canvas_proposal_auto_accept is False
    assert result.state["guidedTakeover"]["status"] == "paused"
    assert result.state["guidedTakeover"]["step"]["status"] == "needs_retry"
    assert result.state["guidedTakeover"]["canContinue"] is True
    assert "left the canvas untouched" in result.text


@pytest.mark.asyncio
async def test_guided_takeover_strips_provider_scoring_updates() -> None:
    proposal = CanvasProposal(
        kind=CanvasProposalKind.SCOPED,
        title="Add an ingress",
        nodes=(
            CanvasProposalNode(
                "guided-ingress",
                "Load Balancer",
                CanvasProposalNodeRole.LOAD_BALANCER,
                1,
            ),
        ),
    )
    planner = ScriptedLLM(
        [
            _start_plan(),
            _plan(
                utterance="I added the ingress boundary.",
                action=InterviewAction.TRANSITION,
                question_status=QuestionStatus.ANSWERED,
                next_phase=InterviewPhase.ESTIMATION,
                next_question=QuestionPlan(
                    "What scale should we support?",
                    "capacity estimation",
                    (Competency.CAPACITY_ESTIMATION,),
                ),
                evidence_updates=(
                    EvidenceUpdate(
                        Competency.ARCHITECTURE_FLOW,
                        "The AI added a load balancer.",
                        EvidenceSource.DIAGRAM,
                        ("guided-ingress",),
                    ),
                ),
                rubric_updates=(
                    RubricUpdate(
                        Competency.ARCHITECTURE_FLOW,
                        RubricLevel.DEMONSTRATED,
                        "The diagram has an ingress.",
                    ),
                ),
                assumptions=("Traffic is global",),
                covered_topics=("ingress",),
                canvas_proposal=proposal,
            ),
        ]
    )
    engine = StructuredInterviewEngine(planner)
    engine.configure("Design a URL shortener")
    started = await engine.start(_context())
    question_id = started.state["currentQuestion"]["id"]

    result = await engine.start_guided_takeover(_context())

    assert result.canvas_proposal is not None
    assert result.state["phase"] == "requirements"
    assert result.state["currentQuestion"]["id"] == question_id
    assert result.state["evidenceCount"] == 0
    assert result.state["assumptions"] == []
    assert "ingress" not in result.state["coveredTopics"]
    architecture = next(
        entry
        for entry in result.state["rubric"]
        if entry["competency"] == "architecture_and_data_flow"
    )
    assert architecture["level"] == "not_observed"


@pytest.mark.asyncio
async def test_guided_provider_failure_rolls_back_takeover_state() -> None:
    planner = FailsAfterStartLLM()
    engine = StructuredInterviewEngine(planner)
    engine.configure("Design a URL shortener")
    started = await engine.start(_context())
    question_id = started.state["currentQuestion"]["id"]

    with pytest.raises(LLMProviderError, match="invalid plan"):
        await engine.start_guided_takeover(_context())

    state = engine.state.client_dict()
    assert state["guidedTakeover"]["active"] is False
    assert state["guidedTakeover"]["status"] == "inactive"
    assert state["currentQuestion"]["id"] == question_id
    assert state["evidenceCount"] == 0


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
        self.contexts: list[InterviewContext] = []

    async def plan(self, context: InterviewContext) -> InterviewTurnPlan:
        self.calls += 1
        self.contexts.append(context)
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
    transcript: str = "",
    *,
    diagram: DiagramSnapshot | None = None,
    selected_object_ids: tuple[str, ...] = (),
) -> InterviewContext:
    return InterviewContext(
        session_id="interview-test",
        problem="Design a URL shortener",
        transcript=transcript,
        diagram=diagram,
        selected_object_ids=selected_object_ids,
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
    canvas_references: tuple[CanvasReference, ...] = (),
    canvas_proposal: CanvasProposal | None = None,
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
        canvas_references=canvas_references,
        canvas_proposal=canvas_proposal or CanvasProposal(),
    )


def _diagram(*, edge_label: str = "lookup") -> DiagramSnapshot:
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
                    "label": edge_label,
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


def _client_only_diagram() -> DiagramSnapshot:
    return DiagramSnapshot.from_payload(
        {
            "version": 1,
            "revision": 4,
            "nodes": [_node("client", "client", "Client")],
            "edges": [],
            "groups": [],
            "selectedObjectIds": ["client"],
            "delta": {
                "addedIds": ["client"],
                "updatedIds": [],
                "removedIds": [],
                "summary": "Added Client",
            },
        }
    )


def _diagram_with_assistant() -> DiagramSnapshot:
    payload = {
        "version": 1,
        "revision": 5,
        "nodes": [_node("client", "client", "Client")],
        "edges": [],
        "groups": [],
        "assistantLayer": {
            "nodes": [_node("ai-lb", "load_balancer", "Load Balancer")],
            "edges": [
                {
                    "id": "ai-client-lb",
                    "shape": "arrow",
                    "label": "HTTPS",
                    "sourceId": "client",
                    "targetId": "ai-lb",
                    "groupIds": [],
                }
            ],
        },
        "selectedObjectIds": ["ai-lb"],
        "delta": {
            "addedIds": [],
            "updatedIds": [],
            "removedIds": [],
            "summary": "",
        },
    }
    return DiagramSnapshot.from_payload(payload)


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
