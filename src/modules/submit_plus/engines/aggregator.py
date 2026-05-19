class ManuscriptAggregator:

    def build(self, engine_outputs: dict):

        return {
            "originality": engine_outputs.get("originality"),
            "ai_authorship": engine_outputs.get("ai_authorship"),
            "editorial": engine_outputs.get("editorial"),
            "structure": engine_outputs.get("structure"),
            "redundancy": engine_outputs.get("redundancy"),
            "scoring": engine_outputs.get("scoring")
        }