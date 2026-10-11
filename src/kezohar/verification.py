"""Deterministic source verification independent of the answer model/provider."""
from . import citations, evidence
from .source_quality import exclusion_reason, applicability_issue
from .semantic_claims import verify_claim_packet, catalog_revision
from .permissions import rag_eligible
import json
from .source_snapshot import admissible, snapshots


class ExtractiveSourceVerifier:
    def eligible_sources(self, question, sources):
        try: snapshots(sources)
        except ValueError: return []
        return evidence.applicable_sources(question, [s for s in sources
            if admissible(s)
            and not exclusion_reason(question, s)])

    def verify(self, question, answer, sources):
        initial_catalog_revision = catalog_revision()
        try: current_snapshots = snapshots(sources)
        except ValueError:
            return {'verdict':'invalid_citation','support':'ambiguous source identity',
                    'human_review':'required','halachic_verified':False}
        if answer.strip().rstrip('.') == 'אין לי מקור לכך':
            return {'verdict': 'no_source', 'support': 'no claim'}
        try:
            payload=json.loads(answer)
        except (ValueError,TypeError):
            payload=None
        claim_packet=isinstance(payload,dict) and 'claims' in payload
        verified = (verify_claim_packet(question,answer,sources) if claim_packet else
                    citations.verify_source_id_answer(answer, sources)
                    if answer.lstrip().startswith(('{', '['))
                    else citations.verify_extractive_answer(answer, sources))
        if 'checks' not in verified:
            quotes=payload.get('quotes') if isinstance(payload,dict) else None
            valid_format=(isinstance(payload,dict) and set(payload)=={'quotes'}
                          and isinstance(quotes,list) and 1<=len(quotes)<=5
                          and all(isinstance(c,dict) and set(c)=={'source_id','quote'}
                                  and all(isinstance(v,str) for v in c.values()) for c in quotes))
            ids={s.get('source_id') for s in sources}
            exists=valid_format and all(c['source_id'] in ids for c in quotes)
            stored_ref=exists and all(s.get('reference') for s in sources
                                     if s.get('source_id') in {c['source_id'] for c in quotes})
            verified['checks']={'format':'passed' if valid_format or verified['verdict'] in ('ok','no_source') else 'failed-or-legacy-unparsed',
                                'source_exists':('passed' if exists or verified.get('evidence') else 'failed' if valid_format else 'not-checked'),
                                'reference_identity':'passed' if stored_ref or verified.get('evidence') else 'not-checked',
                                'claim_support':'exact-quote-only' if verified['verdict']=='ok' else 'not-proved'}
        result = evidence.verify_context(question, verified)
        if result['verdict'] == 'ok':
            cited = {item['source_id'] for item in result.get('evidence', [])}
            if any(not admissible(s)
                   for s in sources if s['source_id'] in cited):
                result.update(verdict='invalid_citation', support='cited source permission or locator requires review')
                result['checks']['source_applicability']='failed'
                return result
            if any(exclusion_reason(question, s) for s in sources if s['source_id'] in cited):
                result.update(verdict='irrelevant', support='source genre or scenario unsuitable')
                result['checks']['source_applicability']='failed'
                return result
            if not claim_packet and any(applicability_issue(question, item['quote']) for item in result.get('evidence', [])):
                result.update(verdict='insufficient_context', support='quotation omits necessary scenario')
                result['checks']['source_applicability']='failed'
                return result
            if not claim_packet and not all(citations.check_relevance(item['quote'], question)[0]
                       for item in result.get('evidence', [])):
                result.update(verdict='irrelevant', support='quoted passage unrelated to question')
                result['checks']['source_applicability']='failed'
                return result
            if not claim_packet and not all(citations.check_relevance(s['text'], question)[0]
                       for s in sources if s['source_id'] in cited):
                result.update(verdict='irrelevant', support='cited quotation unrelated to question')
                result['checks']['source_applicability']='failed'
                return result
            if catalog_revision() != initial_catalog_revision:
                return {'verdict':'review_required', 'support':'evidence catalog changed during verification',
                        'checks':dict(result['checks'], claim_support='not-proved'),
                        'human_review':'required', 'halachic_verified':False}
            result.update(human_review='required', halachic_verified=False)
            result['source_snapshots']={sid:current_snapshots[sid] for sid in cited}
            # Bind to the catalog checked BEFORE reading units; a later update
            # also invalidates this proof at the independent display boundary.
            result['catalog_revision']=initial_catalog_revision
            result['checks']['source_applicability']='passed-necessary-checks'
        return result
