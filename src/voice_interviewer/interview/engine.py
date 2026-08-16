from __future__ import annotations

import re
from dataclasses import dataclass, replace

from voice_interviewer.interview.models import (
    COMPETENCY_LABELS,
    PHASE_SEQUENCE,
    RUBRIC_LEVEL_ORDER,
    CandidateIntent,
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


class StructuredInterviewEngine:
    def __init__(self, llm: InterviewLanguageModel) -> None:
        self.llm = llm
        self.state = InterviewState()

    def configure(self, problem: str | None) -> dict[str, object]:
        self.state = InterviewState(problem=problem)
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
        plan = await self.llm.plan(self._context(context, "candidate"))
        return self._apply(plan, context=context, candidate_transcript=transcript)

    async def finalize(self, context: InterviewContext) -> InterviewEngineResult:
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

    def _context(self, context: InterviewContext, turn_mode: str) -> InterviewContext:
        return replace(
            context,
            interview_state=self.state.prompt_dict(),
            turn_mode=turn_mode,
        )

    def _apply(
        self,
        plan: InterviewTurnPlan,
        *,
        context: InterviewContext,
        candidate_transcript: str,
        force_complete: bool = False,
    ) -> InterviewEngineResult:
        if candidate_transcript:
            self.state.turn_index += 1
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
            InterviewAction.CLARIFY,
        }:
            self.state.current_question = None

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
        )

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
        if not context.diagram or not context.diagram.nodes:
            statement = (
                "I can see the canvas, but it does not contain any labeled components yet."
            )
        else:
            names = [
                (node.label or node.role.replace("_", " "))[:60]
                for node in context.diagram.nodes
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
            for node in context.diagram.nodes
        }
        for edge in context.diagram.edges:
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
