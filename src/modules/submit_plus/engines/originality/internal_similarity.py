class InternalSimilarityService:

    def similarity(self, t1, t2):
        from difflib import SequenceMatcher
        return SequenceMatcher(None, t1, t2).ratio()