"""Deterministic source verification independent of the answer model/provider."""
from . import citations, evidence
from .source_quality import exclusion_reason, applicability_issue


class ExtractiveSourceVerifier:
    def eligible_sources(self, question, sources):
        return evidence.applicable_sources(question, [s for s in sources
            if not exclusion_reason(question, s)])

    def verify(self, question, answer, sources):
        if answer.strip().rstrip('.') == 'אין לי מקור לכך':
            return {'verdict': 'no_source', 'support': 'no claim'}
        verified = (citations.verify_source_id_answer(answer, sources)
                    if answer.lstrip().startswith(('{', '['))
                    else citations.verify_extractive_answer(answer, sources))
        result = evidence.verify_context(question, verified)
        if result['verdict'] == 'ok':
            cited = {item['source_id'] for item in result.get('evidence', [])}
            if any(exclusion_reason(question, s) for s in sources if s['source_id'] in cited):
                return {'verdict': 'irrelevant', 'support': 'source genre or scenario unsuitable'}
            if any(applicability_issue(question, item['quote']) for item in result.get('evidence', [])):
                return {'verdict': 'insufficient_context', 'support': 'quotation omits necessary scenario'}
            if not all(citations.check_relevance(item['quote'], question)[0]
                       for item in result.get('evidence', [])):
                return {'verdict': 'irrelevant', 'support': 'quoted passage unrelated to question'}
            if not all(citations.check_relevance(s['text'], question)[0]
                       for s in sources if s['source_id'] in cited):
                return {'verdict': 'irrelevant', 'support': 'cited quotation unrelated to question'}
            result.update(human_review='required', halachic_verified=False)
        return result
