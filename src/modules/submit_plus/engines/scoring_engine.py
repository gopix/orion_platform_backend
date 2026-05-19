from src.modules.submit_plus.engines.base_engine import BaseEngine
from src.core.logger import get_logger

logger = get_logger(__name__)



class ScoringEngine(BaseEngine):

    def run(self, data: dict):
        logger.info(f"Scoring input: {data}")
        print(f"************data: {data}")
        originality = data.get("originality", {})
        ai_authorship = data.get("ai", {})
        editorial = data.get("editorial", {})
        structure = data.get("structure", {})
        redundancy = data.get("redundancy", {})

        # -------------------------
        # Normalize Scores
        # -------------------------
        orig_score = originality.get("originality_score", 0)

        ai_score = 1 - ai_authorship.get("ai_likelihood_score", 0)

        structure_score = structure.get("structure_score", 0)

        redundancy_score = 1 - redundancy.get("redundancy_score", 0)

        status_map = {
            "Ready for Copyediting": 0.9,
            "Needs Structural Editing": 0.6,
            "Needs Major Editing": 0.3
        }

        editorial_score = status_map.get(
            editorial.get("readiness_status"),
            0.5
        )

        # -------------------------
        # Weighted Score
        # -------------------------
        final_score = (
            orig_score * 0.25 +
            ai_score * 0.15 +
            editorial_score * 0.25 +
            structure_score * 0.20 +
            redundancy_score * 0.15
        )

        submission_score = int(final_score * 100)

        # -------------------------
        # Readiness Label
        # -------------------------
        if submission_score >= 85:
            label = "Ready for Editing"
        elif submission_score >= 65:
            label = "Needs Minor Revision"
        elif submission_score >= 45:
            label = "Needs Structural Editing"
        else:
            label = "High Risk Submission"

        # -------------------------
        # Effort Estimation
        # -------------------------
        if submission_score >= 85:
            effort = "Low"
            hours = 5
        elif submission_score >= 65:
            effort = "Medium"
            hours = 18
        elif submission_score >= 45:
            effort = "High"
            hours = 30
        else:
            effort = "Very High"
            hours = 50

        # -------------------------
        # Recommended Action
        # -------------------------
        if submission_score >= 85:
            action = "Proceed to copyediting"
        elif submission_score >= 65:
            action = "Proceed with copyediting after fixes"
        elif submission_score >= 45:
            action = "Require structural revision before editing"
        else:
            action = "Reject or major rewrite required"

        return {
            "submission_score": submission_score,
            "readiness_label": label,
            "editing_effort": effort,
            "estimated_hours": hours,
            "recommended_action": action
        }