import copy
import json
from pathlib import Path
import pytest
from kezohar.semantic_claims import load_catalog, units_for
from kezohar.verification import ExtractiveSourceVerifier
from kezohar.agent import Agent
from kezohar.models import Source

QS={'rice':'מה מברכים על אורז?','yaaleh-shachrit':'שכחתי יעלה ויבוא בשחרית של ראש חודש',
    'tea':'מותר להכין תה בכלי שני?','travel':'מתי אומרים תפילת הדרך בנסיעה?',
    'meat-wait':'כמה זמן צריך להמתין אחרי בשר לפני חלב?'}


def source(rule):
    return {'source_id':rule['source_id'],'work_title':rule['work_title'],
            'reference':rule['reference'],'text':rule['quote']}


def answer(rule,text):
    return json.dumps({'claims':[{'source_id':rule['source_id'], 'evidence_id':rule['evidence_id'],
                                 'text':text}]},ensure_ascii=False)


@pytest.mark.parametrize('rule',load_catalog(),ids=lambda r:r['evidence_id'])
def test_supported_reformulations_are_not_exact_quotes(rule):
    for variant in rule['variants']:
        assert variant not in rule['quote']
        v=ExtractiveSourceVerifier().verify(QS[rule['intent']],answer(rule,variant),[source(rule)])
        assert v['verdict']=='ok' and v['checks']['format']=='passed'
        assert v['checks']['claim_support']=='supported-bounded'
        assert not v['halachic_verified'] and v['human_review']=='required'


@pytest.mark.parametrize('rule',load_catalog(),ids=lambda r:r['evidence_id'])
def test_contradictions_are_blocked_even_with_valid_source_and_format(rule):
    for bad in rule['contradicted_examples']:
        v=ExtractiveSourceVerifier().verify(QS[rule['intent']],answer(rule,bad),[source(rule)])
        assert v['verdict']=='contradicted'
        assert v['checks']['source_exists']==v['checks']['reference_identity']=='passed'
        assert v['checks']['format']=='passed'


@pytest.mark.parametrize('rule',load_catalog(),ids=lambda r:r['evidence_id'])
def test_conditions_cannot_be_deleted_and_extra_claims_not_allowed(rule):
    v=ExtractiveSourceVerifier()
    variants=[rule['variants'][0]+' מותר גם בכל מקרה אחר.',
              rule['variants'][0].replace('פרסה לפחות','כל מרחק').replace('מעיקר הדין','ללא הסתייגות'),
              rule['variants'][0].replace('שחרית','ערבית').replace('שש שעות','שעה אחת')]
    for bad in variants:
        if bad==rule['variants'][0]:continue
        r=v.verify(QS[rule['intent']],answer(rule,bad),[source(rule)])
        assert r['verdict']!='ok' and r['checks']['format']=='passed'


def test_copied_words_without_conditions_require_review():
    rule=next(r for r in load_catalog() if r['evidence_id']=='tea-second')
    bad='לפי עונג שבת מותר להכין תה בכלי שני.'
    r=ExtractiveSourceVerifier().verify(QS['tea'],answer(rule,bad),[source(rule)])
    assert r['verdict']=='review_required'
    assert r['checks']['reference_identity']=='passed'


def test_changed_source_text_or_locator_invalidates_support():
    rule=load_catalog()[0];s=source(rule)
    for key,value in [('text',s['text']+' תנאי נוסף.'),('reference','מקור מומצא')]:
        changed=dict(s);changed[key]=value
        r=ExtractiveSourceVerifier().verify(QS['rice'],answer(rule,rule['variants'][0]),[changed])
        assert r['verdict']==('review_required' if key=='text' else 'invalid_citation')


def test_general_meat_claim_never_proves_reused_oil_waiting():
    rule=next(r for r in load_catalog() if r['intent']=='meat-wait')
    q="צ'יפס בשמן שטוגנו בו שניצלים בשריים, צריך להמתין שש שעות לפני חלב?"
    assert units_for(q,source(rule))==[]
    assert ExtractiveSourceVerifier().verify(q,answer(rule,rule['variants'][0]),[source(rule)])['verdict']!='ok'


def test_two_claims_cannot_smuggle_an_unsupported_second_claim():
    rule=load_catalog()[0];a=json.loads(answer(rule,rule['variants'][0]))
    a['claims'].append(dict(a['claims'][0],text='מברכים המוציא לחם על אורז.'))
    assert ExtractiveSourceVerifier().verify(QS['rice'],json.dumps(a),[source(rule)])['verdict']!='ok'


def test_quote_format_and_support_are_independent():
    s={'source_id':'x','reference':'א:א','text':'אורז ברכתו מזונות'}
    a=json.dumps({'quotes':[{'source_id':'x','quote':'אורז אין ברכתו מזונות'}]})
    r=ExtractiveSourceVerifier().verify('ברכת אורז',a,[s])
    assert r['checks']['format']=='passed' and r['checks']['source_exists']=='passed'
    assert r['verdict']=='unsupported' and r['checks']['claim_support']=='not-proved'


def test_real_agent_renders_supported_paraphrase_but_blocks_unverified(monkeypatch):
    from kezohar import llm
    rule=load_catalog()[0];s=source(rule)
    monkeypatch.setattr(llm,'ask',lambda *a,**k:{'answer':answer(rule,rule['variants'][1])})
    ag=Agent(sources=[Source.from_dict(s)],base_url='local')
    assert ag.ask(QS['rice'])['verdict']=='ok'
    monkeypatch.setattr(llm,'ask',lambda *a,**k:{'answer':answer(rule,'על אורז מברכים המוציא.')})
    ag._cache.clear()
    assert ag.ask(QS['rice'])['mode']=='llm-guarded'


def test_prompt_mode_is_explicit_and_empty_statements_not_advertised():
    from kezohar.llm import build_messages
    rule=load_catalog()[0]
    a=build_messages(QS['rice'],[source(rule)])[1]['content']
    assert '"response_mode": "claims"' in a
    assert '"source_id": "'+rule['source_id']+'"' in a
    b=build_messages('הלכה אחרת',[{'source_id':'x','reference':'א:א','text':'הלכה אחרת'}])[1]['content']
    assert '"response_mode": "quotes"' in b and 'supported_statements' not in b


def test_civil_provenance_cannot_bypass_checks_using_a_real_statement():
    rule=load_catalog()[0];s=source(rule)
    s['source_url']='https://he.wikisource.org/wiki/תקנות_שירות_טלפון'
    r=ExtractiveSourceVerifier().verify(QS['rice'],answer(rule,rule['variants'][0]),[s])
    assert r['verdict']=='irrelevant' and r['checks']['source_applicability']=='failed'
