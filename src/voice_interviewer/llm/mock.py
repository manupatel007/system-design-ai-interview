from __future__ import annotations

import re

from voice_interviewer.interview.models import (
    CandidateIntent,
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
        )
