"""Validate explanation evidence without pretending to prove general entailment.

Exact quotation and source freshness are mechanically proved. Free explanations
remain attributed proposals; necessary contradiction/condition checks can reject
but cannot certify a model's interpretation as fact or halachic authority.
"""
import re
from .source_snapshot import fingerprint,admissible
from .hebrew import strip_niqqud

class ClaimRejected(ValueError):
    pass

def validate(packet,candidates,resolve):
    if not isinstance(packet,dict) or set(packet)!={'claims'}:raise ClaimRejected('invalid-claim-envelope')
    claims=packet['claims']
    if not isinstance(claims,list) or not 1<=len(claims)<=4:raise ClaimRejected('invalid-claim-count')
    sent={};conflicts=set()
    for s in candidates:
        sid=s.get('source_id')
        if sid in sent and fingerprint(sent[sid])!=fingerprint(s):conflicts.add(sid)
        sent[sid]=s
    for sid in conflicts:sent.pop(sid,None)
    accepted=[];sources=[];seen=set()
    for c in claims:
        if not isinstance(c,dict) or set(c)!={'claim_id','kind','statement','evidence'}:raise ClaimRejected('invalid-claim-schema')
        if not isinstance(c['claim_id'],str) or not re.fullmatch(r'C[1-4]',c['claim_id']) or c['claim_id'] in seen:raise ClaimRejected('invalid-claim-id')
        seen.add(c['claim_id'])
        if c['kind'] not in ('quote','paraphrase','interpretation','inference'):raise ClaimRejected('invalid-claim-kind')
        statement=c['statement']
        if not isinstance(statement,str) or not 8<=len(statement)<=600:raise ClaimRejected('invalid-statement')
        if not isinstance(c['evidence'],list) or not 1<=len(c['evidence'])<=3:raise ClaimRejected('missing-evidence')
        evidence=[]
        for e in c['evidence']:
            if not isinstance(e,dict) or set(e) not in ({'source_id','quote'},{'source_id','unit_id'}):raise ClaimRejected('invalid-evidence-schema')
            sid=e['source_id']
            if not isinstance(sid,str) or sid not in sent:raise ClaimRejected('unsent-source')
            meta=sent[sid].get('metadata',{})
            if not admissible(sent[sid]) or not sent[sid].get('version'):raise ClaimRejected('ineligible-source')
            if meta.get('private') or meta.get('owner_id') or meta.get('user_id') or meta.get('visibility')=='private':raise ClaimRejected('private-source')
            unit=None
            if 'unit_id' in e:
                from .knowledge_units import units
                unit=next((u for u in units(sent[sid]) if u['unit_id']==e['unit_id']),None)
                if not unit:raise ClaimRejected('unknown-evidence-unit')
                quote=unit['text']
            else:quote=e['quote']  # Legacy fixture protocol; same strict guards.
            if not isinstance(quote,str) or not 8<=len(quote)<=1800 or quote not in sent[sid]['text']:raise ClaimRejected('inexact-quote')
            start=unit['start'] if unit else sent[sid]['text'].index(quote);end=start+len(quote)
            before=sent[sid]['text'][:start].rstrip(' \t');after=sent[sid]['text'][end:].lstrip(' \t')
            if (before and before[-1] not in '.!?\n') or (after and not after.startswith('\n') and quote.rstrip()[-1] not in '.!?'):
                raise ClaimRejected('fragmentary-evidence-unit')
            if re.match(r'\s*(?:ובלבד|אבל|אך|אלא|בתנאי|אם)(?=\s)',strip_niqqud(after)):
                raise ClaimRejected('adjacent-condition-omitted')
            fresh=resolve(sid)
            if not fresh or not admissible(fresh) or fingerprint(fresh)!=fingerprint(sent[sid]):raise ClaimRejected('changed-source')
            evidence.append({'source_id':sid,'quote':quote,'reference':fresh['reference'],
                'version':fresh['version'],'source_snapshot':fingerprint(fresh),
                'span':[start,end],'unit_id':unit['unit_id'] if unit else None})
            if not any(s['source_id']==sid for s in sources):sources.append(fresh)
        context=' '.join(e['quote'] for e in evidence);plain=strip_niqqud(context);out=strip_niqqud(statement)
        if c['kind']=='quote' and statement not in context:raise ClaimRejected('statement-not-quotation')
        if c['kind']!='quote':
            # Necessary guards, not a positive similarity/entailment test.
            if set(re.findall(r'\d+',statement))-set(re.findall(r'\d+',context)):raise ClaimRejected('unsupported-number')
            conditions=re.findall(r'(?:אם|אלא אם|ובלבד|בתנאי|רק אם)\s+[^.;\n]{2,100}',plain)
            if any(condition not in out for condition in conditions):raise ClaimRejected('omitted-explicit-condition')
            if re.search(r'(?<![א-ת])לא\s+(?:היה|היו|נכנס|אמר|עשה|כתב)',plain) and not re.search(r'(?<![א-ת])לא\s+',out):raise ClaimRejected('negation-omitted')
            if re.search(r'חייב|אסור|מותר|הלכה למעשה|צריך לברך|צריך להמתין',out):raise ClaimRejected('ruling-in-knowledge-explanation')
        accepted.append(dict(c,evidence=evidence,quotation_verified=True,
            claim_support='literal' if c['kind']=='quote' else 'source-linked-proposal',
            semantic_entailment_verified=False,halachic_verified=False))
    return accepted,sources
