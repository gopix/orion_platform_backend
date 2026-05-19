from src.modules.submit_plus.engines.base_engine import BaseEngine


class EditorialEngine(BaseEngine):

    def run(self, data: dict):

        content = data.get("content_extraction", {}).get("content")

        if not content or not isinstance(content, str):
            return self._empty_response("Invalid or missing content")

        sections = self.split_sections(content)

        key_issues = []
        strengths = []

        # -------------------------
        # Analyze Introduction
        # -------------------------
        intro = sections.get("Introduction", "")

        if intro:
            if len(intro.split()) < 50:
                key_issues.append({
                    "issue": "Weak introduction",
                    "evidence": ["Introduction is too brief"],
                    "impact": "Lacks context setting",
                    "recommendation": "Expand introduction with background and objectives"
                })
            else:
                strengths.append("Introduction provides context")

        # -------------------------
        # Analyze Conclusion
        # -------------------------
        conclusion = sections.get("Conclusion", "")

        if conclusion:
            if "in conclusion" not in conclusion.lower() and len(conclusion.split()) < 50:
                key_issues.append({
                    "issue": "Weak conclusion",
                    "evidence": [
                        "No clear summary of key arguments",
                        "Conclusion is too brief"
                    ],
                    "impact": "Reduces coherence",
                    "recommendation": "Rewrite conclusion with proper summary"
                })
            else:
                strengths.append("Conclusion summarizes key ideas")

        # -------------------------
        # Flow Check (basic)
        # -------------------------
        if len(sections) < 3:
            key_issues.append({
                "issue": "Poor structure",
                "evidence": ["Too few sections"],
                "impact": "Weak content organization",
                "recommendation": "Add more structured sections"
            })

        # -------------------------
        # Generic Content Check
        # -------------------------
        generic_phrases = [
            "in today's world",
            "it is important to note",
            "this highlights"
        ]

        generic_hits = sum(content.lower().count(p) for p in generic_phrases)

        if generic_hits > 3:
            key_issues.append({
                "issue": "Generic writing style",
                "evidence": ["Frequent use of generic phrases"],
                "impact": "Reduces originality and engagement",
                "recommendation": "Add specific examples and insights"
            })
        else:
            strengths.append("Content shows some specificity")

        # -------------------------
        # Readiness Status
        # -------------------------
        if len(key_issues) > 3:
            status = "Needs Major Editing"
        elif len(key_issues) > 1:
            status = "Needs Structural Editing"
        else:
            status = "Ready for Copyediting"

        return {
            "readiness_status": status,
            "key_issues": key_issues,
            "strengths": strengths
        }

    # -------------------------
    # Helpers
    # -------------------------
    def split_sections(self, content):
        """
        Simple heuristic: detect sections by keywords
        """
        sections = {}

        current_section = "General"
        sections[current_section] = ""

        for line in content.split("\n"):
            line_lower = line.lower()

            if "introduction" in line_lower:
                current_section = "Introduction"
                sections[current_section] = ""
            elif "conclusion" in line_lower:
                current_section = "Conclusion"
                sections[current_section] = ""

            sections[current_section] += line + "\n"

        return sections

    def _empty_response(self, msg):
        return {
            "readiness_status": "Unknown",
            "key_issues": [],
            "strengths": [msg]
        }