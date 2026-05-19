from src.modules.submit_plus.engines.base_engine import BaseEngine
from difflib import SequenceMatcher
import re


class RedundancyEngine(BaseEngine):

    def run(self, data: dict):

        content = data.get("content_extraction", {}).get("content")

        if not content or not isinstance(content, str):
            return self._empty_response("Invalid or missing content")

        paragraphs = [
            p.strip() for p in content.split('\n')
            if p.strip() and len(p.strip()) > 50
        ]

        duplicate_sections = []
        similarities = []

        # -------------------------
        # 1. Duplicate Detection
        # -------------------------
        for i in range(len(paragraphs)):
            for j in range(i + 1, len(paragraphs)):

                sim = self.similarity(paragraphs[i], paragraphs[j])
                similarities.append(sim)

                if sim > 0.75:
                    duplicate_sections.append({
                        "sections": [f"Para {i+1}", f"Para {j+1}"],
                        "issue": "Repeated explanation of same concept"
                    })

        # -------------------------
        # 2. Terminology Detection
        # -------------------------
        terminology_issues = self.detect_terminology_issues(content)

        # -------------------------
        # 3. Score Calculation
        # -------------------------
        avg_similarity = sum(similarities) / len(similarities) if similarities else 0

        redundancy_score = round(avg_similarity, 2)

        return {
            "redundancy_score": redundancy_score,
            "duplicate_sections": duplicate_sections,
            "terminology_issues": terminology_issues
        }

    # -------------------------
    # Similarity
    # -------------------------
    def similarity(self, t1, t2):
        return SequenceMatcher(None, t1, t2).ratio()

    # -------------------------
    # Terminology Detection
    # -------------------------
    def detect_terminology_issues(self, content):

        issues = []

        # Define simple synonym groups (expand later)
        concept_groups = [
            ["ai system", "ml engine", "artificial intelligence"],
            ["model", "algorithm", "system"]
        ]

        content_lower = content.lower()

        for group in concept_groups:
            found = [term for term in group if term in content_lower]

            if len(found) > 1:
                issues.append(f"Inconsistent usage: {', '.join(found)}")

        return issues

    def _empty_response(self, msg):
        return {
            "redundancy_score": 0.0,
            "duplicate_sections": [],
            "terminology_issues": [msg]
        }