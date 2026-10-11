import json
from pathlib import Path
import pytest
from kezohar.source_quality import classify, exclusion_reason, web_locator_issue
from kezohar.verification import ExtractiveSourceVerifier
from kezohar.agent import Agent, order_sources
from kezohar.models import Source
from kezohar.web_research import WebResearchEngine


def source(**overrides):
    return dict(source_id='stable', work_title='שולחן ערוך', reference='שולחן ערוך רח:ז',
                text='אורז מבושל ברכתו מזונות', **overrides)


def packet(s, quote=None):
    return json.dumps({'quotes':[{'source_id':s['source_id'], 'quote':quote or s['text']}]}, ensure_ascii=False)


def test_reference_rendered_from_metadata_not_model():
    s=source(); v=ExtractiveSourceVerifier().verify('ברכת אורז',packet(s),[s])
    assert v['verdict']=='ok' and s['reference'] in v['rendered_answer']
    assert not v['halachic_verified'] and v['human_review']=='required'


@pytest.mark.parametrize('payload',[
    {'quotes':[{'source_id':'invented','quote':'אורז מבושל ברכתו מזונות'}]},
    {'quotes':[{'source_id':'stable','quote':'אורז מבושל אין ברכתו מזונות'}]},
    {'quotes':[{'source_id':'stable','quote':'אורז מבושל ברכתו מזונות','reference':'רמ״א א:א'}]},
    {'quotes':[{'source_id':'stable','quote':'אורז מבושל ברכתו מזונות'}],'ruling':'מותר בכל מצב'},
    {'quotes':[]}, {'status':'no_source','ruling':'מותר'}, [],
])
def test_unsupported_claims_remain_blocked(payload):
    assert ExtractiveSourceVerifier().verify('אורז',json.dumps(payload),[source()])['verdict']!='ok'


def test_internal_abbreviation_quotes_are_exact_not_rewritten():
    s=source(); s['text']='אורז מבושל, וכ"כ הרמב"ם, ברכתו מזונות'
    assert ExtractiveSourceVerifier().verify('אורז',packet(s),[s])['verdict']=='ok'


def test_duplicate_json_keys_and_ambiguous_ids_rejected():
    v=ExtractiveSourceVerifier()
    assert v.verify('אורז','{"status":"no_source","status":"no_source"}',[source()])['verdict']=='unsupported'
    b=source();b['text']='אחר'
    assert v.verify('אורז',packet(source()),[source(),b])['verdict']=='invalid_citation'


def test_civil_title_overrides_fake_authority_and_exact_quote():
    s=source();s.update(work_title='תקנות שירות טלפון',text='טלפון בשבת אסור',authority_level='maran')
    assert classify(s)['domain']=='civil-law'
    assert not order_sources([s],'טלפון בשבת')
    assert ExtractiveSourceVerifier().verify('טלפון בשבת',packet(s),[s])['verdict']=='irrelevant'


def test_web_civil_document_never_saved_even_with_permission(tmp_path):
    url='https://he.wikisource.org/wiki/תקנות_שירות_טלפון'
    page='<title>תקנות שירות טלפון – ויקיטקסט</title><p>טלפון בשבת אסור</p>'
    sites={'he.wikisource.org':{'license':'pd'}}
    licenses={'pd':{'allows_full_text':True,'scope':dict(local_storage=True,search_index=True,rag_answers=True)}}
    path=tmp_path/'store.jsonl'
    e=WebResearchEngine(fetcher=lambda u:(page,u),sites=sites,licenses=licenses,store_path=path)
    r=e.research('טלפון בשבת',urls=[url])
    assert not r['sources'] and r['rejected_sources'] and not path.exists()


def test_wikisource_locator_must_match_page():
    assert web_locator_issue('שולחן ערוך – ויקיטקסט','https://he.wikisource.org/wiki/שולחן_ערוך') is None
    assert web_locator_issue('שולחן ערוך','https://he.wikisource.org/wiki/תקנות_טלפון')
    assert web_locator_issue('שולחן ערוך','https://he.wikisource.org/w/index.php?id=1')


def test_reputation_does_not_supply_authority():
    assert classify({'work_title':'מאמר','source_url':'https://he.wikisource.org/wiki/מאמר'})['halachic_authority']=='unclassified'
    assert classify({'work_title':'חוק לישראל'})['domain']!='civil-law'
    assert exclusion_reason('שבת',{'work_title':'סוד ישרים','text':'שבת כלי קיבול',
                                 'author':'gershon-henoch-leiner-of-radzin'})
    assert classify({'work_title':'סוד ישרים','author':'מחבר אחר'})['source_type']!='mysticism'


@pytest.mark.parametrize('question,text',[
    ('מותר לאכול דג עם חלב?','חלב ודגים שאין להם סימני כשרות צריכים השגחה'),
    ('מתי אומרים תפילת הדרך?','חייב לומר תפילת הדרך בכל מין נסיעה'),
    ('מותר להוסיף מים למיחם בשבת?','מותר לערות מים מהמיחם לתוך תבשיל'),
    ('האם שהחיינו לפני ברכת העץ?','על פרי עונתי מברכים שהחיינו'),
])
def test_shared_words_do_not_supply_scenario(question,text):
    s=source();s['text']=text
    assert exclusion_reason(question,s)
    assert not ExtractiveSourceVerifier().eligible_sources(question,[s])


def test_cited_quote_itself_must_be_relevant():
    s=source();s['text']+='. תפילה בשבת'
    assert ExtractiveSourceVerifier().verify('אורז',packet(s,'תפילה בשבת'),[s])['verdict']=='irrelevant'


def test_structured_protocol_runs_through_agent_and_web(monkeypatch):
    from kezohar import llm
    s=source()
    monkeypatch.setattr(llm,'ask',lambda q, ss, *a, **k:{'answer':packet(ss[0])})
    ag=Agent(sources=[Source.from_dict(s)],base_url='local',model='mock')
    assert ag.ask('ברכת אורז')['answer'].endswith('('+s['reference']+').')
    e=WebResearchEngine(fetcher=lambda u:('',u))
    assert e.answer('ברכת אורז','local','mock',urls=[],local_sources=[s])['mode']=='web-llm-verified'


def test_original_twenty_outputs_are_frozen_without_success_inflation():
    d=json.loads(Path('bench/frozen/halacha_2026-10-11.json').read_text())
    assert len(d['questions'])==20 and d['summary']['citation_software_passed']==0
    for r in d['questions']:
        if r['qwen_called']:
            assert r['frozen_messages'] and r['raw_qwen_answer']==r['qwen_calls'][0]['answer']


def test_web_excerpt_id_is_independent_of_question_wording():
    url='https://halachayomit.co.il/test'
    page='<title>ברכת אורז הלכה</title><p>אורז מבושל ברכתו מזונות וברכה אחרונה נפשות.</p>'
    e=WebResearchEngine(fetcher=lambda u:(page,u))
    a=e.research('ברכת אורז',urls=[url])['sources'][0]
    b=e.research('איך מברכים על אורז?',urls=[url])['sources'][0]
    assert a['text']==b['text'] and a['source_id']==b['source_id']


def test_web_top_level_verdict_never_masks_verification_failure(monkeypatch):
    from kezohar import llm
    e=WebResearchEngine(fetcher=lambda u:('',u))
    s=source()
    monkeypatch.setattr(llm,'ask',lambda *a,**k:{'answer':'מותר בוודאות.'})
    r=e.answer('אורז','local','mock',urls=[],local_sources=[s])
    assert r['verdict']==r['verification']['verdict']=='unsupported'
    monkeypatch.setattr(llm,'ask',lambda *a,**k:{'answer':'{"status":"no_source"}'})
    r=e.answer('אורז','local','mock',urls=[],local_sources=[s])
    assert r['verdict']==r['verification']['verdict']=='no_source'
