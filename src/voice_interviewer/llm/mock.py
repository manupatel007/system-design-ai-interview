from __future__ import annotations

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
