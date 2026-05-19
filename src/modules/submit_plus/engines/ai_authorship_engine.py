from src.modules.submit_plus.engines.base_engine import BaseEngine
import re
import statistics


class AIAuthorshipEngine(BaseEngine):

    def run(self, data: dict):

        content = data.get("content_extraction", {}).get("content")

        if not content or not isinstance(content, str):
            return self._empty_response("Invalid or missing content")

        sections = self.split_sections(content)

        section_scores = []
        heatmap = []
        all_signals = []

        for sec_name, text in sections.items():

            features = self.extract_features(text)

            score = self.compute_ai_score(features)
            section_scores.append(score)

            signals = self.detect_signals(features)
            all_signals.extend(signals)

            heatmap.append({
                "section": sec_name,
                "score": round(score, 2)
            })

        # -------------------------
        # Aggregate Score
        # -------------------------
        final_score = sum(section_scores) / len(section_scores) if section_scores else 0

        classification = self.classify(final_score)
        recommendation = self.get_recommendation(final_score)

        ai_authorship_result = {
            "ai_likelihood_score": round(final_score, 2),
            "classification": classification,
            "section_heatmap": heatmap,
            "top_signals": list(set(all_signals))[:3],
            "recommendation": recommendation,
            "confidence": round(min(1.0, final_score + 0.1), 2)
        }
        return ai_authorship_result
            

    # -------------------------
    # Feature Extraction
    # -------------------------
    def extract_features(self, text):

        sentences = re.split(r'[.!?]', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        words = text.split()

        # Sentence length variance
        sentence_lengths = [len(s.split()) for s in sentences]
        variance = statistics.pstdev(sentence_lengths) if len(sentence_lengths) > 1 else 0

        # Lexical diversity
        unique_words = len(set(words))
        total_words = len(words)
        diversity = unique_words / total_words if total_words else 0

        # Repetition (simple heuristic)
        repetition = 1 - diversity

        return {
            "variance": variance,
            "diversity": diversity,
            "repetition": repetition,
            "avg_sentence_length": sum(sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0
        }

    # -------------------------
    # AI Score Computation
    # -------------------------
    def compute_ai_score(self, features):

        score = 0

        # Low variance → AI-like
        if features["variance"] < 5:
            score += 0.3

        # Low diversity → AI-like
        if features["diversity"] < 0.5:
            score += 0.3

        # High repetition → AI-like
        if features["repetition"] > 0.5:
            score += 0.4

        return min(score, 1.0)

    # -------------------------
    # Signal Detection
    # -------------------------
    def detect_signals(self, features):

        signals = []

        if features["variance"] < 5:
            signals.append("Low sentence variation")

        if features["diversity"] < 0.5:
            signals.append("Low lexical diversity")

        if features["repetition"] > 0.5:
            signals.append("Repetitive phrasing")

        return signals

    # -------------------------
    # Classification
    # -------------------------
    def classify(self, score):

        if score > 0.75:
            return "High AI Generation Likely"
        elif score > 0.5:
            return "Moderate AI Assistance Likely"
        else:
            return "Likely Human-Written"

    def get_recommendation(self, score):

        if score > 0.75:
            return "Strongly humanize content. Add examples and varied phrasing."
        elif score > 0.5:
            return "Improve sentence variety and include specific examples."
        else:
            return "Content appears natural."

    def _empty_response(self, msg):
        return {
            "ai_likelihood_score": 0.0,
            "classification": "Unknown",
            "section_heatmap": [],
            "top_signals": [],
            "recommendation": msg,
            "confidence": 0.0
        }

    # -------------------------
    # Simple Section Split
    # -------------------------
    def split_sections(self, content):

        # Simple version: treat entire content as one section
        return {
            "Full Content": content
        }