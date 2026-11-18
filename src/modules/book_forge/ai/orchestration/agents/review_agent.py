"""ReviewAgent — quality-check the generated blueprint.

Business responsibility: inspect the blueprint's chapters, flag issues (missing
titles/objectives, no chapters), score it, and decide whether it's approved or
needs revisions. Operates on ``ReviewState``; reads the blueprint from
``state.metadata['blueprint']``.
"""
from typing import Any, Dict, List

from src.modules.book_forge.ai.orchestration.agents.base_agent import BaseAgent
from src.modules.book_forge.ai.orchestration.workflow_state import ReviewState

_APPROVAL_THRESHOLD = 0.8


class ReviewAgent(BaseAgent[ReviewState]):
    """Review the blueprint and approve or request revisions."""

    name = "Review Agent"
    step = "review"

    def execute(self, state: ReviewState) -> None:
        blueprint = state.metadata.get("blueprint") or {}
        chapters = blueprint.get("chapters", []) if isinstance(blueprint, dict) else []

        issues: List[Dict[str, Any]] = []
        if not chapters:
            issues.append({"severity": "high", "message": "Blueprint has no chapters."})

        for index, chapter in enumerate(chapters):
            position = index + 1
            if not chapter.get("title"):
                issues.append({"severity": "medium", "message": f"Chapter {position} has no title."})
            if not chapter.get("learning_objectives"):
                issues.append(
                    {
                        "severity": "medium",
                        "message": f"Chapter {position} has no learning objectives.",
                        "location": chapter.get("title"),
                    }
                )

        if chapters:
            complete = sum(
                1 for c in chapters if c.get("title") and c.get("learning_objectives")
            )
            score = complete / len(chapters)
        else:
            score = 0.0

        has_blocking = any(i["severity"] == "high" for i in issues)
        state.issues = issues
        state.score = round(score, 2)
        state.approved = score >= _APPROVAL_THRESHOLD and not has_blocking
        if not state.approved:
            state.revisions_requested = [i["message"] for i in issues]
        state.add_message(
            "assistant",
            f"Review complete: score={state.score}, approved={state.approved}.",
        )
