from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, replace

from voice_interviewer.interview.models import (
    COMPETENCY_LABELS,
    PHASE_SEQUENCE,
    RUBRIC_LEVEL_ORDER,
    AssistanceLevel,
    AssistancePolicy,
    AssistanceTurn,
    CandidateIntent,
    CanvasProposal,
    CanvasProposalKind,
    CanvasReference,
    CanvasReferenceKind,
    Competency,
    EvidenceSource,
    FeedbackPlan,
    InterviewAction,
    InterviewPhase,
    InterviewTurnPlan,
    QuestionPlan,
    QuestionStatus,
    RubricLevel,
)
from voice_interviewer.interview.state import (
    EvidenceRecord,
    GuidedTakeoverState,
    GuidedTakeoverStep,
    InterviewState,
    QuestionState,
    TurnRecord,
)
from voice_interviewer.models import InterviewContext, InterviewLanguageModel

DIAGRAM_QUESTION_PATTERN = re.compile(
    r"(?:\b(?:can|could|do)\s+you\s+(?:see|view|read|look at)\b.*\b(?:diagram|canvas|design)\b)"
    r"|(?:\bwhat (?:do|can) you see\b.*\b(?:diagram|canvas)\b)",
    re.IGNORECASE,
)
REPEAT_QUESTION_PATTERN = re.compile(
    r"\b(?:repeat (?:that|the question)|what was (?:that|the question)|say that again)\b",
    re.IGNORECASE,
)
FINISH_PATTERN = re.compile(
    r"\b(?:i(?:'m| am) done|that(?:'s| is) all|finish (?:the )?interview|"
    r"wrap (?:it|this) up)\b",
    re.IGNORECASE,
)
REFERENCE_ARCHITECTURE_PATTERN = re.compile(
    r"\b(?:complete|full|entire|end[- ]to[- ]end)\s+"
    r"(?:reference\s+)?(?:system\s+)?architecture\b"
    r"|\breference architecture\b"
    r"|\b(?:show|give|draw|create|provide)\s+(?:me\s+)?"
    r"(?:a\s+|the\s+)?(?:complete\s+|full\s+)?"
    r"(?:reference\s+)?architecture\b",
    re.IGNORECASE,
)
CANVAS_PROPOSAL_PATTERN = re.compile(
    r"\bwhat (?:can|could|should)\s+(?:i|we)\s+(?:draw|add)\b"
    r"|\bwhat can be drawn\b"
    r"|\bcan you\s+(?:draw|add|suggest|show)\s+(?:me\s+)?"
    r"(?:a\s+|some\s+|the\s+)?(?:component|connection|relationship|box|node)"
    r"|\b(?:draw|add|suggest|show)\s+(?:me\s+)?"
    r"(?:a\s+|some\s+|the\s+)?(?:component|connection|relationship|box|node)"
    r"|\bhelp me\s+(?:draw|with\s+(?:this\s+|the\s+)?(?:diagram|canvas))\b",
    re.IGNORECASE,
)
HELP_REQUEST_PATTERN = re.compile(
    r"\b(?:give|offer|provide)\s+(?:me\s+)?(?:a\s+)?(?:hint|clue|nudge|help|guidance)\b"
    r"|\b(?:can|could|would|will)\s+you\s+(?:help|guide|show)\s+me\b"
    r"|\bcan i\s+(?:get|have)\s+(?:some\s+|a\s+)?(?:help|guidance|hint|clue)\b"
    r"|\bi\s+(?:need|want)\s+(?:some\s+|a\s+)?(?:help|guidance|hint|clue)\b"
    r"|\bi(?:'d| would)\s+like\s+(?:some\s+|a\s+)?(?:help|guidance|hint|clue)\b"
    r"|\b(?:please\s+)?help\s+me\b"
    r"|\bi(?:'m| am)\s+(?:stuck|lost|not sure (?:how|what|where))\b"
    r"|\bwhat should i\s+(?:consider|do|draw|add|think about)\b"
    r"|\b(?:show|give)\s+me\s+(?:an?\s+)?(?:example|approach)\b"
    r"|\b(?:more|another|deeper)\s+(?:help|hint|detail|guidance)\b",
    re.IGNORECASE,
)

GUIDED_TAKEOVER_START_PATTERN = re.compile(
    r"\b(?:walk me through|take over(?: this| the)?(?: section| design| canvas)?|"
    r"build (?:this|it).*(?:explain|step by step)|"
    r"show me .*step by step|demonstrate .*?(?:diagram|canvas|design))\b",
    re.IGNORECASE,
)
GUIDED_TAKEOVER_CONTINUE_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:continue|next(?: step)?|go on|keep going|proceed)"
    r"(?:\s+please)?\s*[.!]?\s*$",
    re.IGNORECASE,
)
GUIDED_TAKEOVER_ALTERNATIVE_PATTERN = re.compile(
    r"\b(?:alternative|another approach|different (?:approach|design)|other option)\b",
    re.IGNORECASE,
)
GUIDED_TAKEOVER_EXIT_PATTERN = re.compile(
    r"\b(?:take back|let me take over|my turn|stop (?:the )?walkthrough|"
    r"resume (?:the )?interview|hand (?:it|control) back)\b",
    re.IGNORECASE,
)

GUIDED_TAKEOVER_BLUEPRINT = (
    (
        "entry-routing",
        "Entry and routing",
        "Establish the external caller and the ingress or routing boundary.",
    ),
    (
        "core-request-path",
        "Core request path",
        "Add the main application boundary and label the synchronous request path.",
    ),
    (
        "state-and-fast-reads",
        "State and fast reads",
        "Add durable state and the read-optimization path, including fallback behavior.",
    ),
    (
        "async-and-operations",
        "Async work and operations",
        "Add asynchronous work and make one important operational concern visible.",
    ),
)
GUIDED_TAKEOVER_QUESTIONS = (
    (
        "Why separate entry routing from application logic?",
        "What changes if traffic spans multiple regions?",
    ),
    (
        "Why is this the right service boundary?",
        "Where should validation and rate limiting live?",
    ),
    (
        "What happens on a cache miss?",
        "Which data must remain strongly consistent?",
    ),
    (
        "Why make this work asynchronous?",
        "What failure signal should wake the operator?",
    ),
)

PHASE_EXIT_COMPETENCIES: dict[InterviewPhase, tuple[Competency, ...]] = {
    InterviewPhase.REQUIREMENTS: (Competency.REQUIREMENTS_SCOPE,),
    InterviewPhase.ESTIMATION: (Competency.CAPACITY_ESTIMATION,),
    InterviewPhase.HIGH_LEVEL_DESIGN: (Competency.ARCHITECTURE_FLOW,),
    InterviewPhase.DEEP_DIVE: (
        Competency.API_DATA_MODEL,
        Competency.SCALABILITY,
        Competency.CONSISTENCY,
    ),
    InterviewPhase.RELIABILITY_SCALE: (Competency.RELIABILITY,),
    InterviewPhase.WRAP_UP: (Competency.COMMUNICATION_TRADEOFFS,),
}


@dataclass(frozen=True, slots=True)
class InterviewEngineResult:
    text: str
    state: dict[str, object]
    feedback: FeedbackPlan | None = None
    assistance: AssistanceTurn | None = None
    canvas_references: tuple[CanvasReference, ...] = ()
    canvas_proposal: CanvasProposal | None = None
    canvas_proposal_auto_accept: bool = False
    canvas_anchor_ids: tuple[str, ...] = ()


class StructuredInterviewEngine:
    def __init__(self, llm: InterviewLanguageModel) -> None:
        self.llm = llm
        self.state = InterviewState()

    def configure(
        self,
        problem: str | None,
        assistance_policy: str | AssistancePolicy | None = None,
    ) -> dict[str, object]:
        try:
            policy = (
                assistance_policy
                if isinstance(assistance_policy, AssistancePolicy)
                else AssistancePolicy(
                    assistance_policy or AssistancePolicy.ADAPTIVE.value
                )
            )
        except ValueError:
            policy = AssistancePolicy.ADAPTIVE
        self.state = InterviewState(problem=problem, assistance_policy=policy)
        return self.state.client_dict()

    async def start(self, context: InterviewContext) -> InterviewEngineResult:
        if self.state.history or self.state.current_question:
            return InterviewEngineResult(
                text="The interview is already in progress.",
                state=self.state.client_dict(),
            )
        plan = await self.llm.plan(self._context(context, "start"))
        return self._apply(plan, context=context, candidate_transcript="")

    async def respond(self, context: InterviewContext) -> InterviewEngineResult:
        transcript = context.transcript.strip()
        if self.state.completed:
            return self._completed_result()
        if FINISH_PATTERN.search(transcript):
            return await self.finalize(context)
        if self.state.guided_takeover.active:
            if GUIDED_TAKEOVER_EXIT_PATTERN.search(transcript):
                return await self.guided_takeover_command(context, "take_back")
            if GUIDED_TAKEOVER_CONTINUE_PATTERN.search(transcript):
                return await self.guided_takeover_command(context, "continue")
            if GUIDED_TAKEOVER_ALTERNATIVE_PATTERN.search(transcript):
                return await self.guided_takeover_command(context, "alternative")
            return await self.guided_takeover_command(
                context,
                "question",
                question=transcript,
            )
        if GUIDED_TAKEOVER_START_PATTERN.search(transcript):
            selected_ids = self._selected_object_ids(context)
            scope = "selection" if selected_ids else (
                "end_to_end"
                if re.search(r"\b(?:complete|full|end[- ]to[- ]end)\b", transcript)
                else "current_question"
            )
            return await self.start_guided_takeover(context, scope=scope)
        if DIAGRAM_QUESTION_PATTERN.search(transcript):
            return self._apply(
                self._diagram_visibility_plan(context),
                context=context,
                candidate_transcript=transcript,
            )
        if REPEAT_QUESTION_PATTERN.search(transcript) and self.state.current_question:
            return self._apply(
                self._repeat_question_plan(),
                context=context,
                candidate_transcript=transcript,
            )
        if REFERENCE_ARCHITECTURE_PATTERN.search(transcript):
            return await self._assist(
                context,
                transcript,
                proposal_kind=CanvasProposalKind.REFERENCE,
                level=AssistanceLevel.REFERENCE,
            )
        if CANVAS_PROPOSAL_PATTERN.search(transcript):
            return await self._assist(
                context,
                transcript,
                proposal_kind=CanvasProposalKind.SCOPED,
            )
        if HELP_REQUEST_PATTERN.search(transcript):
            return await self._assist(context, transcript)
        plan = await self.llm.plan(self._context(context, "candidate"))
        return self._apply(plan, context=context, candidate_transcript=transcript)

    async def start_guided_takeover(
        self,
        context: InterviewContext,
        *,
        scope: str = "current_question",
        step_count: int = 4,
    ) -> InterviewEngineResult:
        if self.state.completed:
            return self._completed_result()
        if self.state.guided_takeover.active:
            return self._guided_takeover_message(
                context,
                "The walkthrough is already active. Continue, ask why, request an "
                "alternative, or take the floor back.",
            )
        normalized_scope = (
            scope
            if scope in {"selection", "current_question", "end_to_end"}
            else "current_question"
        )
        bounded_count = min(
            len(GUIDED_TAKEOVER_BLUEPRINT),
            max(1, step_count),
        )
        steps = [
            GuidedTakeoverStep(identifier, title, goal)
            for identifier, title, goal in GUIDED_TAKEOVER_BLUEPRINT[:bounded_count]
        ]
        previous_takeover = self.state.guided_takeover
        self.state.guided_takeover = GuidedTakeoverState(
            active=True,
            status="planning",
            scope=normalized_scope,
            objective=self._guided_takeover_objective(context, normalized_scope),
            steps=steps,
        )
        try:
            return await self._run_guided_takeover_step(context, command="start")
        except BaseException:
            self.state.guided_takeover = previous_takeover
            raise

    async def guided_takeover_command(
        self,
        context: InterviewContext,
        command: str,
        *,
        question: str = "",
    ) -> InterviewEngineResult:
        takeover = self.state.guided_takeover
        if not takeover.active:
            return self._guided_takeover_message(
                context,
                "No walkthrough is active. Use Walk me through when you want me "
                "to demonstrate on the canvas.",
            )
        if command == "take_back":
            takeover.active = False
            takeover.status = "handed_back"
            takeover.suggested_questions = []
            return self._guided_takeover_message(
                context,
                "You have the floor again. Explain or change any part of the "
                "walkthrough, and I will resume the interview from the same question.",
            )
        if command == "continue":
            previous_takeover = deepcopy(takeover)
            try:
                if takeover.steps[takeover.step_index].status == "needs_retry":
                    return await self._run_guided_takeover_step(
                        context,
                        command="retry",
                    )
                if takeover.step_index + 1 >= len(takeover.steps):
                    takeover.active = False
                    takeover.status = "completed"
                    takeover.suggested_questions = []
                    return self._guided_takeover_message(
                        context,
                        "That completes the walkthrough. Take the floor and explain the "
                        "request path and the trade-off you would revisit first.",
                    )
                takeover.steps[takeover.step_index].status = "completed"
                takeover.step_index += 1
                return await self._run_guided_takeover_step(
                    context,
                    command="continue",
                )
            except BaseException:
                self.state.guided_takeover = previous_takeover
                raise
        if command in {"why", "question", "alternative"}:
            previous_takeover = deepcopy(takeover)
            try:
                return await self._explain_guided_takeover_step(
                    context,
                    command=command,
                    question=question,
                )
            except BaseException:
                self.state.guided_takeover = previous_takeover
                raise
        return self._guided_takeover_message(
            context,
            "That walkthrough command is not supported. Continue, ask why, "
            "request an alternative, or take the floor back.",
        )
    async def finalize(self, context: InterviewContext) -> InterviewEngineResult:
        self.state.guided_takeover.active = False
        self.state.guided_takeover.status = "handed_back"
        if self.state.completed:
            return self._completed_result()
        plan = await self.llm.plan(self._context(context, "finalize"))
        plan = replace(
            plan,
            candidate_intent=CandidateIntent.FINISH_REQUEST,
            action=InterviewAction.COMPLETE,
            next_phase=InterviewPhase.COMPLETE,
            next_question=QuestionPlan(),
        )
        return self._apply(
            plan,
            context=context,
            candidate_transcript=context.transcript.strip(),
            force_complete=True,
        )

    def _guided_takeover_objective(
        self,
        context: InterviewContext,
        scope: str,
    ) -> str:
        topic = (
            self.state.current_question.topic
            if self.state.current_question
            else self.state.phase.value.replace("_", " ")
        )
        problem = self.state.problem or context.problem or "the current system"
        if scope == "selection" and self._selected_object_ids(context):
            return f"Explain and extend the selected canvas area for {topic}."
        if scope == "end_to_end":
            return f"Build one illustrative end-to-end architecture for {problem}."
        if context.diagram is None or not context.diagram.all_nodes:
            return f"Build {problem} from a blank canvas while explaining each boundary."
        return f"Continue the current {topic} design one justified step at a time."

    def _guided_takeover_context(
        self,
        context: InterviewContext,
        *,
        command: str,
        include_canvas: bool,
        question: str = "",
        retry: bool = False,
    ) -> InterviewContext:
        takeover = self.state.guided_takeover
        step = takeover.steps[takeover.step_index]
        runtime_directive = dict(context.runtime_directive)
        runtime_directive["guidedTakeover"] = {
            "command": command,
            "scope": takeover.scope,
            "objective": takeover.objective,
            "stepIndex": takeover.step_index + 1,
            "totalSteps": len(takeover.steps),
            "stepTitle": step.title,
            "stepGoal": step.goal,
            "question": question[:500],
            "retryAfterEmptyProposal": retry,
        }
        if include_canvas:
            runtime_directive["canvasProposal"] = {
                "kind": CanvasProposalKind.SCOPED.value,
                "maxNodes": 3,
                "maxEdges": 4,
                "anchorObjectIds": list(self._selected_object_ids(context)),
            }
        return replace(
            context,
            runtime_directive=runtime_directive,
            interview_state=self.state.prompt_dict(),
            turn_mode="guided_takeover",
        )

    async def _run_guided_takeover_step(
        self,
        context: InterviewContext,
        *,
        command: str,
    ) -> InterviewEngineResult:
        takeover = self.state.guided_takeover
        step = takeover.steps[takeover.step_index]
        takeover.status = "demonstrating"
        step.status = "active"
        plan = await self.llm.plan(
            self._guided_takeover_context(
                context,
                command=command,
                include_canvas=True,
            )
        )
        proposal = self._validated_canvas_proposal(
            plan.canvas_proposal,
            context,
            requested_kind=CanvasProposalKind.SCOPED,
            max_nodes=3,
            max_edges=4,
        )
        if proposal is None:
            plan = await self.llm.plan(
                self._guided_takeover_context(
                    context,
                    command=command,
                    include_canvas=True,
                    retry=True,
                )
            )
            proposal = self._validated_canvas_proposal(
                plan.canvas_proposal,
                context,
                requested_kind=CanvasProposalKind.SCOPED,
                max_nodes=3,
                max_edges=4,
            )
        if proposal is None:
            step.status = "needs_retry"
            takeover.status = "paused"
            takeover.suggested_questions = [
                "Retry this step",
                "Explain the step without drawing",
            ]
            plan = replace(
                plan,
                utterance=(
                    "The next diagram change did not validate, so I left the canvas "
                    "untouched. Continue to retry, ask why, or take the floor back."
                ),
            )
        else:
            step.status = "completed"
            takeover.status = "paused"
            takeover.suggested_questions = list(
                GUIDED_TAKEOVER_QUESTIONS[
                    min(takeover.step_index, len(GUIDED_TAKEOVER_QUESTIONS) - 1)
                ]
            )
            if command == "start":
                plan = replace(
                    plan,
                    utterance=(
                        f"I'll use {len(takeover.steps)} short reversible steps. "
                        f"{plan.utterance}"
                    ),
                )
        takeover.last_explanation = plan.utterance
        guarded_plan = self._guard_guided_takeover_plan(plan)
        return self._apply(
            guarded_plan,
            context=context,
            candidate_transcript="",
            canvas_proposal=proposal,
            canvas_proposal_auto_accept=proposal is not None,
            canvas_anchor_ids=self._selected_object_ids(context),
        )

    async def _explain_guided_takeover_step(
        self,
        context: InterviewContext,
        *,
        command: str,
        question: str,
    ) -> InterviewEngineResult:
        takeover = self.state.guided_takeover
        takeover.status = "explaining"
        plan = await self.llm.plan(
            self._guided_takeover_context(
                context,
                command=command,
                include_canvas=False,
                question=question,
            )
        )
        takeover.status = "paused"
        takeover.last_explanation = plan.utterance
        return self._apply(
            self._guard_guided_takeover_plan(plan),
            context=context,
            candidate_transcript="",
        )

    def _guard_guided_takeover_plan(
        self,
        plan: InterviewTurnPlan,
    ) -> InterviewTurnPlan:
        return replace(
            plan,
            candidate_intent=CandidateIntent.HELP_REQUEST,
            action=InterviewAction.ASSIST,
            question_status=(
                self.state.current_question.status
                if self.state.current_question
                else QuestionStatus.NOT_APPLICABLE
            ),
            evidence_updates=(),
            rubric_updates=(),
            assumptions=(),
            decisions=(),
            covered_topics=(),
            next_phase=self.state.phase,
            next_question=QuestionPlan(),
            final_feedback=FeedbackPlan(),
            canvas_proposal=CanvasProposal(),
        )

    def _guided_takeover_message(
        self,
        context: InterviewContext,
        text: str,
    ) -> InterviewEngineResult:
        plan = self._local_plan(
            intent=CandidateIntent.HELP_REQUEST,
            action=InterviewAction.ASSIST,
            utterance=text,
        )
        return self._apply(plan, context=context, candidate_transcript="")

    async def _assist(
        self,
        context: InterviewContext,
        transcript: str,
        *,
        proposal_kind: CanvasProposalKind = CanvasProposalKind.NONE,
        level: AssistanceLevel | None = None,
    ) -> InterviewEngineResult:
        assistance = self.state.preview_assistance(
            self._selected_object_ids(context),
            level=level,
        )
        plan = await self.llm.plan(
            self._context(
                context,
                "help",
                assistance=assistance,
                proposal_kind=proposal_kind,
            )
        )
        max_nodes, max_edges = self._proposal_limits(
            proposal_kind,
            assistance.level,
        )
        canvas_proposal = self._validated_canvas_proposal(
            plan.canvas_proposal,
            context,
            requested_kind=proposal_kind,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )
        plan = replace(
            plan,
            candidate_intent=CandidateIntent.HELP_REQUEST,
            action=InterviewAction.ASSIST,
            question_status=(
                self.state.current_question.status
                if self.state.current_question
                else QuestionStatus.NOT_APPLICABLE
            ),
            evidence_updates=(),
            rubric_updates=(),
            assumptions=(),
            decisions=(),
            covered_topics=(),
            next_phase=self.state.phase,
            next_question=QuestionPlan(),
            final_feedback=FeedbackPlan(),
            canvas_proposal=CanvasProposal(),
        )
        return self._apply(
            plan,
            context=context,
            candidate_transcript=transcript,
            assistance=assistance,
            canvas_proposal=canvas_proposal,
        )

    def _context(
        self,
        context: InterviewContext,
        turn_mode: str,
        *,
        assistance: AssistanceTurn | None = None,
        proposal_kind: CanvasProposalKind = CanvasProposalKind.NONE,
    ) -> InterviewContext:
        runtime_directive = dict(context.runtime_directive)
        if assistance is not None:
            runtime_directive["assistance"] = assistance.to_dict()
        if proposal_kind is not CanvasProposalKind.NONE and assistance is not None:
            max_nodes, max_edges = self._proposal_limits(
                proposal_kind,
                assistance.level,
            )
            runtime_directive["canvasProposal"] = {
                "kind": proposal_kind.value,
                "maxNodes": max_nodes,
                "maxEdges": max_edges,
                "anchorObjectIds": list(assistance.object_ids),
            }
        return replace(
            context,
            runtime_directive=runtime_directive,
            interview_state=self.state.prompt_dict(),
            turn_mode=turn_mode,
        )

    @staticmethod
    def _proposal_limits(
        kind: CanvasProposalKind,
        level: AssistanceLevel,
    ) -> tuple[int, int]:
        if kind is CanvasProposalKind.REFERENCE:
            return 12, 18
        if kind is CanvasProposalKind.NONE:
            return 0, 0
        if level is AssistanceLevel.NUDGE:
            return 1, 2
        if level is AssistanceLevel.CONCEPT:
            return 2, 4
        return 4, 6

    @staticmethod
    def _selected_object_ids(context: InterviewContext) -> tuple[str, ...]:
        if context.diagram is None:
            return ()
        valid_ids = {
            item.id for item in (*context.diagram.all_nodes, *context.diagram.all_edges)
        }
        selected_ids = (
            context.selected_object_ids or context.diagram.selected_object_ids
        )
        return tuple(
            dict.fromkeys(
                identifier
                for identifier in selected_ids
                if identifier in valid_ids
            )
        )[:8]

    def _apply(
        self,
        plan: InterviewTurnPlan,
        *,
        context: InterviewContext,
        candidate_transcript: str,
        force_complete: bool = False,
        assistance: AssistanceTurn | None = None,
        canvas_proposal: CanvasProposal | None = None,
        canvas_proposal_auto_accept: bool = False,
        canvas_anchor_ids: tuple[str, ...] = (),
    ) -> InterviewEngineResult:
        if candidate_transcript:
            self.state.turn_index += 1
            if assistance is None:
                self.state.phase_turns += 1

        if self.state.current_question:
            self.state.current_question.status = plan.question_status

        self._apply_evidence(
            plan, context=context, candidate_transcript=candidate_transcript
        )
        self._apply_rubric(plan)
        self._extend_unique(self.state.assumptions, plan.assumptions, maximum=40)
        self._apply_decisions(plan)
        self._extend_unique(self.state.covered_topics, plan.covered_topics, maximum=60)

        next_phase = self._resolve_phase(plan, force_complete=force_complete)
        if next_phase != self.state.phase:
            self.state.phase = next_phase
            self.state.phase_turns = 0
            self.state.phase_history.append(next_phase)

        if plan.action is InterviewAction.COMPLETE or self.state.phase is InterviewPhase.COMPLETE:
            self.state.current_question = None
            self.state.completed = True
            self.state.feedback = (
                plan.final_feedback
                if not plan.final_feedback.is_empty
                else self._fallback_feedback()
            )
        elif plan.next_question.text:
            self.state.current_question = QuestionState(
                id=f"q-{len(self.state.history) + 1}",
                text=plan.next_question.text,
                topic=plan.next_question.topic,
                expected_evidence=plan.next_question.expected_evidence,
                asked_turn=self.state.turn_index,
            )
            self._extend_unique(
                self.state.covered_topics, (plan.next_question.topic,), maximum=60
            )
        elif plan.question_status in {
            QuestionStatus.ANSWERED,
            QuestionStatus.NOT_APPLICABLE,
        } and plan.action not in {
            InterviewAction.ANSWER_CANDIDATE,
            InterviewAction.ASSIST,
            InterviewAction.CLARIFY,
        }:
            self.state.current_question = None

        if assistance is not None:
            self.state.record_assistance(assistance)
        if canvas_proposal is not None:
            self.state.record_canvas_proposal(canvas_proposal)

        self.state.history.append(
            TurnRecord(
                turn=self.state.turn_index,
                phase=self.state.phase,
                candidate=candidate_transcript[:2_000],
                interviewer=plan.utterance,
                intent=plan.candidate_intent,
                action=plan.action,
                question_status=plan.question_status,
            )
        )
        if len(self.state.history) > 200:
            del self.state.history[:-200]
        return InterviewEngineResult(
            text=plan.utterance,
            state=self.state.client_dict(),
            feedback=self.state.feedback if self.state.completed else None,
            assistance=assistance,
            canvas_references=self._validated_canvas_references(
                plan,
                context,
                assistance=assistance,
            ),
            canvas_proposal=canvas_proposal,
            canvas_proposal_auto_accept=canvas_proposal_auto_accept,
            canvas_anchor_ids=canvas_anchor_ids,
        )

    @staticmethod
    def _validated_canvas_proposal(
        proposal: CanvasProposal,
        context: InterviewContext,
        *,
        requested_kind: CanvasProposalKind,
        max_nodes: int,
        max_edges: int,
    ) -> CanvasProposal | None:
        if requested_kind is CanvasProposalKind.NONE or proposal.is_empty:
            return None
        existing_node_ids = (
            {node.id for node in context.diagram.all_nodes}
            if context.diagram is not None
            else set()
        )
        nodes = tuple(
            node for node in proposal.nodes if node.id not in existing_node_ids
        )[:max_nodes]
        proposed_node_ids = {node.id for node in nodes}
        allowed_endpoint_ids = existing_node_ids | proposed_node_ids
        edges = tuple(
            edge
            for edge in proposal.edges
            if edge.source_id in allowed_endpoint_ids
            and edge.target_id in allowed_endpoint_ids
        )[:max_edges]
        if not nodes and not edges:
            return None
        return replace(
            proposal,
            kind=requested_kind,
            nodes=nodes,
            edges=edges,
        )

    @staticmethod
    def _validated_canvas_references(
        plan: InterviewTurnPlan,
        context: InterviewContext,
        *,
        assistance: AssistanceTurn | None = None,
    ) -> tuple[CanvasReference, ...]:
        if context.diagram is None:
            return ()
        valid_ids = {
            item.id for item in (*context.diagram.all_nodes, *context.diagram.all_edges)
        }
        references: list[CanvasReference] = []
        for reference in plan.canvas_references[:3]:
            object_ids = tuple(
                dict.fromkeys(
                    identifier
                    for identifier in reference.object_ids
                    if identifier in valid_ids
                )
            )
            if object_ids:
                references.append(replace(reference, object_ids=object_ids))
        if assistance is not None and assistance.object_ids:
            scope_ids = set(assistance.object_ids)
            scope_is_referenced = any(
                scope_ids.issubset(reference.object_ids)
                for reference in references
            )
            if not scope_is_referenced:
                references.insert(
                    0,
                    CanvasReference(
                        kind=CanvasReferenceKind.FOCUS,
                        label=(
                            f"{assistance.level.value.capitalize()} requested here"
                        ),
                        object_ids=assistance.object_ids,
                    ),
                )
        return tuple(references[:3])

    def _apply_evidence(
        self,
        plan: InterviewTurnPlan,
        *,
        context: InterviewContext,
        candidate_transcript: str,
    ) -> None:
        valid_object_ids: set[str] = set()
        if context.diagram:
            valid_object_ids.update(item.id for item in context.diagram.nodes)
            valid_object_ids.update(item.id for item in context.diagram.edges)
        for update in plan.evidence_updates:
            if len(self.state.evidence) >= 200:
                break
            object_ids = tuple(
                identifier for identifier in update.object_ids if identifier in valid_object_ids
            )
            source = update.source
            if source is EvidenceSource.DIAGRAM and not object_ids:
                continue
            if source is EvidenceSource.COMBINED and not object_ids:
                if not candidate_transcript:
                    continue
                source = EvidenceSource.TRANSCRIPT
            evidence_id = f"ev-{self.state.turn_index}-{len(self.state.evidence) + 1}"
            self.state.evidence.append(
                EvidenceRecord(
                    id=evidence_id,
                    turn=self.state.turn_index,
                    competency=update.competency,
                    summary=update.summary.strip()[:240],
                    source=source,
                    object_ids=object_ids,
                )
            )
            entry = self.state.rubric[update.competency]
            if (
                source is not EvidenceSource.DIAGRAM
                and RUBRIC_LEVEL_ORDER[entry.level]
                < RUBRIC_LEVEL_ORDER[RubricLevel.SOME_EVIDENCE]
            ):
                entry.level = RubricLevel.SOME_EVIDENCE
            entry.evidence_ids.append(evidence_id)

    def _apply_rubric(self, plan: InterviewTurnPlan) -> None:
        for update in plan.rubric_updates:
            entry = self.state.rubric[update.competency]
            has_reasoning_evidence = any(
                item.competency is update.competency
                and item.source is not EvidenceSource.DIAGRAM
                for item in self.state.evidence
            )
            if not has_reasoning_evidence:
                continue
            if RUBRIC_LEVEL_ORDER[update.level] > RUBRIC_LEVEL_ORDER[entry.level]:
                entry.level = update.level
            if update.rationale:
                entry.rationale = update.rationale

    def _apply_decisions(self, plan: InterviewTurnPlan) -> None:
        existing = {
            (item.topic.casefold(), item.choice.casefold()) for item in self.state.decisions
        }
        for decision in plan.decisions:
            if len(self.state.decisions) >= 40:
                break
            key = (decision.topic.casefold(), decision.choice.casefold())
            if key not in existing:
                self.state.decisions.append(decision)
                existing.add(key)

    def _resolve_phase(
        self, plan: InterviewTurnPlan, *, force_complete: bool
    ) -> InterviewPhase:
        current = self.state.phase
        if force_complete:
            return InterviewPhase.COMPLETE
        if current is InterviewPhase.COMPLETE:
            return current
        if (
            plan.action is InterviewAction.COMPLETE
            and (
                current is InterviewPhase.WRAP_UP
                or plan.candidate_intent is CandidateIntent.FINISH_REQUEST
            )
        ):
            return InterviewPhase.COMPLETE
        if plan.next_phase is current:
            return current
        next_index = min(PHASE_SEQUENCE.index(current) + 1, len(PHASE_SEQUENCE) - 1)
        allowed_next = PHASE_SEQUENCE[next_index]
        if plan.next_phase is not allowed_next:
            return current
        if current is InterviewPhase.INTRODUCTION or self._phase_exit_satisfied(current):
            return allowed_next
        return current

    def _phase_exit_satisfied(self, phase: InterviewPhase) -> bool:
        competencies = PHASE_EXIT_COMPETENCIES.get(phase, ())
        if any(
            self.state.rubric[item].level is not RubricLevel.NOT_OBSERVED
            for item in competencies
        ):
            return True
        return self.state.phase_turns >= 3

    def _diagram_visibility_plan(self, context: InterviewContext) -> InterviewTurnPlan:
        if not context.diagram or not context.diagram.all_nodes:
            statement = (
                "I can see the canvas, but it does not contain any labeled components yet."
            )
        else:
            names = [
                (node.label or node.role.replace("_", " "))[:60]
                for node in context.diagram.all_nodes
            ]
            visible = ", ".join(names[:4])
            relation = self._first_relation(context)
            statement = f"Yes—I can see {visible}"
            if relation:
                statement += f", with {relation}"
            statement += ". The diagram is coming through clearly; please continue."
        return self._local_plan(
            intent=CandidateIntent.DIAGRAM_QUESTION,
            action=InterviewAction.ANSWER_CANDIDATE,
            utterance=statement,
        )

    def _first_relation(self, context: InterviewContext) -> str:
        if not context.diagram:
            return ""
        names = {
            node.id: (node.label or node.role.replace("_", " "))[:60]
            for node in context.diagram.all_nodes
        }
        for edge in context.diagram.all_edges:
            if edge.source_id in names and edge.target_id in names:
                return f"{names[edge.source_id]} connected to {names[edge.target_id]}"
        return ""

    def _repeat_question_plan(self) -> InterviewTurnPlan:
        question = self.state.current_question
        utterance = f"Of course. {question.text}" if question else "Please continue."
        return self._local_plan(
            intent=CandidateIntent.CLARIFICATION_REQUEST,
            action=InterviewAction.CLARIFY,
            utterance=utterance,
        )

    def _local_plan(
        self,
        *,
        intent: CandidateIntent,
        action: InterviewAction,
        utterance: str,
    ) -> InterviewTurnPlan:
        return InterviewTurnPlan(
            candidate_intent=intent,
            action=action,
            question_status=(
                self.state.current_question.status
                if self.state.current_question
                else QuestionStatus.NOT_APPLICABLE
            ),
            acknowledgement=utterance,
            utterance=utterance,
            evidence_updates=(),
            rubric_updates=(),
            assumptions=(),
            decisions=(),
            covered_topics=(),
            next_phase=self.state.phase,
            next_question=QuestionPlan(),
            final_feedback=FeedbackPlan(),
        )

    def _fallback_feedback(self) -> FeedbackPlan:
        observed = [
            COMPETENCY_LABELS[item]
            for item, entry in self.state.rubric.items()
            if entry.level is not RubricLevel.NOT_OBSERVED
        ]
        missing = [
            COMPETENCY_LABELS[item]
            for item, entry in self.state.rubric.items()
            if entry.level is RubricLevel.NOT_OBSERVED
        ]
        strengths = tuple(observed[:3])
        improvements = tuple(
            f"Develop {item.lower()} with explicit trade-offs"
            for item in missing[:3]
        )
        summary = (
            "The interview is complete. The feedback distinguishes demonstrated evidence "
            "from areas that were not discussed."
        )
        return FeedbackPlan(
            summary=summary,
            strengths=strengths,
            improvements=improvements,
            not_discussed=tuple(missing[:6]),
        )

    def _completed_result(self) -> InterviewEngineResult:
        feedback = self.state.feedback or self._fallback_feedback()
        self.state.feedback = feedback
        return InterviewEngineResult(
            text="The interview is already complete. Your structured feedback is available.",
            state=self.state.client_dict(),
            feedback=feedback,
        )

    @staticmethod
    def _extend_unique(
        target: list[str],
        values: tuple[str, ...],
        *,
        maximum: int,
    ) -> None:
        existing = {item.casefold() for item in target}
        for value in values:
            normalized = value.strip()[:240]
            if len(target) >= maximum:
                break
            if normalized and normalized.casefold() not in existing:
                target.append(normalized)
                existing.add(normalized.casefold())
