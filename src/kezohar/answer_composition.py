"""Present only the existing verifier's approved output; never fill gaps by AI."""
from .permissions import rag_eligible
from urllib.parse import quote
from .source_snapshot import unique_sources, admissible, fingerprint
from .semantic_claims import catalog_revision


def snapshot_valid(verification, sources):
    try: index=unique_sources(sources)
    except ValueError: return False
    evidence=verification.get('evidence',[])
    pinned=verification.get('source_snapshots',{})
    return (verification.get('verdict')=='ok' and bool(evidence)
            and verification.get('catalog_revision')==catalog_revision()
            and all(e.get('source_id') in index and admissible(index[e['source_id']])
                    and pinned.get(e['source_id'])==fingerprint(index[e['source_id']])
                    and e.get('quote') and e['quote'] in index[e['source_id']].get('text','')
                    for e in evidence))


def verification_layers(verification, sources):
    checks = verification.get('checks', {})
    index={s['source_id']:s for s in sources}
    evidence=verification.get('evidence',[])
    literal=bool(evidence) and all(e.get('source_id') in index and e.get('quote')
                                 and e['quote'] in index[e['source_id']].get('text','') for e in evidence)
    valid=snapshot_valid(verification,sources)
    support=checks.get('claim_support','not-proved') if valid else 'not-proved'
    return {
        'source_identity': {'existence': checks.get('source_exists', 'not-checked'),
                            'locator': checks.get('reference_identity', 'not-checked')},
        'quotation_integrity': 'passed-exact-extract' if literal and valid else 'not-proved',
        'permissions': 'passed-current-snapshot' if valid else 'not-proved',
        'overall': 'passed-software-checks' if valid else 'not-approved',
        'claim_support': {'status':'supported-bounded' if support=='supported-bounded' else 'not-proved-as-answer-to-case',
                          'method':support,'general_entailment_verified':False},
        'format': checks.get('format', 'not-checked'),
        'human_review': 'required', 'halachic_verified': False,
    }


class VerifiedAnswerComposer:
    def compose(self, result, reasoning=None, question=None, rule_answers=None, conditional_first=False):
        result = dict(result)
        # Rebuild derived case data; never trust an old presentation payload.
        result.pop('known_rule_context',None)
        result.pop('answer_status',None)
        if result.get('clarifications'):
            result['clarifications']=[c for c in result['clarifications'] if c.get('kind')!='source-condition']
        verification = result.get('verification', {})
        layers = verification_layers(verification,result.get('sources',[]))
        if result.get('mode')=='web-sources-only' and verification.get('verdict')!='ok':
            result['answer']='מצב חיפוש: המקורות זמינים לבדיקה; לא הופקה תשובה מאומתת.'
        if verification.get('verdict')=='ok' and not snapshot_valid(verification,result.get('sources',[])):
            checks=dict(verification.get('checks',{}),claim_support='not-proved',
                        source_applicability='failed-current-snapshot')
            verification=dict(verification,verdict='invalid_citation',checks=checks,
                              support='composer source snapshot mismatch')
            result.update(verdict='invalid_citation',mode='llm-guarded',verification=verification,
                          answer='אין בסיס מאומת לתשובה; המקור או הציטוט דורשים בירור נוסף.')
            layers=verification_layers(verification,result.get('sources',[]))
        if verification.get('verdict')!='ok':
            # Diagnostics are public API data too: do not leak a revoked quote,
            # a previously supported statement or a rejected model assertion.
            verification={k:v for k,v in verification.items() if k not in ('evidence','claims','rendered_answer','derived_rules')}
            result['verification']=verification
        sources = {s['source_id']: s for s in result.get('sources', [])}
        citations = []
        quotes = []
        for evidence in verification.get('evidence', []):
            source = sources.get(evidence.get('source_id'))
            if (verification.get('verdict') != 'ok' or not source or not rag_eligible(source)
                    or not source.get('reference')
                    or not evidence.get('quote') or evidence['quote'] not in source.get('text', '')):
                continue
            citations.append({k: source.get(k, '') for k in
                              ('source_id', 'work_title', 'author', 'reference', 'version', 'source_url')})
            citations[-1]['local_url']='/sources/'+quote(source['source_id'],safe='')
            quotes.append({'source_id': source['source_id'], 'text': evidence['quote'],
                           'kind': 'original-quotation'})
        if verification.get('verdict')=='ok' and (not citations or len(citations)!=len(verification.get('evidence',[]))):
            # The independent display boundary also fails closed if its source
            # snapshot no longer agrees with the verifier result.
            verification=dict(verification,verdict='invalid_citation',support='composer source snapshot mismatch')
            result.update(verdict='invalid_citation',mode='llm-guarded',verification=verification,
                          answer='אין בסיס מאומת לתשובה; המקור או הציטוט דורשים בירור נוסף.')
            citations=[];quotes=[]
            layers=verification_layers(verification,result.get('sources',[]))
        claims = [{'source_id': c['source_id'], 'text': c['text'], 'kind': 'AI-bounded-reformulation'}
                  for c in verification.get('claims', []) if c.get('assessment', {}).get('status') == 'supported'
                  and c.get('source_id') in {s['source_id'] for s in citations}]
        # Source reading is distinct from a source-supported answer to the case.
        result['structured_answer'] = {
            'short_answer': result.get('answer', ''),
            'explanation': ('הציטוט נבדק מול המקור; התאמת משמעותו למקרה עדיין דורשת בדיקה.'
                            if citations and not claims else
                            'הסבר מאומת רק בגבולות הטענות והתנאים המקובעים למקור.' if claims else
                            'אין בסיס מאומת להכרעה; אין להשלים דין מן ההשערה.'),
            'quotations': quotes, 'explanations': claims,
            'case_conditions': [c.get('assessment', {}).get('conditions', [])
                                for c in verification.get('claims', []) if verification.get('verdict')=='ok'
                                and c.get('assessment', {}).get('status') == 'supported'],
            'sources': citations,
            'difference_candidates': (reasoning or {}).get('difference_candidates', []),
            'caveat': 'אימות תוכנה אינו אישור הלכתי. נדרשת ביקורת הלכתית אנושית.',
        }
        result['verification_layers'] = layers
        if verification.get('verdict')=='ok':
            from .blessing_context import reading
            tables=reading(verification.get('evidence',[]),result.get('sources',[]))
            if tables:
                result['structured_answer']['table_readings']=tables
                if any(r['has_conditions'] for r in tables):
                    # Do not project a column when a condition elsewhere in the
                    # row might qualify it. Keep the complete literal reading.
                    result['answer']=verification.get('rendered_answer',result.get('answer',''))
                else:
                    result['answer']='\n'.join('ברכה ראשונה לפי הטבלה עבור ״'+r['food']+'״: ״'+r['first_column']+'״ ('+r['reference']+').' for r in tables)
                result['answer']+='\nהעמודה השנייה מסווגת ברכה אחרונה בלבד; אין כאן קביעה שחייבים בה לאחר כל אכילה. תנאי החיוב במקרה שלך לא אומתו.'
                result['structured_answer']['short_answer']=result['answer']
        # Only validated complete evidence enters this server-authored language
        # layer. It approves no free model paraphrase or case ruling.
        from .source_rules import context, validate_answers
        from .answer_status import describe
        answers=validate_answers(rule_answers)
        if (question is not None and result.get('verdict')=='ok' and snapshot_valid(verification,result.get('sources',[]))
                and not result['structured_answer'].get('table_readings') and not claims):
            rule_context=context(verification,result.get('sources',[]),question,answers)
            result['known_rule_context']=rule_context
            if rule_context['rules']:
                result['structured_answer']['explanations']=rule_context['rules']
                result['answer']='לפי המקור, על תנאיו:\n'+'\n'.join(
                    r['text']+' ('+r['reference']+').' for r in rule_context['rules'])
                result['structured_answer']['explanation']='הסבר שנוצר בשרת מתוך יחידת המקור המלאה; אין אימות סמנטי כללי או הכרעה במקרה.'
                missing=[c for c in rule_context['conditions'] if c['status']=='missing']
                if missing and not conditional_first:
                    result.update(verdict='rule_needs_clarification',mode='rule-with-clarification',clarifications=missing)
                    result['answer']+='\nחסר פרט להחלת הכלל: '+' '.join(c['question'] for c in missing)
                elif rule_context['conditions'] and not conditional_first:
                    result['answer']+='\nהפרטים שנמסרו מתועדים בלבד; לא אומתה הכרעה במקרה. תנאים נוספים נשמרו בטקסט המקור.'
                if conditional_first:
                    rule_context['presentation']='conditional-rules-first'
                    result['answer']+='\nזהו כלל לפי תנאיו במקור; אין כאן קביעה שכל התנאים מתקיימים במקרה שלך.'
                result['structured_answer']['short_answer']=result['answer']
        status=describe(result)
        result['answer_status']=status
        if result.get('verdict') in ('no_source','unsupported','invalid_citation','irrelevant','review_required','format_error'):
            result['answer']=status['message']
            result['structured_answer']['short_answer']=result['answer']
        result['human_review'] = 'required'
        result['halachic_verified'] = False
        return result
