"""Bounded source-backed reformulations, distinct from citation/format checks.

This is NOT general natural-language entailment. Entire approved statements
(including conditions) must match, against a catalog pinned to source text and
locator. Unknown wording is human-review-required, never accepted by token overlap.
"""
import hashlib
import json
from .hebrew import normalize
from .evidence import shared_oil_waiting
from .source_snapshot import admissible
from .quotation_units import catalog_data


def question_intent(question):
    q=normalize(question)
    if shared_oil_waiting(question): return 'shared-oil'
    if 'אורז' in q: return 'rice'
    if 'יעלה' in q and 'שחרית' in q: return 'yaaleh-shachrit'
    if 'תה' in q.split() and 'כלי שני' in q: return 'tea'
    if 'תפילת הדרכ' in q: return 'travel'
    if 'בשר' in q and 'חלב' in q and any(t in q for t in ('להמתינ','מחכ','מחכימ','זמנ')): return 'meat-wait'
    if 'ברכת המזונ' in q: return 'birkat-mazon'
    return ''


def load_catalog():
    return catalog_data().get('rules', [])

def catalog_revision():
    return hashlib.sha256(json.dumps(catalog_data(),sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def units_for(question, source):
    if not admissible(source): return []
    intent=question_intent(question)
    if intent not in ('rice','yaaleh-shachrit','tea','travel','meat-wait'):
        return []  # in particular, meat itself never proves the shared-oil case
    digest=hashlib.sha256(source.get('text','').encode()).hexdigest()
    rules=load_catalog()
    ids=[r.get('evidence_id') for r in rules]
    return [r for r in rules if ids.count(r.get('evidence_id'))==1 and r['intent']==intent
            and r['source_text_sha256']==digest and r['reference']==source.get('reference')
            and r['work_title']==source.get('work_title')
            and r.get('source_id')==source.get('source_id')
            and r.get('author','')==source.get('author','')
            and r.get('version') and r['version']==source.get('version','')
            and r['quote'] in source.get('text','')]


def assess_claim(question, text, source, evidence_id):
    unit=next((r for r in units_for(question,source) if r['evidence_id']==evidence_id),None)
    if unit is None:
        return {'status':'unverified','reason':'no source-pinned statement for this case'}
    canonical=normalize(text)
    if canonical in {normalize(t) for t in unit['variants']}:
        return {'status':'supported','method':'bounded-whole-statement-equivalence',
                'conditions':unit['conditions'],'quote':unit['quote']}
    if canonical in {normalize(t) for t in unit['contradicted_examples']}:
        return {'status':'contradicted','reason':'opposite of source-pinned statement'}
    return {'status':'unverified','reason':'wording or conditions outside audited equivalence; human review required',
            'required_conditions':unit['conditions']}


def verify_claim_packet(question, answer, sources):
    layers={'format':'failed','source_exists':'not-checked','reference_identity':'not-checked',
            'claim_support':'not-checked'}
    def reject(verdict,reason,claims=None):
        return {'verdict':verdict,'support':reason,'checks':dict(layers),
                'claims':claims or [],'human_review':'required','halachic_verified':False}
    def unique(pairs):
        obj={}
        for k,v in pairs:
            if k in obj:raise ValueError('duplicate key')
            obj[k]=v
        return obj
    try:packet=json.loads(answer,object_pairs_hook=unique)
    except (ValueError,TypeError):return reject('format_error','invalid claim JSON')
    if (not isinstance(packet,dict) or set(packet)!={'claims'}
            or not isinstance(packet['claims'],list) or not 1<=len(packet['claims'])<=5):
        return reject('format_error','one to five source-linked claims required')
    for c in packet['claims']:
        if (not isinstance(c,dict) or set(c)!={'source_id','evidence_id','text'}
                or not all(isinstance(v,str) and v.strip() for v in c.values())):
            return reject('format_error','unexpected claim fields')
    layers['format']='passed'
    index={}
    for s in sources:
        sid=s.get('source_id')
        if sid in index and s!=index[sid]:return reject('invalid_citation','ambiguous source id')
        index[sid]=s
    claims=[];evidence=[];rendered=[]
    for c in packet['claims']:
        s=index.get(c['source_id'])
        if not s:
            layers['source_exists']='failed'
            return reject('invalid_citation','claim source not retrieved',claims)
        layers['source_exists']='passed'
        if not s.get('reference'):
            layers['reference_identity']='failed'
            return reject('invalid_citation','stored locator missing',claims)
        # Source fingerprint and locator must both match the audited evidence unit.
        declared=next((r for r in load_catalog() if r['evidence_id']==c['evidence_id']),None)
        if declared and (declared['reference']!=s['reference'] or declared['work_title']!=s.get('work_title')
                         or 'version' not in declared or declared['version']!=s.get('version','')):
            layers['reference_identity']='failed'
            return reject('invalid_citation','evidence locator does not identify this retrieved source',claims)
        layers['reference_identity']='passed'
        u=next((r for r in units_for(question,s) if r['evidence_id']==c['evidence_id']),None)
        if not u:
            layers['claim_support']='unverified'
            return reject('review_required','no matching case and text fingerprint for declared evidence unit',claims)
        assessment=assess_claim(question,c['text'],s,c['evidence_id'])
        claims.append(dict(c,assessment=assessment,reference=s['reference']))
        if assessment['status']!='supported':
            layers['claim_support']=assessment['status']
            return reject('contradicted' if assessment['status']=='contradicted' else 'review_required',
                          assessment['reason'],claims)
        evidence.append({'source_id':s['source_id'],'quote':u['quote']})
        rendered.append(c['text']+' ('+s['reference']+').')
    layers['claim_support']='supported-bounded'
    return {'verdict':'ok','support':'source-pinned-reformulations','checks':layers,
            'claims':claims,'evidence':evidence,'rendered_answer':'\n'.join(rendered),
            'semantic_scope':'bounded audited reformulations only; no general entailment',
            'human_review':'required','halachic_verified':False}
