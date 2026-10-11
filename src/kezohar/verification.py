"""Deterministic source verification independent of the answer model/provider."""
from . import citations, evidence


class ExtractiveSourceVerifier:
    def eligible_sources(self, question, sources):
        return evidence.applicable_sources(question, sources)

    def verify(self, question, answer, sources):
        if answer.strip().rstrip('.') == 'אין לי מקור לכך':
            return {'verdict': 'no_source', 'support': 'no claim'}
        result = evidence.verify_context(
            question, citations.verify_extractive_answer(answer, sources))
        if result['verdict'] == 'ok':
            cited = {item['source_id'] for item in result.get('evidence', [])}
            if not all(citations.check_relevance(s['text'], question)[0]
                       for s in sources if s['source_id'] in cited):
                return {'verdict': 'irrelevant', 'support': 'cited quotation unrelated to question'}
        return result
