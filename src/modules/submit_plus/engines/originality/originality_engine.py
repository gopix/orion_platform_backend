from src.modules.submit_plus.engines.base_engine import BaseEngine


class InternalSimilarityService:
    def similarity(self, t1, t2):
        from difflib import SequenceMatcher
        return SequenceMatcher(None, t1, t2).ratio()


class ExternalSimilarityService:
    def check(self, paragraph: str):
        """
        Stub implementation.
        Future: integrate with web search / vector DB / API
        """
        return {
            "similarity": 0.0,
            "source": None,
            "matched_text": None
        }


class OriginalityEngine(BaseEngine):

    def __init__(self):
        self.internal_service = InternalSimilarityService()
        self.external_service = ExternalSimilarityService()

    def run(self, data: dict):

        content = data.get("content_extraction", {}).get("content")

        if not content:
            return {
                "originality_score": 0.0,
                "risk_level": "High",
                "flagged_sections": [],
                "recommendation": "No content provided"
            }

        if not isinstance(content, str):
            return {
                "originality_score": 0.0,
                "risk_level": "High",
                "flagged_sections": [],
                "recommendation": "Content must be a text string"
            }

        flagged_sections = []
        similarities = []

        # -------------------------
        # Split content into paragraphs
        # -------------------------
        paragraphs = [
            p.strip() for p in content.split('\n')
            if p.strip() and len(p.strip()) > 50
        ]

        print(f"Paragraphs extracted for originality analysis: {len(paragraphs)}")

        if len(paragraphs) < 2:
            return {
                "originality_score": 1.0,
                "risk_level": "Low",
                "flagged_sections": [],
                "recommendation": "Content too short for originality analysis"
            }

        # -------------------------
        # INTERNAL COMPARISON
        # -------------------------
        for i in range(len(paragraphs)):
            for j in range(i + 1, len(paragraphs)):
                sim = self.internal_service.similarity(paragraphs[i], paragraphs[j])
                similarities.append(sim)

                if sim > 0.75:
                    flagged_sections.append({
                        "paragraph_pair": f"Para {i+1} vs Para {j+1}",
                        "similarity": round(sim, 2),
                        "evidence": "High internal duplication detected"
                    })

        # -------------------------
        # EXTERNAL COMPARISON 
        # -------------------------
        for idx, para in enumerate(paragraphs):

            result = self.external_service.check(para)
            sim = result.get("similarity", 0.0)

            similarities.append(sim)

            if sim > 0.75:
                flagged_sections.append({
                    "paragraph": f"Para {idx+1}",
                    "similarity": round(sim, 2),
                    "evidence": "Paragraph closely matches external source",
                    "source": result.get("source"),
                    "matched_text": result.get("matched_text")
                })

        # -------------------------
        # AGGREGATE SCORE
        # -------------------------
        avg_similarity = sum(similarities) / len(similarities) if similarities else 0
        originality_score = round(1 - avg_similarity, 2)

        # -------------------------
        # RISK LEVEL
        # -------------------------
        if originality_score > 0.8:
            risk = "Low"
        elif originality_score > 0.5:
            risk = "Moderate"
        else:
            risk = "High"

        # -------------------------
        # RECOMMENDATION
        # -------------------------
        if risk == "High":
            recommendation = "High duplication detected. Rewrite and add citations."
        elif risk == "Moderate":
            recommendation = "Some similarity found. Review content."
        else:
            recommendation = "Content appears original."

        return {
            "originality_score": originality_score,
            "risk_level": risk,
            "flagged_sections": flagged_sections,
            "recommendation": recommendation
        }

    # -------------------------
    # Helper
    # -------------------------
    def split_paragraphs(self, text):
        return [p.strip() for p in text.split("\n") if p.strip()]