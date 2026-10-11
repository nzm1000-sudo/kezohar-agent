"""Synthetic adversarial outputs are explicitly distinct from real Qwen data."""
import json
from pathlib import Path
import pytest
from kezohar.agent import Agent
from kezohar import citations, evidence, llm
from kezohar.web_research import WebResearchEngine

CASE = json.loads(Path('bench/halachic_cases/fries_shared_meat_oil.json').read_text())
Q = CASE['question']
# These source texts are synthetic policy fixtures, not quotations from poskim.
EXPLICIT = "ציפס שטוגן בשמן שבו טוגנו שניצלים ויש בו שומן בשרי, צריך להמתין שש שעות לפני אכילת חלב."

def source(text):
    return {'source_id':'synthetic-1','reference':'מקור בדיקה א:א','text':text}

@pytest.mark.parametrize('text', [
    'אסור לאכול בשר עם חלב.',
    'ציפס שטוגן בשמן חדש בכלי שטוגנו בו שניצלים אינו צריך להמתין שש שעות לפני חלב.',
    'האם ציפס בשמן שבו טוגנו שניצלים צריך להמתין שש שעות לפני אכילת חלב?',
    'ציפס שטוגן בשמן שבו טוגנו שניצלים אסור עם חלב. אחרי חלב צריך להמתין שש שעות לפני בשר.',
    'אכל בשר לא יאכל גבינה עד שישהה שש שעות.',
    'ציפס שטוגן בשמן של שניצלים אסור לאוכלו עם חלב.',
    'ציפס בשמן שניצלים אסור עם חלב. אחרי חלב צריך להמתין לפני אכילת בשר.',
])
def test_separation_and_generic_waiting_are_not_case_evidence(text, monkeypatch):
    monkeypatch.setattr(llm, 'ask', lambda *a,**k: pytest.fail('Insufficient evidence must bypass inference'))
    result = Agent(sources=[]).ask(Q, retrieved_sources=[source(text)])
    assert result['verdict']=='insufficient_context'
    assert result['answer']==evidence.INSUFFICIENT
    assert 'איסור אכילה עם חלב כשלעצמו אינו מוכיח' in result['answer']

@pytest.mark.parametrize('answer', [
    *[s['text'] for s in CASE['synthetic_problematic_responses']],
    'הרב עובדיה יוסף פסק שחייבים שש שעות (מקור בדיקה א:א).',
    'בוודאי חייבים תמיד. ״'+EXPLICIT+'״ (מקור בדיקה א:א).',
    '״צריך להמתין שש שעות לפני אכילת חלב.״ (מקור בדיקה א:א).',
    '״אין צורך להמתין שש שעות לפני אכילת חלב.״ (מקור בדיקה א:א).',
    '״'+EXPLICIT+'״ (מקור בדיקה א:ב).',
])
def test_fabrication_attribution_certainty_and_context_loss_blocked(answer, monkeypatch):
    monkeypatch.setattr(llm,'ask',lambda *a,**k:{'answer':answer})
    result=Agent(sources=[]).ask(Q,retrieved_sources=[source(EXPLICIT)])
    assert result['mode']=='llm-guarded'
    assert result['answer']==evidence.INSUFFICIENT

@pytest.mark.parametrize('text', [EXPLICIT, EXPLICIT.replace('צריך להמתין','אין צריך להמתין')])
def test_exact_contextual_quote_preserves_source_polarity(text, monkeypatch):
    answer='״'+text+'״ (מקור בדיקה א:א).'
    monkeypatch.setattr(llm,'ask',lambda *a,**k:{'answer':answer})
    result=Agent(sources=[]).ask(Q,retrieved_sources=[source(text)])
    assert result['answer']==answer and result['verdict']=='ok'
    assert result['verification']['support']=='exact-extract-only'

@pytest.mark.parametrize('available', [False,True])
def test_model_refusal_or_outage_explains_missing_evidence(available,monkeypatch):
    def response(*a,**k):
        if not available: raise llm.LLMUnavailable('offline')
        return {'answer':'אין לי מקור לכך.'}
    monkeypatch.setattr(llm,'ask',response)
    assert Agent(sources=[]).ask(Q,retrieved_sources=[source(EXPLICIT)])['answer']==evidence.INSUFFICIENT

def test_empty_store_returns_qualified_answer():
    assert Agent(sources=[]).ask(Q)['answer']==evidence.INSUFFICIENT

@pytest.mark.parametrize('text', ['אסור בשר עם חלב.',EXPLICIT])
def test_web_path_guarded_even_when_model_offline(text,monkeypatch):
    engine=WebResearchEngine()
    monkeypatch.setattr(engine,'research',lambda *a,**k:{'sources':[source(text)],'answer':'unsafe','comparisons':[]})
    monkeypatch.setattr(llm,'ask',lambda *a,**k: (_ for _ in ()).throw(llm.LLMUnavailable('offline')))
    result=engine.answer(Q,'local','qwen')
    assert result['answer']==evidence.INSUFFICIENT

def test_web_rejects_shortened_quote(monkeypatch):
    engine=WebResearchEngine()
    monkeypatch.setattr(engine,'research',lambda *a,**k:{'sources':[source(EXPLICIT)],'answer':'unsafe','comparisons':[]})
    monkeypatch.setattr(llm,'ask',lambda *a,**k:{'answer':'״צריך להמתין שש שעות לפני אכילת חלב.״ (מקור בדיקה א:א).'})
    result=engine.answer(Q,'local','qwen')
    assert result['verification']['verdict']=='insufficient_context'
    assert result['answer']==evidence.INSUFFICIENT

def test_reference_provenance_and_missing_original_not_fabricated():
    if CASE['original_qwen_response'] is None:
        assert CASE['original_response_status']=='awaiting-exact-user-supplied-response'
    else:
        assert CASE['original_qwen_response'].strip()
        assert CASE['original_response_status']=='user-supplied-original'
    assert CASE['reference']['primary_source']['pdf_pages']==[2,4]
    assert all(s['origin'].startswith('synthetic') for s in CASE['synthetic_problematic_responses'])
    from bench.run import load_questions
    assert next(q for q in load_questions() if q['n']==21)['q']==Q

def test_real_qwen_response_preserved_verbatim():
    import hashlib
    original=Path(CASE['original_response_file']).read_bytes()
    assert hashlib.sha256(original).hexdigest()==CASE['original_response_sha256']
    assert original.decode('utf-8').removesuffix('\n')==CASE['original_qwen_response']
    assert CASE['original_response_status']=='user-supplied-original'
    assert 'טיגון משמנת' in CASE['original_qwen_response']
    assert 'בשולי בשר' in CASE['original_qwen_response']
    assert CASE['original_qwen_response'].endswith('בדיני טיגון ומשקאות.')

@pytest.mark.parametrize('text', ['אסור לאכול בשר עם חלב.',EXPLICIT])
def test_real_qwen_failure_never_becomes_local_answer(text,monkeypatch):
    calls=[]
    def generated(*a,**k):
        calls.append(True)
        return {'answer':CASE['original_qwen_response']}
    monkeypatch.setattr(llm,'ask',generated)
    result=Agent(sources=[]).ask(Q,retrieved_sources=[source(text)])
    assert result['answer']==evidence.INSUFFICIENT
    assert bool(calls)==(text==EXPLICIT)
    if calls:
        assert result['verification']['verdict']=='unsupported'


def test_real_qwen_failure_never_becomes_web_answer(monkeypatch):
    engine=WebResearchEngine()
    monkeypatch.setattr(engine,'research',lambda *a,**k:{'sources':[source(EXPLICIT)],'answer':'unsafe','comparisons':[]})
    monkeypatch.setattr(llm,'ask',lambda *a,**k:{'answer':CASE['original_qwen_response']})
    result=engine.answer(Q,'local','qwen')
    assert result['mode']=='web-llm-guarded'
    assert result['answer']==evidence.INSUFFICIENT
    assert result['verification']['verdict']=='unsupported'

@pytest.mark.parametrize('answer', [
    'לפי הרמ״א והגר״א חייבים להמתין שש שעות (מקור בדיקה א:א).',
    'זהו דין טיגון משמנת: ״'+EXPLICIT+'״ (מקור בדיקה א:א).',
    'אפשר להקל בשלושים דקות או שעה, לפי רוב הפוסקים.',
])
def test_specific_unsupported_claims_from_original_are_blocked(answer,monkeypatch):
    monkeypatch.setattr(llm,'ask',lambda *a,**k:{'answer':answer})
    result=Agent(sources=[]).ask(Q,retrieved_sources=[source(EXPLICIT)])
    assert result['mode']=='llm-guarded'
    assert result['answer']==evidence.INSUFFICIENT
