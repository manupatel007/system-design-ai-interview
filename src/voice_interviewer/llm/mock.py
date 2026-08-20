from __future__ import annotations

import re

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
    InterviewTurnPlan,
    QuestionPlan,
    QuestionStatus,
    RubricLevel,
    RubricUpdate,
)
from voice_interviewer.models import InterviewContext


class MockInterviewLLM:
    async def respond(self, context: InterviewContext) -> str:
        if context.recent_diagram_delta:
            return (
                f"You {context.recent_diagram_delta.rstrip('.').lower()}. "
                "What trade-off led you to that choice?"
            )

        transcript = context.transcript.lower()
        probes = (
            ("cache", "How will you handle stale cache entries and cache failures?"),
            ("queue", "What delivery guarantee does that queue need, and why?"),
            ("database", "What access pattern drove your database choice?"),
            ("shard", "How would you choose and rebalance the shard key?"),
            ("replica", "What consistency behavior do you expect during replica lag?"),
        )
        for keyword, question in probes:
            if keyword in transcript:
                return question
        return "Could you explain the main trade-off behind that decision?"

    async def plan(self, context: InterviewContext) -> InterviewTurnPlan:
        phase = self._phase(context)
        if context.turn_mode == "start":
            return self._plan(
                utterance=(
                    "Let's begin with scope. What functional and non-functional requirements "
                    "would you clarify first?"
                ),
                action=InterviewAction.TRANSITION,
                next_phase=InterviewPhase.REQUIREMENTS,
                next_question=QuestionPlan(
                    text=(
                        "What functional and non-functional requirements would you clarify first?"
                    ),
                    topic="requirements",
                    expected_evidence=(Competency.REQUIREMENTS_SCOPE,),
                ),
            )
        if context.turn_mode == "finalize":
            return self._final_plan(context)
        if context.turn_mode == "help":
            return self._help_plan(context)
        if phase is InterviewPhase.INTRODUCTION:
            return self._plan(
                utterance=(
                    "I have that initial direction. Before we go deeper, what requirements and "
                    "constraints are you designing for?"
                ),
                acknowledgement="I have that initial direction.",
                action=InterviewAction.TRANSITION,
                question_status=QuestionStatus.NOT_APPLICABLE,
                next_phase=InterviewPhase.REQUIREMENTS,
                next_question=QuestionPlan(
                    text="What requirements and constraints are you designing for?",
                    topic="requirements",
                    expected_evidence=(Competency.REQUIREMENTS_SCOPE,),
                ),
            )
        if phase is InterviewPhase.REQUIREMENTS:
            return self._requirements_plan(context)
        if phase is InterviewPhase.ESTIMATION:
            return self._estimation_plan(context)
        if phase is InterviewPhase.HIGH_LEVEL_DESIGN:
            return self._architecture_plan(context)
        if phase is InterviewPhase.DEEP_DIVE:
            return self._deep_dive_plan(context)
        if phase is InterviewPhase.RELIABILITY_SCALE:
            return self._reliability_plan(context)
        return self._wrap_up_plan(context)

    def _help_plan(self, context: InterviewContext) -> InterviewTurnPlan:
        phase = self._phase(context)
        directive = context.runtime_directive.get("assistance", {})
        raw_level = (
            directive.get("level", AssistanceLevel.NUDGE.value)
            if isinstance(directive, dict)
            else AssistanceLevel.NUDGE.value
        )
        try:
            level = AssistanceLevel(str(raw_level))
        except ValueError:
            level = AssistanceLevel.NUDGE
        topic = (
            str(directive.get("topic", "")).strip()
            if isinstance(directive, dict)
            else ""
        ) or phase.value.replace("_", " ")
        focus = {
            InterviewPhase.REQUIREMENTS: (
                "separate one user-visible behavior from one measurable quality constraint"
            ),
            InterviewPhase.ESTIMATION: (
                "turn one dominant volume into peak per-second load and storage"
            ),
            InterviewPhase.HIGH_LEVEL_DESIGN: (
                "trace one request end to end and label every boundary it crosses"
            ),
            InterviewPhase.DEEP_DIVE: (
                "tie the selected component to a workload property and a failure mode"
            ),
            InterviewPhase.RELIABILITY_SCALE: (
                "name the first failure, its detection signal, and its recovery owner"
            ),
            InterviewPhase.WRAP_UP: (
                "rank the largest remaining risk by impact and likelihood"
            ),
        }.get(
            phase,
            "state one design decision and the constraint that drives it",
        )
        examples = {
            InterviewPhase.REQUIREMENTS: (
                "For example, pair a redirect latency target with an availability target"
            ),
            InterviewPhase.ESTIMATION: (
                "For example, convert ten million daily requests to average QPS, then add a "
                "peak multiplier"
            ),
            InterviewPhase.HIGH_LEVEL_DESIGN: (
                "For example, label Client to API as HTTPS and API to Cache as a key lookup"
            ),
            InterviewPhase.DEEP_DIVE: (
                "For example, justify a cache with read dominance and define cache-miss behavior"
            ),
            InterviewPhase.RELIABILITY_SCALE: (
                "For example, detect cache timeouts and define a bounded database fallback"
            ),
            InterviewPhase.WRAP_UP: (
                "For example, prioritize removing a single-region stateful dependency"
            ),
        }
        if level is AssistanceLevel.NUDGE:
            utterance = f"Hint: {focus}. What would you add or change?"
        elif level is AssistanceLevel.CONCEPT:
            utterance = (
                f"A useful method is to {focus}; this keeps the reasoning tied to a "
                f"testable decision. How would you apply it to {topic}?"
            )
        else:
            example = examples.get(
                phase,
                "For example, connect one constraint to one explicit design choice",
            )
            utterance = f"{example}. How would you adapt that pattern to {topic}?"
        raw_object_ids = (
            directive.get("objectIds", []) if isinstance(directive, dict) else []
        )
        object_ids = tuple(
            item for item in raw_object_ids if isinstance(item, str)
        )[:8]
        references = (
            (
                CanvasReference(
                    CanvasReferenceKind.FOCUS,
                    f"{level.value.capitalize()} help requested here",
                    object_ids,
                ),
            )
            if object_ids
            else ()
        )
        canvas_proposal = self._canvas_proposal(context)
        if canvas_proposal.kind is CanvasProposalKind.REFERENCE:
            utterance = (
                "I've placed one illustrative reference architecture beside your work; "
                "it is a comparison aid, not the only correct answer. Which trade-off "
                "would you change first?"
            )
        elif canvas_proposal.kind is CanvasProposalKind.SCOPED:
            if level is AssistanceLevel.NUDGE:
                utterance = (
                    "I've previewed one small possible addition in purple. What would "
                    "you keep or change?"
                )
            elif level is AssistanceLevel.CONCEPT:
                utterance = (
                    "I've previewed an addition that makes one system boundary explicit. "
                    "How would you justify it for this workload?"
                )
            else:
                utterance = (
                    "I've previewed a bounded drawing example beside your design. How "
                    "would you adapt it rather than copy it directly?"
                )
        return self._plan(
            utterance=utterance,
            candidate_intent=CandidateIntent.HELP_REQUEST,
            action=InterviewAction.ASSIST,
            question_status=self._current_question_status(context),
            next_phase=phase,
            canvas_references=references,
            canvas_proposal=canvas_proposal,
        )

    def _canvas_proposal(self, context: InterviewContext) -> CanvasProposal:
        request = context.runtime_directive.get("canvasProposal")
        if not isinstance(request, dict):
            return CanvasProposal()
        try:
            kind = CanvasProposalKind(str(request.get("kind", "")))
        except ValueError:
            return CanvasProposal()
        max_nodes = self._bounded_directive_limit(request.get("maxNodes"), 12)
        max_edges = self._bounded_directive_limit(request.get("maxEdges"), 18)
        if kind is CanvasProposalKind.REFERENCE:
            return self._reference_architecture(max_nodes, max_edges)
        if kind is not CanvasProposalKind.SCOPED:
            return CanvasProposal()
        return self._scoped_canvas_proposal(
            context,
            request,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )

    @staticmethod
    def _bounded_directive_limit(value: object, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            return maximum
        return min(maximum, max(0, value))

    def _scoped_canvas_proposal(
        self,
        context: InterviewContext,
        request: dict[str, object],
        *,
        max_nodes: int,
        max_edges: int,
    ) -> CanvasProposal:
        diagram_nodes = context.diagram.all_nodes if context.diagram else ()
        existing_ids = {node.id for node in diagram_nodes}
        raw_anchors = request.get("anchorObjectIds")
        anchor_ids = tuple(
            item
            for item in raw_anchors
            if isinstance(item, str) and item in existing_ids
        ) if isinstance(raw_anchors, list) else ()
        if len(anchor_ids) >= 2 and max_edges:
            return CanvasProposal(
                kind=CanvasProposalKind.SCOPED,
                title="Connect the selected components",
                summary=(
                    "A labelled request path makes the interaction explicit."
                ),
                edges=(
                    CanvasProposalEdge(
                        id="suggested-request-flow",
                        label="request / response",
                        source_id=anchor_ids[0],
                        target_id=anchor_ids[1],
                    ),
                ),
            )
        existing_roles = {node.role for node in diagram_nodes}
        choices = (
            (
                CanvasProposalNodeRole.LOAD_BALANCER,
                "Load Balancer",
                "HTTPS",
            ),
            (
                CanvasProposalNodeRole.SERVICE,
                "Application Service",
                "route",
            ),
            (
                CanvasProposalNodeRole.CACHE,
                "Read Cache",
                "cache lookup",
            ),
            (
                CanvasProposalNodeRole.DATABASE,
                "Primary Store",
                "read / write",
            ),
            (
                CanvasProposalNodeRole.QUEUE,
                "Event Queue",
                "domain event",
            ),
            (
                CanvasProposalNodeRole.WORKER,
                "Async Worker",
                "consume",
            ),
            (
                CanvasProposalNodeRole.OBSERVABILITY,
                "Metrics and Tracing",
                "telemetry",
            ),
        )
        role, label, edge_label = next(
            (
                candidate
                for candidate in choices
                if candidate[0].value not in existing_roles
            ),
            choices[-1],
        )
        identifier = f"suggested-{role.value.replace('_', '-')}"
        suffix = 2
        while identifier in existing_ids:
            identifier = f"suggested-{role.value.replace('_', '-')}-{suffix}"
            suffix += 1
        nodes = (
            CanvasProposalNode(
                id=identifier,
                label=label,
                role=role,
                layer=1,
            ),
        ) if max_nodes else ()
        anchor_id = anchor_ids[0] if anchor_ids else (
            context.diagram.assistant_nodes[-1].id
            if context.diagram and context.diagram.assistant_nodes
            else (diagram_nodes[0].id if diagram_nodes else None)
        )
        edges = (
            (
                CanvasProposalEdge(
                    id=f"suggested-{role.value}-flow",
                    label=edge_label,
                    source_id=anchor_id,
                    target_id=identifier,
                ),
            )
            if nodes and anchor_id and max_edges
            else ()
        )
        if not nodes and not edges:
            return CanvasProposal()
        return CanvasProposal(
            kind=CanvasProposalKind.SCOPED,
            title=f"Consider adding {label}",
            summary=(
                "A minimal additive suggestion; validate its need and failure mode."
            ),
            nodes=nodes,
            edges=edges,
        )

    @staticmethod
    def _reference_architecture(
        max_nodes: int,
        max_edges: int,
    ) -> CanvasProposal:
        nodes = (
            CanvasProposalNode(
                "reference-client",
                "Web / Mobile Client",
                CanvasProposalNodeRole.CLIENT,
                0,
            ),
            CanvasProposalNode(
                "reference-gateway",
                "API Gateway",
                CanvasProposalNodeRole.GATEWAY,
                1,
            ),
            CanvasProposalNode(
                "reference-create",
                "Short Link Service",
                CanvasProposalNodeRole.SERVICE,
                2,
            ),
            CanvasProposalNode(
                "reference-redirect",
                "Redirect Service",
                CanvasProposalNodeRole.SERVICE,
                2,
            ),
            CanvasProposalNode(
                "reference-cache",
                "Redis Cache",
                CanvasProposalNodeRole.CACHE,
                3,
            ),
            CanvasProposalNode(
                "reference-store",
                "URL Store",
                CanvasProposalNodeRole.DATABASE,
                4,
            ),
            CanvasProposalNode(
                "reference-events",
                "Click Event Queue",
                CanvasProposalNodeRole.QUEUE,
                3,
            ),
            CanvasProposalNode(
                "reference-analytics-worker",
                "Analytics Worker",
                CanvasProposalNodeRole.WORKER,
                4,
            ),
            CanvasProposalNode(
                "reference-analytics-store",
                "Analytics Store",
                CanvasProposalNodeRole.DATABASE,
                5,
            ),
        )[:max_nodes]
        node_ids = {node.id for node in nodes}
        candidate_edges = (
            CanvasProposalEdge(
                "reference-client-gateway",
                "HTTPS",
                "reference-client",
                "reference-gateway",
            ),
            CanvasProposalEdge(
                "reference-gateway-create",
                "create short link",
                "reference-gateway",
                "reference-create",
            ),
            CanvasProposalEdge(
                "reference-gateway-redirect",
                "resolve code",
                "reference-gateway",
                "reference-redirect",
            ),
            CanvasProposalEdge(
                "reference-redirect-cache",
                "cache lookup",
                "reference-redirect",
                "reference-cache",
            ),
            CanvasProposalEdge(
                "reference-redirect-store",
                "cache miss",
                "reference-redirect",
                "reference-store",
            ),
            CanvasProposalEdge(
                "reference-create-store",
                "persist mapping",
                "reference-create",
                "reference-store",
            ),
            CanvasProposalEdge(
                "reference-redirect-events",
                "click event",
                "reference-redirect",
                "reference-events",
            ),
            CanvasProposalEdge(
                "reference-events-worker",
                "consume",
                "reference-events",
                "reference-analytics-worker",
            ),
            CanvasProposalEdge(
                "reference-worker-store",
                "aggregate",
                "reference-analytics-worker",
                "reference-analytics-store",
            ),
        )
        edges = tuple(
            edge
            for edge in candidate_edges
            if edge.source_id in node_ids and edge.target_id in node_ids
        )[:max_edges]
        return CanvasProposal(
            kind=CanvasProposalKind.REFERENCE,
            title="Illustrative URL shortener reference architecture",
            summary=(
                "Separates create, redirect, cache, durable storage, and analytics paths."
            ),
            nodes=nodes,
            edges=edges,
        )

    def _requirements_plan(self, context: InterviewContext) -> InterviewTurnPlan:
        transcript = context.transcript.lower()
        relevant = self._contains(
            transcript,
            "requirement",
            "user",
            "read",
            "write",
            "latency",
            "availability",
            "scope",
            "functional",
        )
        if not relevant:
            return self._plan(
                utterance=(
                    "That does not yet establish the scope. Which user-visible behavior and "
                    "quality constraint should drive this design?"
                ),
                acknowledgement="That does not yet establish the scope.",
                candidate_intent=CandidateIntent.PARTIAL_ANSWER,
                question_status=QuestionStatus.PARTIAL,
                next_phase=InterviewPhase.REQUIREMENTS,
                next_question=QuestionPlan(
                    text=(
                        "Which user-visible behavior and quality constraint should drive "
                        "this design?"
                    ),
                    topic="requirements",
                    expected_evidence=(Competency.REQUIREMENTS_SCOPE,),
                ),
            )
        return self._plan(
            utterance=(
                "Good—you identified concrete scope and quality constraints. What traffic or "
                "storage scale should the design support?"
            ),
            acknowledgement="You identified concrete scope and quality constraints.",
            question_status=QuestionStatus.ANSWERED,
            next_phase=InterviewPhase.ESTIMATION,
            next_question=QuestionPlan(
                text="What traffic or storage scale should the design support?",
                topic="capacity estimation",
                expected_evidence=(Competency.CAPACITY_ESTIMATION,),
            ),
            evidence=(
                EvidenceUpdate(
                    Competency.REQUIREMENTS_SCOPE,
                    context.transcript.strip(),
                    EvidenceSource.TRANSCRIPT,
                ),
            ),
            rubric=(
                RubricUpdate(
                    Competency.REQUIREMENTS_SCOPE,
                    RubricLevel.DEMONSTRATED,
                    "Candidate stated concrete scope or quality constraints.",
                ),
            ),
            topics=("requirements",),
        )

    def _estimation_plan(self, context: InterviewContext) -> InterviewTurnPlan:
        relevant = bool(re.search(r"\d", context.transcript)) or self._contains(
            context.transcript.lower(), "qps", "traffic", "storage", "million", "daily"
        )
        if not relevant:
            return self._plan(
                utterance=(
                    "I do not yet have a scale assumption. Give me one rough traffic or storage "
                    "estimate and explain which design choice it affects."
                ),
                candidate_intent=CandidateIntent.PARTIAL_ANSWER,
                question_status=QuestionStatus.PARTIAL,
                next_phase=InterviewPhase.ESTIMATION,
                next_question=QuestionPlan(
                    text=(
                        "What rough traffic or storage estimate affects your design most?"
                    ),
                    topic="capacity estimation",
                    expected_evidence=(Competency.CAPACITY_ESTIMATION,),
                ),
            )
        return self._plan(
            utterance=(
                "That gives us a useful scale assumption. Walk me through the main components "
                "and the end-to-end request flow."
            ),
            acknowledgement="That gives us a useful scale assumption.",
            question_status=QuestionStatus.ANSWERED,
            next_phase=InterviewPhase.HIGH_LEVEL_DESIGN,
            next_question=QuestionPlan(
                text="What are the main components and the end-to-end request flow?",
                topic="high-level architecture",
                expected_evidence=(Competency.ARCHITECTURE_FLOW,),
            ),
            evidence=(
                EvidenceUpdate(
                    Competency.CAPACITY_ESTIMATION,
                    context.transcript.strip(),
                    EvidenceSource.TRANSCRIPT,
                ),
            ),
            rubric=(
                RubricUpdate(
                    Competency.CAPACITY_ESTIMATION,
                    RubricLevel.SOME_EVIDENCE,
                    "Candidate supplied a quantitative scale assumption.",
                ),
            ),
            assumptions=(context.transcript.strip(),),
            topics=("capacity estimation",),
        )

    def _architecture_plan(self, context: InterviewContext) -> InterviewTurnPlan:
        object_ids = tuple(node.id for node in context.diagram.nodes[:4]) if context.diagram else ()
        spoken_architecture = self._contains(
            context.transcript.lower(),
            "api",
            "service",
            "database",
            "cache",
            "queue",
            "client",
            "request",
            "flow",
        )
        if not spoken_architecture:
            return self._plan(
                utterance=(
                    "I can see the drawing, but I still need your explanation of the flow. "
                    "Which component receives "
                    "the request, and where does the data go next?"
                ),
                candidate_intent=CandidateIntent.PARTIAL_ANSWER,
                question_status=QuestionStatus.PARTIAL,
                next_phase=InterviewPhase.HIGH_LEVEL_DESIGN,
                next_question=QuestionPlan(
                    text="Which component receives the request, and where does data go next?",
                    topic="high-level architecture",
                    expected_evidence=(Competency.ARCHITECTURE_FLOW,),
                ),
            )
        unlabeled_edges = (
            tuple(edge for edge in context.diagram.edges if not edge.label)[:2]
            if context.diagram
            else ()
        )
        if unlabeled_edges:
            return self._plan(
                utterance=(
                    "I can follow the components, but the highlighted relationships are not "
                    "labelled, so their protocol or purpose is unclear. What does each "
                    "interaction represent?"
                ),
                candidate_intent=CandidateIntent.PARTIAL_ANSWER,
                question_status=QuestionStatus.PARTIAL,
                next_phase=InterviewPhase.HIGH_LEVEL_DESIGN,
                next_question=QuestionPlan(
                    text="What does each highlighted interaction represent?",
                    topic="high-level architecture",
                    expected_evidence=(Competency.ARCHITECTURE_FLOW,),
                ),
                canvas_references=tuple(
                    CanvasReference(
                        CanvasReferenceKind.ISSUE,
                        "Relationship lacks a protocol or purpose",
                        (edge.id,),
                    )
                    for edge in unlabeled_edges
                ),
            )
        source = EvidenceSource.COMBINED if object_ids else EvidenceSource.TRANSCRIPT
        return self._plan(
            utterance=(
                "I can follow that request path. Choose one important component and explain why "
                "it is the right boundary or technology for this workload."
            ),
            acknowledgement="I can follow that request path.",
            question_status=QuestionStatus.ANSWERED,
            next_phase=InterviewPhase.DEEP_DIVE,
            next_question=QuestionPlan(
                text=(
                    "Why is one important component the right boundary or technology here?"
                ),
                topic="component trade-off",
                expected_evidence=(
                    Competency.API_DATA_MODEL,
                    Competency.COMMUNICATION_TRADEOFFS,
                ),
            ),
            evidence=(
                EvidenceUpdate(
                    Competency.ARCHITECTURE_FLOW,
                    "Candidate described the major request path and components.",
                    source,
                    object_ids,
                ),
            ),
            rubric=(
                RubricUpdate(
                    Competency.ARCHITECTURE_FLOW,
                    RubricLevel.DEMONSTRATED,
                    "Major components and data flow were established.",
                ),
            ),
            topics=("high-level architecture", "data flow"),
        )

    def _deep_dive_plan(self, context: InterviewContext) -> InterviewTurnPlan:
        transcript = context.transcript.lower()
        relevant = self._contains(
            transcript,
            "because",
            "choose",
            "fits",
            "latency",
            "throughput",
            "schema",
            "consistent",
            "cost",
            "cache",
            "database",
            "api",
            "queue",
        )
        if not relevant:
            return self._plan(
                utterance=(
                    "I heard the choice, but not the reasoning behind it. Which workload property "
                    "made that component or technology a good fit?"
                ),
                candidate_intent=CandidateIntent.PARTIAL_ANSWER,
                question_status=QuestionStatus.PARTIAL,
                next_phase=InterviewPhase.DEEP_DIVE,
                next_question=QuestionPlan(
                    text="Which workload property made that component or technology a good fit?",
                    topic="component trade-off",
                    expected_evidence=(Competency.COMMUNICATION_TRADEOFFS,),
                ),
            )
        competency = (
            Competency.CONSISTENCY
            if self._contains(transcript, "consistent", "stale", "replica")
            else Competency.API_DATA_MODEL
        )
        return self._plan(
            utterance=(
                "That rationale connects the component to the workload. What failure or overload "
                "scenario would you handle first?"
            ),
            acknowledgement="That rationale connects the component to the workload.",
            question_status=QuestionStatus.ANSWERED,
            next_phase=InterviewPhase.RELIABILITY_SCALE,
            next_question=QuestionPlan(
                text="What failure or overload scenario would you handle first?",
                topic="reliability",
                expected_evidence=(Competency.RELIABILITY, Competency.SCALABILITY),
            ),
            evidence=(
                EvidenceUpdate(
                    competency,
                    context.transcript.strip(),
                    EvidenceSource.TRANSCRIPT,
                ),
                EvidenceUpdate(
                    Competency.COMMUNICATION_TRADEOFFS,
                    "Candidate explained a component rationale.",
                    EvidenceSource.TRANSCRIPT,
                ),
            ),
            rubric=(
                RubricUpdate(
                    competency,
                    RubricLevel.SOME_EVIDENCE,
                    "Candidate explained a design detail and rationale.",
                ),
            ),
            topics=("component trade-off",),
        )

    def _reliability_plan(self, context: InterviewContext) -> InterviewTurnPlan:
        relevant = self._contains(
            context.transcript.lower(),
            "fail",
            "retry",
            "replica",
            "fallback",
            "timeout",
            "overload",
            "rate limit",
            "circuit",
            "redundan",
            "recover",
            "backup",
        )
        if not relevant:
            return self._plan(
                utterance=(
                    "That does not yet describe failure handling. What breaks first, how is it "
                    "detected, and how does the system recover?"
                ),
                candidate_intent=CandidateIntent.PARTIAL_ANSWER,
                question_status=QuestionStatus.PARTIAL,
                next_phase=InterviewPhase.RELIABILITY_SCALE,
                next_question=QuestionPlan(
                    text="What breaks first, how is it detected, and how does the system recover?",
                    topic="reliability",
                    expected_evidence=(Competency.RELIABILITY,),
                ),
            )
        return self._plan(
            utterance=(
                "You identified a concrete failure path and response. Before we finish, what is "
                "the most important improvement or unresolved trade-off in your design?"
            ),
            acknowledgement="You identified a concrete failure path and response.",
            question_status=QuestionStatus.ANSWERED,
            next_phase=InterviewPhase.WRAP_UP,
            next_question=QuestionPlan(
                text=(
                    "What is the most important improvement or unresolved trade-off?"
                ),
                topic="wrap-up",
                expected_evidence=(Competency.COMMUNICATION_TRADEOFFS,),
            ),
            evidence=(
                EvidenceUpdate(
                    Competency.RELIABILITY,
                    context.transcript.strip(),
                    EvidenceSource.TRANSCRIPT,
                ),
            ),
            rubric=(
                RubricUpdate(
                    Competency.RELIABILITY,
                    RubricLevel.SOME_EVIDENCE,
                    "Candidate discussed a failure or overload response.",
                ),
            ),
            topics=("reliability", "failure recovery"),
        )

    def _wrap_up_plan(self, context: InterviewContext) -> InterviewTurnPlan:
        relevant = self._contains(
            context.transcript.lower(),
            "improve",
            "trade",
            "bottleneck",
            "risk",
            "monitor",
            "next",
            "with more time",
        )
        if not relevant:
            return self._plan(
                utterance=(
                    "I do not yet have your final prioritization. What is the most important "
                    "improvement or unresolved trade-off?"
                ),
                candidate_intent=CandidateIntent.PARTIAL_ANSWER,
                question_status=QuestionStatus.PARTIAL,
                next_phase=InterviewPhase.WRAP_UP,
                next_question=QuestionPlan(
                    text="What is the most important improvement or unresolved trade-off?",
                    topic="wrap-up",
                    expected_evidence=(Competency.COMMUNICATION_TRADEOFFS,),
                ),
            )
        return self._plan(
            utterance=(
                "That is a clear prioritization of the remaining trade-off. When you are ready, "
                "use Finish interview for an evidence-backed summary."
            ),
            acknowledgement="That is a clear prioritization of the remaining trade-off.",
            question_status=QuestionStatus.ANSWERED,
            next_phase=InterviewPhase.WRAP_UP,
            evidence=(
                EvidenceUpdate(
                    Competency.COMMUNICATION_TRADEOFFS,
                    context.transcript.strip(),
                    EvidenceSource.TRANSCRIPT,
                ),
            ),
            rubric=(
                RubricUpdate(
                    Competency.COMMUNICATION_TRADEOFFS,
                    RubricLevel.DEMONSTRATED,
                    "Candidate prioritized an improvement or unresolved trade-off.",
                ),
            ),
            topics=("wrap-up",),
        )

    def _final_plan(self, context: InterviewContext) -> InterviewTurnPlan:
        rubric = context.interview_state.get("rubric", [])
        observed = [
            item.get("label", "")
            for item in rubric
            if isinstance(item, dict) and item.get("level") != "not_observed"
        ]
        missing = [
            item.get("label", "")
            for item in rubric
            if isinstance(item, dict) and item.get("level") == "not_observed"
        ]
        feedback = FeedbackPlan(
            summary=(
                "You established a traceable design direction. The detailed feedback separates "
                "demonstrated evidence from topics we did not reach."
            ),
            strengths=tuple(item for item in observed[:3] if item),
            improvements=tuple(
                f"Make the trade-offs for {item.lower()} explicit"
                for item in missing[:3]
                if item
            ),
            not_discussed=tuple(item for item in missing[:6] if item),
        )
        return self._plan(
            utterance=(
                "Thanks—that completes the interview. I have prepared feedback grounded in the "
                "reasoning and diagram evidence we actually covered."
            ),
            candidate_intent=CandidateIntent.FINISH_REQUEST,
            action=InterviewAction.COMPLETE,
            question_status=QuestionStatus.NOT_APPLICABLE,
            next_phase=InterviewPhase.COMPLETE,
            feedback=feedback,
        )

    @staticmethod
    def _current_question_status(context: InterviewContext) -> QuestionStatus:
        question = context.interview_state.get("currentQuestion")
        raw_status = question.get("status") if isinstance(question, dict) else None
        try:
            return QuestionStatus(str(raw_status))
        except ValueError:
            return QuestionStatus.NOT_APPLICABLE

    @staticmethod
    def _phase(context: InterviewContext) -> InterviewPhase:
        raw_phase = context.interview_state.get("phase", InterviewPhase.INTRODUCTION.value)
        try:
            return InterviewPhase(str(raw_phase))
        except ValueError:
            return InterviewPhase.INTRODUCTION

    @staticmethod
    def _contains(text: str, *keywords: str) -> bool:
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _plan(
        *,
        utterance: str,
        acknowledgement: str = "",
        candidate_intent: CandidateIntent = CandidateIntent.ANSWER,
        action: InterviewAction = InterviewAction.PROBE,
        question_status: QuestionStatus = QuestionStatus.UNANSWERED,
        next_phase: InterviewPhase = InterviewPhase.INTRODUCTION,
        next_question: QuestionPlan | None = None,
        evidence: tuple[EvidenceUpdate, ...] = (),
        rubric: tuple[RubricUpdate, ...] = (),
        assumptions: tuple[str, ...] = (),
        decisions: tuple[DecisionUpdate, ...] = (),
        topics: tuple[str, ...] = (),
        feedback: FeedbackPlan | None = None,
        canvas_references: tuple[CanvasReference, ...] = (),
        canvas_proposal: CanvasProposal | None = None,
    ) -> InterviewTurnPlan:
        return InterviewTurnPlan(
            candidate_intent=candidate_intent,
            action=action,
            question_status=question_status,
            acknowledgement=acknowledgement,
            utterance=utterance,
            evidence_updates=evidence,
            rubric_updates=rubric,
            assumptions=assumptions,
            decisions=decisions,
            covered_topics=topics,
            next_phase=next_phase,
            next_question=next_question or QuestionPlan(),
            final_feedback=feedback or FeedbackPlan(),
            canvas_references=canvas_references,
            canvas_proposal=canvas_proposal or CanvasProposal(),
        )
