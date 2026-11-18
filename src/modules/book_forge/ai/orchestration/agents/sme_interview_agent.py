"""SMEInterviewAgent — gather book requirements from the subject-matter expert.

Business responsibility: turn a topic/audience into a set of interview questions
and a consolidated ``requirements`` dict the blueprint phase can build from.
Operates on ``InterviewState``.
"""
from src.modules.book_forge.ai.orchestration.agents.base_agent import BaseAgent
from src.modules.book_forge.ai.orchestration.workflow_state import InterviewState


class SMEInterviewAgent(BaseAgent[InterviewState]):
    """Conduct the requirements interview."""

    name = "SME Interview Agent"
    step = "interview"

    def execute(self, state: InterviewState) -> None:
        topic = state.topic or state.metadata.get("topic")
        audience = state.audience or state.metadata.get("audience") or "general readers"

        subject = topic or "the subject"
        state.questions = [
            f"What key concepts should a reader learn about {subject}?",
            "Who is the target audience and what is their background?",
            "What should readers be able to do after finishing the book?",
            "Are there prerequisites or reference works to include?",
        ]

        requirements = dict(state.requirements)
        if topic:
            requirements.setdefault("topic", topic)
        requirements.setdefault("audience", audience)
        if state.goals:
            requirements.setdefault("goals", state.goals)
        # Any answers already collected win.
        requirements.update(state.answers)

        state.audience = audience
        state.requirements = requirements
        state.add_message(
            "assistant", f"Prepared {len(state.questions)} interview questions."
        )
