"""Additional bounded meaning screen, never a substitute for source verification.

Similarity and LLM confidence cannot authorize a claim. A positive result means
only an exact complete reading or a previously audited equivalence. Conditional
language is inventoried, not interpreted as a complete list of halachic facts.
"""
import re
from .hebrew import normalize
from .source_snapshot import admissible, fingerprint
from .source_rules import explain
from .semantic_claims import assess_claim

def conditional_spans(text):
    # Keep the entire containing sentence; do not extract just the favourable
    # branch or treat this inventory as a determination of essential conditions.
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', text)
            if re.search(r'(?<!\w)(?:אם|ואם|אלא|אבל|רק|ובלבד|בתנאי|כל זמן|כל עוד|כש\w+)(?!\w)', s)]

def assess(question, text, source, *, snapshot, evidence_id=None):
    base={'human_review':'required','halachic_verified':False,
          'general_entailment_verified':False,'source_id':source.get('source_id'),
          'case_application_verified':False}
    if (not isinstance(text,str) or not admissible(source) or snapshot != fingerprint(source)):
        return dict(base,status='blocked',kind='unsupported-conclusion',reason='source identity, permission or snapshot changed')
    original=source['text'].strip()
    spans=conditional_spans(original)
    from .quotation_units import reviewed_complete_quote
    if text.strip()==original or reviewed_complete_quote(text,source):
        return dict(base,status='bounded-reading',kind='exact-quotation',
                    conditional_source=bool(spans),condition_spans=spans,
                    condition_inventory_complete=False,all_source_conditions_preserved=text.strip()==original,
                    unit_context_reviewed=text.strip()!=original)
    if text==explain(source):
        return dict(base,status='bounded-equivalence',kind='supported-paraphrase',
                    method='whole-unit-server-style-equivalence',conditional_source=bool(spans),
                    condition_spans=spans,condition_inventory_complete=False,all_source_conditions_preserved=True)
    if evidence_id:
        support=assess_claim(question,text,source,evidence_id)
        if support['status']=='supported':
            conditions=support.get('conditions',[])
            return dict(base,status='bounded-equivalence',kind='conditional-conclusion' if conditions else 'supported-paraphrase',
                        method=support['method'],required_conditions=conditions,
                        case_application_verified=False)
        return dict(base,status='blocked',kind='unsupported-conclusion',reason=support.get('reason','not supported'))
    return dict(base,status='review-required',kind='unsupported-conclusion',
                reason='outside audited equivalence; exact quotation elsewhere does not prove this assertion',
                condition_spans=spans,condition_inventory_complete=False)

def screen(verification, sources, question):
    """Audit every displayed explanation against a current approved snapshot."""
    from .answer_composition import snapshot_valid
    if not snapshot_valid(verification,sources):
        return {'status':'blocked','items':[],'human_review':'required','halachic_verified':False}
    index={s['source_id']:s for s in sources}
    items=[]
    for e in verification.get('evidence',[]):
        s=index[e['source_id']]
        items.append(assess(question,e['quote'],s,snapshot=verification['source_snapshots'][e['source_id']]))
    for c in verification.get('claims',[]):
        s=index[c['source_id']]
        items.append(assess(question,c['text'],s,snapshot=verification['source_snapshots'][c['source_id']],evidence_id=c['evidence_id']))
    state=('blocked' if any(i['status']=='blocked' for i in items) else
           'review-required' if any(i['status']=='review-required' for i in items) else 'bounded-screening-only')
    return {'status':state,
            'items':items,'general_entailment_verified':False,'human_review':'required','halachic_verified':False}
