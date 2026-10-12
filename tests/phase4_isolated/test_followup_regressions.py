"""Continuation: synthetic security/context cases, no real rulings or models."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from test_contracts import (sandbox, source, agent, FixedAnswer, Q, TEXT, complete, make_db,
                            quote, request, events, memory, MemoryAgent, backend)
from kezohar import api, evidence
from kezohar.hybrid import rrf_fuse, FederatedSearch
from kezohar.verification import ExtractiveSourceVerifier
from kezohar.answer_composition import VerifiedAnswerComposer
from kezohar.source_snapshot import fingerprint
from kezohar.conversation_state import ConversationConflict

UNIT = 'בדיקת סמל אלפא: רק כאשר דגל בדיקה פעיל, מציגים אלפא; אם כבוי אין להציג.'
FULL = 'הקדמה סינתטית נפרדת.\n' + UNIT + '\nפרק נפרד על סמל ביתא: מציגים ביתא רק כשמצב ביתא פעיל.'


def reviewed(tmp_path, s):
    start = s['text'].index(UNIT)
    unit = {'unit_id': 'synthetic-reviewed-unit', 'source_id': s['source_id'],
            'source_snapshot': fingerprint(s), 'version': s['version'],
            'reference': s['reference'], 'quote': UNIT,
            'start': start, 'end': start + len(UNIT),
            'review': {'status': 'complete-context-reviewed', 'reviewer': 'synthetic-test-reviewer',
                       'rationale': 'Synthetic independent alpha rule; both flag conditions retained.',
                       'essential_conditions': ['דגל פעיל', 'אין להציג כשהדגל כבוי']}}
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps({'rules': [], 'quotation_units': [unit]}, ensure_ascii=False))
    return path, unit


def unit_output(s, text=UNIT, protocol='json'):
    return (json.dumps({'quotes': [{'source_id': s['source_id'], 'quote': text}]}, ensure_ascii=False)
            if protocol == 'json' else '״' + text + '״ (' + s['reference'] + ').')


@pytest.mark.parametrize('protocol', ['json', 'legacy'])
def test_reviewed_short_complete_unit_without_unrelated_long_section(tmp_path, protocol):
    s = source(text=FULL); reviewed(tmp_path, s)
    v = ExtractiveSourceVerifier().verify('סמל אלפא', unit_output(s, protocol=protocol), [s])
    assert v['verdict'] == 'ok' and v['evidence'][0]['quote'] == UNIT
    displayed = VerifiedAnswerComposer().compose({'answer': v.get('rendered_answer', UNIT),
        'verdict': 'ok', 'verification': v, 'sources': [s]})
    assert displayed['structured_answer']['quotations'][0]['text'] == UNIT
    assert displayed['human_review'] == 'required' and not displayed['halachic_verified']


@pytest.mark.parametrize('text', ['מציגים אלפא', UNIT, UNIT.split(';')[0]])
def test_unreviewed_or_condition_truncated_short_units_rejected(text):
    s = source(text=FULL)
    assert ExtractiveSourceVerifier().verify('סמל אלפא', unit_output(s, text), [s])['verdict'] != 'ok'


@pytest.mark.parametrize('change', [
    {'version': 'second-edition'}, {'text': FULL + '\nתנאי נוסף: נדרש דגל גמא.'},
    {'reference': 'בדיקה בלבד ב:ב'}, {'author': 'changed'},
    {'metadata': {'rag_answers_allowed': False}},
    {'metadata': {'rag_answers_allowed': True, 'permission_revision': 'updated'}},
    {'source_id': 'alias'}, {'metadata': {'locator_status': 'ambiguous-file-fields'}}])
def test_short_unit_approval_invalidated_by_any_source_or_permission_change(tmp_path, change):
    s = source(text=FULL); reviewed(tmp_path, s)
    changed = dict(s, **change)
    assert ExtractiveSourceVerifier().verify('סמל אלפא', unit_output(changed), [changed])['verdict'] != 'ok'


@pytest.mark.parametrize('mutation', ['no-review', 'model-review', 'no-reviewer', 'no-rationale',
                                      'no-conditions', 'bad-condition', 'bad-offset', 'duplicate-id'])
def test_incomplete_review_cannot_approve_short_unit(tmp_path, mutation):
    s = source(text=FULL); path, unit = reviewed(tmp_path, s)
    if mutation == 'no-review': unit.pop('review')
    elif mutation == 'model-review': unit['review']['status'] = 'model-says-complete'
    elif mutation == 'no-reviewer': unit['review']['reviewer'] = ''
    elif mutation == 'no-rationale': unit['review']['rationale'] = ''
    elif mutation == 'no-conditions': unit['review'].pop('essential_conditions')
    elif mutation == 'bad-condition': unit['review']['essential_conditions'] = [None]
    elif mutation == 'bad-offset': unit['end'] -= 1
    units = [unit, copy.deepcopy(unit)] if mutation == 'duplicate-id' else [unit]
    path.write_text(json.dumps({'rules': [], 'quotation_units': units}))
    assert ExtractiveSourceVerifier().verify('סמל אלפא', unit_output(s), [s])['verdict'] != 'ok'


@pytest.mark.parametrize('raw', ['{broken', 'null', '[]', '{"quotation_units":null}',
                               '{"rules":{},"quotation_units":[]}',
                               '{"rules":[],"quotation_units":[],"quotation_units":[]}'])
def test_invalid_catalog_does_not_reuse_old_short_quote_approval(tmp_path, raw):
    s = source(text=FULL); path, _ = reviewed(tmp_path, s)
    v = ExtractiveSourceVerifier().verify('סמל אלפא', unit_output(s), [s])
    assert v['verdict'] == 'ok'
    path.write_text(raw)
    assert ExtractiveSourceVerifier().verify('סמל אלפא', unit_output(s), [s])['verdict'] != 'ok'
    r = VerifiedAnswerComposer().compose({'answer': UNIT, 'verification': v, 'sources': [s]})
    assert r['verdict'] == 'invalid_citation' and not r['structured_answer']['quotations']


def test_short_unit_catalog_revocation_invalidates_answer_cache_and_display(tmp_path):
    s = source(text=FULL); path, _ = reviewed(tmp_path, s)
    a = agent([s], FixedAnswer(unit_output(s)))
    first = a.ask('סמל אלפא'); assert first['verdict'] == 'ok'
    assert a.ask('סמל אלפא').get('cached') and len(a.answer_model.calls) == 1
    path.write_text(json.dumps({'rules': [], 'quotation_units': []}))
    second = a.ask('סמל אלפא')
    assert second['verdict'] == 'unsupported' and not second.get('cached')
    assert len(a.answer_model.calls) == 2
    r = VerifiedAnswerComposer().compose(first)
    assert r['verdict'] == 'invalid_citation' and not r['structured_answer']['sources']


def test_review_does_not_approve_further_shortening_or_metadata_self_approval(tmp_path):
    s = source(text=FULL); reviewed(tmp_path, s)
    shortened = UNIT.split(';')[0]
    assert ExtractiveSourceVerifier().verify('סמל אלפא', unit_output(s, shortened), [s])['verdict'] != 'ok'
    (tmp_path / 'catalog.json').write_text(json.dumps({'rules': []}))
    s['metadata']['quotation_units'] = [{'quote': UNIT, 'review': 'approved'}]
    assert ExtractiveSourceVerifier().verify('סמל אלפא', unit_output(s), [s])['verdict'] != 'ok'


@pytest.mark.parametrize('stream', [False, True])
def test_short_reviewed_unit_json_sse_render_same_verified_locator(tmp_path, monkeypatch, stream):
    s = source(text=FULL); reviewed(tmp_path, s)
    a = agent([s], FixedAnswer(unit_output(s))); monkeypatch.setattr(api, '_agent', a)
    response = request('/ask', {'question': 'סמל אלפא', 'stream': stream})
    result = events(response.text)[-1][1] if stream else response.json()
    assert result['verdict'] == 'ok' and not result['halachic_verified']
    assert result['structured_answer']['quotations'][0]['text'] == UNIT
    assert result['structured_answer']['sources'][0]['reference'] == s['reference']


@pytest.mark.parametrize('stream', [False, True])
def test_review_revoked_during_generation_cannot_escape_in_json_or_sse(tmp_path, monkeypatch, stream):
    s = source(text=FULL); path, _ = reviewed(tmp_path, s)
    model = FixedAnswer(unit_output(s), hook=lambda: path.write_text(json.dumps({'rules': []})))
    a = agent([s], model); monkeypatch.setattr(api, '_agent', a)
    response = request('/ask', {'question': 'סמל אלפא', 'stream': stream})
    result = events(response.text)[-1][1] if stream else response.json()
    assert result['verdict'] == 'unsupported' and not result['structured_answer']['quotations']
    assert result['verification_layers']['overall'] == 'not-approved'


@pytest.mark.parametrize('change', [{'version': 'new-edition'}, {'text': TEXT + ' נוסף'},
                                  {'metadata': {'rag_answers_allowed': True, 'permission_revision': 'new'}}])
def test_cached_full_quote_reverified_against_new_source_snapshot(change):
    a = agent(model=FixedAnswer(output=quote(source())))
    assert a.ask('בדיקת מקור סינתטי')['verdict'] == 'ok'
    assert a.ask('בדיקת מקור סינתטי').get('cached')
    for key, value in change.items(): setattr(a.search.bm25.docs[0], key, value)
    r = a.ask('בדיקת מקור סינתטי')
    assert not r.get('cached') and len(a.answer_model.calls) == 2
    if 'text' in change:
        assert r['verdict'] == 'unsupported'
    else:
        assert r['verdict'] == 'ok'  # Fresh verification, never reuse old evidence.
        assert r['verification']['source_snapshots']['s1'] == fingerprint(a.search.bm25.docs[0].to_dict())


@pytest.mark.parametrize('damage', [{'text': TEXT + ' conflict'}, {'version': 'conflict-edition'},
                                  {'metadata': {'rag_answers_allowed': False}}])
def test_collision_quarantines_only_bad_id_and_marks_partial(damage):
    bad = source('bad'); other = dict(bad, **damage); good = source('good')
    fused = rrf_fuse([[bad, good], [other]])
    assert [s['source_id'] for s in fused] == ['good'] and fused.status['partial']
    assert all(e.get('source_id') != 'good' for e in fused.errors)
    a = agent([bad, other, good])
    results = a.search.search('בדיקת מקור סינתטי')
    assert [s['source_id'] for s in results] == ['good'] and results.status['partial']
    assert a.knowledge.source_by_id('bad') is None
    assert a.knowledge.source_by_id('good')['source_id'] == 'good'


@pytest.mark.parametrize('stream', [False, True])
def test_json_sse_partial_collision_keeps_healthy_search_sources_visible(monkeypatch, stream):
    a = agent([source('bad'), source('bad', version='conflict'), source('good')])
    monkeypatch.setattr(api, '_agent', a)
    r = request('/ask', {'question': Q, 'circumstances': complete(), 'stream': stream})
    stream_events = events(r.text) if stream else []
    result = stream_events[-1][1] if stream else r.json()
    assert result['verdict'] == 'partial_search' and result['search_status']['partial']
    visible = stream_events[0][1] if stream else result
    assert visible['search_status']['partial']
    assert {s['source_id'] for s in visible['sources']} == {'good'}
    assert not a.answer_model.calls and not result['halachic_verified']
    search = request('/search', {'query': 'בדיקת מקור סינתטי'}).json()
    assert search['search_status']['partial'] and {s['source_id'] for s in search['results']} == {'good'}
    assert request('/sources/good', method='GET').status_code == 200
    assert request('/sources/bad', method='GET').status_code == 404


def test_failed_federated_backend_does_not_hide_healthy_backend(monkeypatch):
    failed = backend([])
    def fail(*args, **kwargs): raise OSError('synthetic backend unavailable')
    failed.search = fail
    a = agent([source('good')]); a.search = FederatedSearch(a.search, [failed])
    monkeypatch.setattr(api, '_agent', a)
    result = request('/search', {'query': 'בדיקת מקור סינתטי'}).json()
    assert result['search_status']['partial'] and result['search_status']['errors']
    assert {s['source_id'] for s in result['results']} == {'good'}


@pytest.mark.parametrize('owner', ['', ' ', None, 123, 'x' * 257])
def test_invalid_trusted_owner_rejected_on_all_memory_operations(tmp_path, owner):
    store = memory(tmp_path); cid = store.create('victim'); revision, state = store.load('victim', cid)
    for op in (lambda: store.create(owner), lambda: store.load(owner, cid),
               lambda: store.save(owner, cid, revision, state), lambda: store.delete(owner, cid),
               lambda: store.turn(MemoryAgent(), owner, cid, Q)):
        with pytest.raises(ValueError): op()
    assert store.load('victim', cid) == (revision, state)


@pytest.mark.parametrize('attacker', ['other', 'victim ', "victim' OR 1=1 --", 'VICTIM'])
def test_cross_owner_read_update_turn_and_delete_all_blocked(tmp_path, attacker):
    store = memory(tmp_path); cid = store.create('victim'); m = MemoryAgent()
    store.turn(m, 'victim', cid, Q + ' PRIVATE_VICTIM_CONDITION', circumstances=complete())
    before = store.load('victim', cid); count = len(m.calls)
    with pytest.raises(KeyError): store.load(attacker, cid)
    with pytest.raises(ConversationConflict): store.save(attacker, cid, before[0], before[1])
    with pytest.raises(KeyError): store.turn(m, attacker, cid, 'ATTACKER_UPDATE', circumstances=complete())
    assert not store.delete(attacker, cid)
    assert store.load('victim', cid) == before and len(m.calls) == count


def test_concurrent_owners_and_same_owner_conversations_are_independent(tmp_path):
    store = memory(tmp_path); owners = ['owner-a', 'owner-b', 'owner-a']
    cids = [store.create(o) for o in owners]
    def turn(i):
        m = MemoryAgent()
        store.turn(m, owners[i], cids[i], Q + f' PRIVATE_MARKER_{i}', circumstances=complete())
        return store.load(owners[i], cids[i])
    with ThreadPoolExecutor(max_workers=3) as pool:
        states = list(pool.map(turn, range(3)))
    for i, (revision, state) in enumerate(states):
        text = json.dumps(state)
        assert revision == 1 and f'PRIVATE_MARKER_{i}' in text
        assert all(f'PRIVATE_MARKER_{j}' not in text for j in range(3) if j != i)
    assert store.delete('owner-a', cids[0])
    assert store.load('owner-b', cids[1]) == states[1]
    assert store.load('owner-a', cids[2]) == states[2]


def test_loaded_memory_is_not_shared_mutable_state(tmp_path):
    store = memory(tmp_path); cid = store.create('owner'); before = store.load('owner', cid)
    changed = store.load('owner', cid)[1]
    changed['free_conditions'].append('UNSAVED'); changed['user_facts']['injected'] = 'UNSAVED'
    assert store.load('owner', cid) == before
    with pytest.raises(KeyError): store.load('owner', "' OR 1=1 --")


@pytest.mark.parametrize('stream', [False, True])
def test_client_owner_fields_do_not_expose_private_memory_via_api(tmp_path, monkeypatch, stream):
    store = memory(tmp_path); cid = store.create('victim')
    store.turn(MemoryAgent(), 'victim', cid, Q + ' PRIVATE_MEMORY_MARKER', circumstances=complete())
    before = store.load('victim', cid)
    monkeypatch.setattr(api, '_agent', agent())
    response = request('/ask', {'question': Q, 'circumstances': complete(), 'stream': stream,
                               'owner': 'victim', 'conversation_id': cid})
    assert 'PRIVATE_MEMORY_MARKER' not in response.text
    assert store.load('victim', cid) == before
    assert request('/conversations/' + cid, method='GET').status_code == 404


@pytest.mark.parametrize('raw', [b'null', b'42', b'{"question":null,"stream":true}',
    b'{"question":[],"stream":true}', b'{"question":"A","stream":true,"stream":false}',
    b'{"question":"A","stream":true,"circumstances":{"unsupported":"x"}}',
    b'{"question":"A","stream":true,"top_k":false}', b'\xff', b'{"stream":true,'])
def test_malformed_sse_request_returns_json_error_before_any_agent(monkeypatch, raw):
    monkeypatch.setattr(api, 'get_agent', lambda: pytest.fail('malformed SSE reached agent'))
    r = request('/ask', raw=raw)
    assert r.status_code == 400 and r.headers['content-type'].startswith('application/json')
    assert 'event:' not in r.text and not r.json()['halachic_verified']


def test_synthetic_separation_rule_does_not_prove_waiting_rule(monkeypatch):
    # Generic symbols only: this is not execution of T20's real religious fixture.
    s = source(text='סמל אלפא חייב בהפרדה מסמל ביתא, רק כשהדגל פעיל.')
    monkeypatch.setattr(evidence, 'shared_oil_waiting', lambda q: q == 'סמל אלפא TEST_WAITING')
    monkeypatch.setattr(evidence, 'explicit_oil_waiting', lambda text: 'EXPLICIT_WAITING_PROOF' in text)
    v = ExtractiveSourceVerifier()
    assert v.eligible_sources('סמל אלפא TEST_WAITING', [s]) == []
    assert v.verify('סמל אלפא TEST_WAITING', quote(s), [s])['verdict'] == 'insufficient_context'
    for output in ('UNSUPPORTED_FIRM_RULING', 'INVENTED_TERM (UNLOCATED_AUTHORITY)',
                   json.dumps({'quotes': [{'source_id': 'invented', 'quote': s['text']}]})):
        assert v.verify('סמל אלפא', output, [s])['verdict'] != 'ok'

@pytest.mark.parametrize('protocol', ['json', 'legacy'])
def test_catalog_change_between_quote_check_and_snapshot_binding_fails_closed(tmp_path, monkeypatch, protocol):
    from kezohar import citations
    s = source(text=FULL); path, _ = reviewed(tmp_path, s)
    name = 'verify_source_id_answer' if protocol == 'json' else 'verify_extractive_answer'
    original = getattr(citations, name)
    def change_after_check(*args, **kwargs):
        result = original(*args, **kwargs)
        assert result['verdict'] == 'ok'
        path.write_text(json.dumps({'rules': []}))
        return result
    monkeypatch.setattr(citations, name, change_after_check)
    v = ExtractiveSourceVerifier().verify('סמל אלפא', unit_output(s, protocol=protocol), [s])
    assert v['verdict'] != 'ok'
    result = VerifiedAnswerComposer().compose({'answer': 'אין בסיס מאומת.', 'verification': v, 'sources': [s]})
    assert not result['structured_answer']['quotations'] and not result['halachic_verified']

# The private demo uses the same guards with a longer per-request time budget.
def demo_request(path, body=None, headers=None, method='POST'):
    import asyncio, httpx
    from kezohar.demo import app
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://127.0.0.1:8711') as client:
            return await client.request(method, path, json=body, headers=headers)
    return asyncio.run(run())

@pytest.mark.parametrize('headers', [{'host':'evil.invalid'}, {'origin':'https://evil.invalid'},
                                    {'origin':'http://localhost:8711'}])
def test_private_demo_rejects_foreign_origin_and_host_before_agent(monkeypatch, headers):
    monkeypatch.setattr(api, 'get_agent', lambda: pytest.fail('foreign page reached agent'))
    assert demo_request('/demo/ask', {'question':Q}, headers).status_code == 403


def test_private_demo_uses_real_pipeline_with_mock_provider_and_no_old_cache(monkeypatch):
    a = agent(); monkeypatch.setattr(api,'_agent',a)
    for _ in range(2):
        r = demo_request('/demo/ask', {'question':Q,'circumstances':complete()}).json()
        assert r['verdict']=='ok' and r['demo_model_calls']==1 and not r['halachic_verified']
        assert 4.5 < a.answer_model.calls[-1][2] <= 45
    assert len(a.answer_model.calls)==2
    assert demo_request('/api/sources/s1', method='GET').status_code==200
    assert demo_request('/api/research', {'question':Q}).status_code==404


@pytest.mark.parametrize('body', [{'question':Q,'stream':True}, {'question':Q,'research':True},
                                  {'question':None}, {'question':Q,'top_k':False}])
def test_private_demo_invalid_input_rejected_without_generation(monkeypatch, body):
    monkeypatch.setattr(api,'get_agent',lambda:pytest.fail('invalid demo reached agent'))
    assert demo_request('/demo/ask',body).status_code==400


def test_ruling_calendar_mention_is_not_a_fast_date_answer():
    from kezohar.fastpath import is_fast_question
    assert not is_fast_question('שכחתי לומר יעלה ויבוא בראש חודש — האם חוזרים?')
    assert is_fast_question('מה התאריך העברי היום?')


def test_missing_prayer_service_and_soup_details_are_not_inferred():
    from kezohar.question_understanding import analyze
    p = analyze('שכחתי לומר יעלה ויבוא בראש חודש — האם חוזרים?')
    assert p['requires_clarification'] and p['missing_fields']==['prayer_service','prayer_stage']
    s = analyze('האם מותר לחמם בשבת מרק שהתקרר?')
    assert s['requires_clarification'] and set(s['missing_fields'])=={'soup_cooked','soup_temperature','reheating_method'}

@pytest.mark.parametrize('ids', [[], ['s1','s1'], ['s1','x','y'], 's1', [True], [' s1'], ['missing']])
def test_source_selection_rejects_invalid_duplicate_or_unretrieved_ids(ids):
    packet=json.dumps({'selected_sources':ids})
    assert ExtractiveSourceVerifier().verify('בדיקת מקור',packet,[source()])['verdict']!='ok'


def test_source_selection_cannot_add_prose_claims_or_crop_conditions():
    s=source(text='בדיקת מקור: רק אם דגל אלפא פעיל. אם כבוי אין להציג את הסמל.')
    packet=json.dumps({'selected_sources':['s1']})
    v=ExtractiveSourceVerifier().verify('בדיקת מקור',packet,[s])
    assert v['verdict']=='ok' and v['evidence'][0]['quote']==s['text']
    assert v['support']=='source-selection-whole-unit-reading' and not v['halachic_verified']
    for extra in ({'answer':'UNSUPPORTED'}, {'quotes':[]}, {'conditions':[]}):
        assert ExtractiveSourceVerifier().verify('בדיקת מקור',json.dumps({'selected_sources':['s1'],**extra}),[s])['verdict']!='ok'


@pytest.mark.parametrize('change', [{'version':'changed'},{'metadata':{'rag_answers_allowed':False}},
                                  {'text':TEXT+' CONDITION_ADDED'}])
def test_source_selection_still_revalidates_snapshot_after_generation(change):
    a=agent(model=FixedAnswer(json.dumps({'selected_sources':['s1']})))
    def mutate():
        for key,value in change.items():setattr(a.search.bm25.docs[0],key,value)
    a.answer_model.hook=mutate
    r=a.converse(Q,circumstances=complete())
    assert r['verdict']=='invalid_citation' and not r['structured_answer']['quotations']


def test_focused_disk_retrieval_preserves_rare_subject_and_action(tmp_path):
    from kezohar.ranking import retrieval_query
    good=source('good',text='בדיקה סינתטית: לא יפסיק בדיבור בין תפלה של יד לתפלה של ראש, כאשר דגל אלפא פעיל.')
    noise=[source(str(i),text='בדיקה סינתטית: ראש יד תפילין ראש יד תפילין מידע כללי.') for i in range(12)]
    db=make_db(tmp_path,noise+[good])
    rows=__import__('kezohar.library_search',fromlist=['SQLiteLibrarySearch']).SQLiteLibrarySearch(db).search(
        retrieval_query('האם מותר לדבר בין תפילין של יד לתפילין של ראש?'),top_k=1)
    assert [s['source_id'] for s in rows]==['good']


def test_complete_concept_match_not_displaced_by_diversity():
    from kezohar.agent import diverse_sources,order_sources
    exact=source('exact',text='בדיקה סינתטית: יפסיק בדיבור בין תפלה של יד לתפלה של ראש.')
    extra=source('extra',text=exact['text']); extra['work_title']=exact['work_title']
    tangential=source('tangential',work_title='ספר אחר',text='ראש ויד בלבד בבדיקה.')
    ordered=order_sources([tangential,exact,extra],'האם מותר לדבר בין תפילין של יד לתפילין של ראש?')
    assert {s['source_id'] for s in diverse_sources(ordered,2)}=={'exact','extra'}


def test_blessing_table_requires_stage_and_never_proves_last_blessing_conditions():
    s=source(text='אלפא – העץ / נפשות.',reference='לוח ברכות סינתטי א:א')
    v=ExtractiveSourceVerifier()
    packet=json.dumps({'selected_sources':['s1']})
    assert v.verify('מה מברכים על אלפא?',packet,[s])['verdict']=='insufficient_context'
    assert v.verify('מה מברכים על אלפא? ברכה אחרונה, נאכל כזית בתוך כדי אכילת פרס',packet,[s])['verdict']=='insufficient_context'
    passed=v.verify('מה מברכים על אלפא? ברכה ראשונה',packet,[s])
    assert passed['verdict']=='ok'
    r=VerifiedAnswerComposer().compose({'answer':'old','verification':passed,'sources':[s]})
    assert 'הברכה הראשונה על אלפא' in r['answer'] and 'לא אומתו' in r['answer']
    assert not r['structured_answer']['table_readings'][0]['after_blessing_case_verified']


def test_unknown_circumstance_stops_instead_of_clarification_loop():
    a=agent()
    r=a.converse('מה מברכים על אלפא?',circumstances={'blessing_stage':'unknown'})
    assert not r.get('clarifications') and not r['halachic_verified']
    assert r['answer_policy']['missing_case_fields']==['blessing_stage']
    assert r['question_analysis']['unable_to_clarify']==['blessing_stage']


def test_blessing_clarification_is_bounded_and_separates_before_from_after():
    from kezohar.question_understanding import analyze
    q='מה מברכים על אלפא?'
    assert analyze(q)['missing_fields']==['blessing_stage']
    assert not analyze(q,{'blessing_stage':'before'})['requires_clarification']
    after=analyze(q,{'blessing_stage':'after'})
    assert set(after['missing_fields'])=={'food_amount','eating_time'}


def test_source_selection_layer_separates_format_from_missing_identity():
    v=ExtractiveSourceVerifier().verify('בדיקת מקור',json.dumps({'selected_sources':['missing']}),[source()])
    assert v['verdict']=='invalid_citation' and v['checks']['format']=='passed'
    assert v['checks']['source_exists']=='failed'


def test_after_blessing_cannot_use_unconditional_non_table_excerpt():
    s=source(text='אלפא: ברכה אחרונה היא נפשות.')
    r=ExtractiveSourceVerifier().verify('מה מברכים על אלפא? ברכה אחרונה',json.dumps({'selected_sources':['s1']}),[s])
    assert r['verdict']=='insufficient_context' and not r['halachic_verified']


def test_niqqud_does_not_hide_embedded_other_views():
    from kezohar.halachic_authority import profile
    s=source(text='בדיקת מקור. הַגָּה: דעה נוספת בבדיקה בלבד.')
    assert profile(s)['embedded_other_views']


def test_condition_in_table_last_column_is_not_lost_in_first_column_projection():
    s=source(text='אלפא – העץ / נפשות, רק אם דגל הבדיקה פעיל.',reference='לוח ברכות סינתטי א:א')
    v=ExtractiveSourceVerifier().verify('מה מברכים על אלפא? ברכה ראשונה',json.dumps({'selected_sources':['s1']}),[s])
    assert v['verdict']=='ok'
    r=VerifiedAnswerComposer().compose({'answer':v['rendered_answer'],'verification':v,'sources':[s]})
    assert s['text'] in r['answer'] and r['structured_answer']['table_readings'][0]['has_conditions']

# No actual law or production corpus in these cases.
RULE_TEXT='בדיקת סמל אלפא: כל זמן שאינו אדום מחמת דגל הבדיקה ומשעה שהשתנה הדגל אין להציג אלפא. תנאי נוסף: רק בבדיקת יחידה.'

def rule_result(s=None,q='בדיקת סמל אלפא',answers=None):
    s=s or source(text=RULE_TEXT)
    v=ExtractiveSourceVerifier().verify(q,json.dumps({'selected_sources':['s1']}),[s])
    return VerifiedAnswerComposer().compose({'answer':v.get('rendered_answer',''),'verdict':v['verdict'],
        'verification':v,'sources':[s]},question=q,rule_answers=answers)

def test_rule_shown_before_case_detail_and_whole_conditions_retained():
    r=rule_result()
    assert r['verdict']=='rule_needs_clarification' and r['verification']['verdict']=='ok'
    assert 'תנאי נוסף' in r['answer'] and 'משעה' in r['answer']
    assert r['structured_answer']['quotations'][0]['text']==RULE_TEXT
    assert r['answer_status']['category']=='rule_needs_details'
    assert not r['known_rule_context']['case_ruling_verified']

@pytest.mark.parametrize('value',['yes','no','unknown'])
def test_reported_source_condition_is_not_a_ruling_or_infinite_loop(value):
    first=rule_result();key=first['clarifications'][0]['condition_id']
    r=rule_result(answers={key:value})
    assert not r.get('clarifications') and not r['halachic_verified']
    assert r['known_rule_context']['conditions'][0]['reported_value']==value
    assert 'תנאי נוסף' in r['answer']

@pytest.mark.parametrize('change',[{'text':RULE_TEXT+' שינוי'}, {'version':'edition-two'}, {'reference':'בדיקה ב:א'}])
def test_source_bound_answer_never_reused_after_change(change):
    key=rule_result()['clarifications'][0]['condition_id']
    s=source(text=RULE_TEXT);s.update(change)
    r=rule_result(s,answers={key:'no'})
    assert r['known_rule_context']['stale_answers'] and r.get('clarifications')
    assert r['known_rule_context']['conditions'][0]['reported_value'] is None

def test_source_condition_cannot_be_reused_for_different_question_or_other_session():
    key=rule_result()['clarifications'][0]['condition_id']
    assert rule_result(q='בדיקת סמל אלפא נוספת',answers={key:'no'})['known_rule_context']['stale_answers']
    assert rule_result()['known_rule_context']['conditions'][0]['reported_value'] is None

@pytest.mark.parametrize('bad',[[], {'bad':'yes'}, {'a'*32:'maybe'}, {'a'*32:True}])
def test_rule_answers_validated_before_inference(bad):
    a=agent()
    with pytest.raises(ValueError):a.converse(Q,rule_answers=bad)
    assert not a.answer_model.calls

@pytest.mark.parametrize('change',[{'metadata':{'rag_answers_allowed':False}},{'version':'edition-two'},{'text':RULE_TEXT+' changed'}])
def test_changed_source_cannot_enter_language_layer(change):
    s=source(text=RULE_TEXT)
    v=ExtractiveSourceVerifier().verify('בדיקת סמל אלפא',json.dumps({'selected_sources':['s1']}),[s])
    s.update(change)
    r=VerifiedAnswerComposer().compose({'verdict':'ok','verification':v,'sources':[s]},question='בדיקת סמל אלפא')
    assert not r.get('known_rule_context') and not r['structured_answer']['explanations']

@pytest.mark.parametrize('text,code',[(RULE_TEXT.split(' ומשעה')[0],'incomplete-quote-unit'),('ניסוח שלא קיים','quote-text-mismatch')])
def test_quote_failure_explains_exact_reason(text,code):
    s=source(text=RULE_TEXT)
    # Legacy protocol also remains fail-closed; JSON gives exact mismatch code.
    v=ExtractiveSourceVerifier().verify('בדיקת סמל אלפא',json.dumps({'quotes':[{'source_id':'s1','quote':text}]}),[s])
    assert v['verdict']=='unsupported' and v['support']==code
    r=VerifiedAnswerComposer().compose({'verdict':'unsupported','verification':v,'sources':[s]})
    assert r['answer_status']['category']=='quotation_mismatch' and 'אין לי מקור לכך' not in r['answer']

def test_rule_status_and_context_survive_sse():
    r=rule_result();done=list(events(''.join(api._sse_events(r))))[-1]
    assert done[1]['answer_status']==r['answer_status']
    assert done[1]['known_rule_context']==r['known_rule_context']

@pytest.mark.parametrize('verdict,sources,category',[
    ('no_source',[],'no_relevant_source'),('no_source',[source()],'insufficient_evidence'),
    ('unsupported',[],'unsupported_claim'),('invalid_citation',[],'source_identity_or_permission'),
    ('sources-only',[],'technical_error'),('irrelevant',[source()],'no_relevant_source')])
def test_failure_categories_are_distinct(verdict,sources,category):
    r=VerifiedAnswerComposer().compose({'verdict':verdict,'sources':sources})
    assert r['answer_status']['category']==category and not r['halachic_verified']

def test_old_case_payload_is_removed_when_permission_changes():
    r=rule_result();r['sources'][0]['metadata']['rag_answers_allowed']=False
    new=VerifiedAnswerComposer().compose(r,question='בדיקת סמל אלפא')
    assert not new.get('known_rule_context') and not new.get('clarifications')
    assert not new['structured_answer']['quotations']

def test_budget_stop_never_replaced_by_source_explanation():
    r=rule_result();r.update(verdict='budget_exhausted',answer='מגבלת זמן')
    new=VerifiedAnswerComposer().compose(r,question='בדיקת סמל אלפא')
    assert new['answer']=='מגבלת זמן' and not new.get('known_rule_context')

def test_style_policy_update_invalidates_existing_proof(monkeypatch):
    from kezohar import source_rules
    r=rule_result()
    monkeypatch.setattr(source_rules,'STYLE',source_rules.STYLE+(('אלפא','ביתא'),))
    new=VerifiedAnswerComposer().compose(r,question='בדיקת סמל אלפא')
    assert new['verdict']=='invalid_citation' and not new.get('known_rule_context')

def test_source_condition_roundtrip_normal_http_and_sse(monkeypatch):
    a=agent([source(text=RULE_TEXT)],FixedAnswer(json.dumps({'selected_sources':['s1']})))
    monkeypatch.setattr(api,'get_agent',lambda:a)
    q='בדיקת סמל אלפא'
    normal=request('/ask',{'question':q}).json()
    streamed=events(request('/ask',{'question':q,'stream':True}).text)
    done=streamed[-1][1]
    assert done['answer_status']==normal['answer_status']
    assert done['known_rule_context']==normal['known_rule_context']
    assert not normal.get('clarifications') and normal['answer_policy']['conditional_source_reading']
    key=normal['known_rule_context']['conditions'][0]['condition_id']
    follow=request('/ask',{'question':q,'rule_answers':{key:'unknown'}}).json()
    assert not follow.get('clarifications') and not follow['halachic_verified']
    bad=request('/ask',{'question':q,'stream':True,'rule_answers':{'bad':'yes'}})
    assert bad.status_code==400 and 'event: answer' not in bad.text

# Answer-first policy: facts never become evidence, nor bypass source guards.
@pytest.mark.parametrize('question',[
    'מה מברכים על אלפא?',
    'האם מותר לחמם בשבת מרק אלפא?',
    'שכחתי לומר יעלה ויבוא בראש חודש אלפא',
    'מתי מברכים ברכת המזון אלפא?',
])
def test_answer_first_retrieves_before_missing_fact_decision(monkeypatch,question):
    s=source(text=question+' בדיקה סינתטית: אם דגל אלפא פעיל מציגים אלפא, ואם כבוי אין להציג אלפא.')
    a=agent([s],FixedAnswer(json.dumps({'selected_sources':['s1']})))
    searched=[]
    monkeypatch.setattr(a,'search_only',lambda q,**kw:searched.append(q) or [s])
    r=a.converse(question)
    assert searched and not r.get('clarifications') and not r['halachic_verified']
    assert r['answer_policy']['search_before_clarification']
    if r['verification'].get('verdict')=='ok':
        assert s['text'] in r['structured_answer']['quotations'][0]['text']
        assert 'אם כבוי' in r['answer']


def test_conditional_duration_rule_does_not_force_personal_intake():
    a=agent([source(text=RULE_TEXT)],FixedAnswer(json.dumps({'selected_sources':['s1']})))
    r=a.converse('בדיקת סמל אלפא')
    assert not r.get('clarifications') and r['verification']['verdict']=='ok'
    assert 'משעה' in r['answer'] and 'תנאי נוסף' in r['answer']
    assert not r['known_rule_context']['case_ruling_verified']


def test_unspecified_blessing_scope_is_not_an_assumed_user_fact():
    a=agent([source(text='אלפא – העץ / נפשות.',reference='לוח ברכות בדיקה א:א')],
            FixedAnswer(json.dumps({'selected_sources':['s1']})))
    r=a.converse('מה מברכים על אלפא?')
    assert not r.get('clarifications') and r['verification']['verdict']=='ok'
    assert 'blessing_stage' not in r['question_analysis']['circumstances']
    assert 'הברכה הראשונה על אלפא' in r['answer'] and 'לא אומתו' in r['answer']
    assert not r['structured_answer']['table_readings'][0]['after_blessing_case_verified']

@pytest.mark.parametrize('slots',[{}, {'blessing_stage':'after'}, {'blessing_stage':'both','food_amount':'at_least_kezayit','eating_time':'within_pras'}])
def test_table_cannot_issue_after_blessing_ruling_even_after_clarification(slots):
    a=agent([source(text='אלפא – העץ / נפשות.',reference='לוח ברכות בדיקה א:א')],
            FixedAnswer(json.dumps({'selected_sources':['s1']})))
    q='מה הברכה האחרונה על אלפא?'
    r=a.converse(q,circumstances=slots)
    assert r['verification']['verdict']=='insufficient_context'
    assert not r['structured_answer']['quotations'] and not r['halachic_verified']

@pytest.mark.parametrize('target',['',' לפני אכילת חלב'])
def test_missing_dairy_target_never_disables_shared_oil_waiting_guard(target):
    q='האם צריך להמתין שש שעות אחרי ציפס שטוגן בשמן שבו טוגנו שניצלים'+target+'?'
    s=source(text='בדיקה סינתטית: בשר וחלב אין לאכול יחד. אחרי בשר יש להמתין שש שעות. שמן ושניצלים וציפס נזכרים כאן רק ברשימה.')
    a=agent([s],FixedAnswer(json.dumps({'selected_sources':['s1']})))
    r=a.converse(q)
    assert r['verdict']=='insufficient_context' and not a.answer_model.calls
    assert not r['structured_answer']['quotations'] and not r.get('clarifications')


def test_neighbouring_physical_action_cannot_answer_explicit_speech_question():
    s=source(text='בדיקה סינתטית: אין להפסיק במעשה בין תפילין של יד לתפילין של ראש. מעשה הוא כמו דיבור.')
    q='האם מותר לדבר בין תפילין של יד לתפילין של ראש?'
    v=ExtractiveSourceVerifier().verify(q,json.dumps({'selected_sources':['s1']}),[s])
    assert v['verdict'] in ('irrelevant','insufficient_context')
    a=agent([s],FixedAnswer(json.dumps({'selected_sources':['s1']})))
    r=a.converse(q)
    assert not a.answer_model.calls and not r['structured_answer']['quotations']


def test_one_conflict_question_after_rules_preserves_both_facts_and_no_case_ruling():
    a=agent([source()],FixedAnswer(json.dumps({'selected_sources':['s1']})))
    r=a.converse(Q+' לא מבושל',circumstances={'rice_form':'cooked'})
    assert r['verification']['verdict']=='ok' and len(r['clarifications'])==1
    assert r['question_analysis']['conflicting_fields']==['rice_form']
    assert not r['answer_policy']['personal_ruling_verified']
    assert r['structured_answer']['quotations']


def test_budget_failure_cannot_be_disguised_as_conflict_clarification():
    from kezohar.request_budget import RequestBudget
    a=agent([source()],FixedAnswer(json.dumps({'selected_sources':['s1']})))
    r=a.converse(Q+' לא מבושל',circumstances={'rice_form':'cooked'},request_budget=RequestBudget(max_calls=0))
    assert r['verdict']=='budget_exhausted' and not r.get('clarifications')


def test_source_absence_never_generates_a_case_question_or_a_rule(monkeypatch):
    a=agent();monkeypatch.setattr(a,'search_only',lambda *a,**kw:[])
    r=a.converse('האם מותר לחמם מרק בשבת?')
    assert r['verdict']=='no_source' and not r.get('clarifications')
    assert not r['structured_answer']['quotations'] and not a.answer_model.calls

@pytest.mark.parametrize('statement',[
    'בדיקה סינתטית: אסור להפסיק בדיבור בין תפילין של יד לתפילין של ראש כאשר דגל אלפא פעיל.',
    'בדיקה סינתטית: מותר להפסיק בדיבור בין תפילין של יד לתפילין של ראש כאשר דגל אלפא פעיל.',
])
def test_action_coverage_checks_subject_not_predetermined_ruling(statement):
    s=source(text=statement)
    v=ExtractiveSourceVerifier().verify('האם מותר לדבר בין תפילין של יד לתפילין של ראש?',
                                      json.dumps({'selected_sources':['s1']}),[s])
    assert v['verdict']=='ok' and v['evidence'][0]['quote']==statement
    assert not v['halachic_verified']

@pytest.mark.parametrize('answer',['yes','no','unknown'])
def test_answered_conflict_confirmation_is_not_repeated_or_a_case_ruling(answer):
    a=agent([source()],FixedAnswer(json.dumps({'selected_sources':['s1']})))
    q=Q+' לא מבושל';slots={'rice_form':'cooked'}
    first=a.converse(q,circumstances=slots);key=first['clarifications'][0]['condition_id']
    follow=a.converse(q,circumstances=slots,rule_answers={key:answer})
    assert not follow.get('clarifications')
    assert follow['answer_policy']['conflict_confirmation']['reported_answer']==answer
    assert not follow['answer_policy']['personal_ruling_verified']
    stale=a.converse(q+' נסיבה אחרת',circumstances=slots,rule_answers={key:answer})
    assert len(stale['clarifications'])==1 and stale['clarifications'][0]['condition_id']!=key


def test_memory_retains_answered_confirmation_without_repeating_or_guessing(tmp_path):
    a=agent([source()],FixedAnswer(json.dumps({'selected_sources':['s1']})))
    store=memory(tmp_path);cid=store.create('alice')
    store.turn(a,'alice',cid,Q+' לא מבושל',circumstances={'rice_form':'raw'})
    asked=store.turn(a,'alice',cid,'TEST_CORRECTION',circumstances={'rice_form':'cooked'})
    key=asked['clarifications'][0]['condition_id']
    confirmed=store.turn(a,'alice',cid,'TEST_CONFIRM',rule_answers={key:'yes'})
    assert not confirmed.get('clarifications')
    follow=store.turn(a,'alice',cid,'TEST_NEXT')
    assert not follow.get('clarifications') and not follow['halachic_verified']
    assert follow['answer_policy']['conflict_confirmation']['reported_answer']=='yes'
    state=store.load('alice',cid)[1]
    assert state['user_facts']=={'rice_form':'cooked'}
    assert all(text in a.answer_model.calls[-1][0] for text in ('TEST_CORRECTION','TEST_CONFIRM','TEST_NEXT'))
    before=len(a.answer_model.calls)
    with pytest.raises(KeyError):store.turn(a,'bob',cid,'TEST_CONFIRM',rule_answers={key:'yes'})
    assert len(a.answer_model.calls)==before


def test_confirmation_memory_is_separate_for_other_conversation_and_new_case(tmp_path):
    a=agent([source()],FixedAnswer(json.dumps({'selected_sources':['s1']})))
    store=memory(tmp_path);cid=store.create('alice');other=store.create('bob')
    slots={'rice_form':'cooked'};q=Q+' לא מבושל'
    asked=store.turn(a,'alice',cid,q,circumstances=slots);key=asked['clarifications'][0]['condition_id']
    store.turn(a,'alice',cid,'TEST_CONFIRM',rule_answers={key:'yes'})
    bob=store.turn(a,'bob',other,q,circumstances=slots)
    assert len(bob['clarifications'])==1 and not store.load('bob',other)[1]['clarification_answers']
    store.turn(a,'alice',cid,Q+' NEW_CASE',circumstances=complete())
    assert store.load('alice',cid)[1]['clarification_answers']=={}


def test_scope_boilerplate_does_not_make_unrelated_source_relevant_for_ranking():
    from kezohar.ranking import topic_tokens,retrieval_query
    q='מה מברכים על אלפא?'
    scoped=q+'\nתחום המענה הכללי ברכה ראשונה בלבד; נסיבות אכילה מקור אחר.'
    assert topic_tokens(q)==topic_tokens(scoped)
    assert str(retrieval_query(q))==str(retrieval_query(scoped))


def test_prompt_does_not_fill_remaining_slots_with_partial_subject_matches():
    from kezohar.agent import diverse_sources,order_sources
    exact=source('exact',text='בדיקת סמל אלפא ביתא גמא: אם דגל פעיל מציגים אלפא.')
    partial=source('partial',text='בדיקה סינתטית גמא בלבד; אין כאן שאר נושאי השאלה.')
    ordered=order_sources([partial,exact],'בדיקת סמל אלפא ביתא גמא')
    assert [s['source_id'] for s in diverse_sources(ordered,5)]==['exact']


def test_generic_request_verbs_do_not_hide_meal_blessing_subject():
    from kezohar.ranking import concept_groups,topic_tokens
    q='שכחתי לברך ברכת המזון, מה עושים?'
    assert 'עושימ' not in topic_tokens(q)
    assert not any('עושימ' in g for g in concept_groups(q))


def test_no_complete_subject_match_retains_lexical_candidates_for_verification():
    from kezohar.agent import diverse_sources,order_sources
    partial=source('partial',text='בדיקה סינתטית אלפא בלבד, יחידה שלמה.')
    ordered=order_sources([partial],'בדיקה סינתטית אלפא ביתא גמא')
    assert [s['source_id'] for s in diverse_sources(ordered,5)]==['partial']


def test_model_cannot_use_response_scope_words_as_source_relevance():
    q='בדיקת סמל אלפא'+'\nתחום מענה: כשרות ובשר וחלב וכללי אכילה.'
    s=source(text='מקור אחר סינתטי על כשרות ובשר וחלב וכללי אכילה; אין בו הקשר מתאים.')
    v=ExtractiveSourceVerifier().verify(q,json.dumps({'selected_sources':['s1']}),[s])
    assert v['verdict']=='irrelevant' and not v['halachic_verified']


def test_muktzeh_movement_is_not_ownership_of_found_money():
    s=source(text='בדיקה סינתטית: המוצא כסף בשבת רשאי להזיז אותו ברגלו ולהניחו במקום אחר.')
    v=ExtractiveSourceVerifier().verify('מצאתי כסף ברחוב, האם מותר לי לקחת?',json.dumps({'selected_sources':['s1']}),[s])
    assert v['verdict'] in ('irrelevant','insufficient_context')


def test_bathing_time_does_not_establish_immersion_time():
    s=source(text='בדיקה סינתטית: נכון לטבול לכבוד שבת. אחר כך יש להתרחץ ביום שישי.')
    v=ExtractiveSourceVerifier().verify('האם מותר לטבול ביום?',json.dumps({'selected_sources':['s1']}),[s])
    assert v['verdict'] in ('irrelevant','insufficient_context')


def test_ambiguous_immersion_action_asks_one_after_search_and_stops_on_unknown(monkeypatch):
    a=agent();seen=[];monkeypatch.setattr(a,'search_only',lambda q,**kw:seen.append(q) or [])
    r=a.converse('האם מותר לטבול ביום?')
    assert seen and len(r['clarifications'])==1 and not r['halachic_verified']
    unknown=a.converse('האם מותר לטבול ביום?',circumstances={'immersion_purpose':'unknown'})
    assert not unknown.get('clarifications')


def test_clear_blessing_name_is_scoped_to_unconditional_first_column():
    s=source(text='אלפא – העץ / נפשות.',reference='לוח ברכות בדיקה א:א')
    a=agent([s],FixedAnswer(json.dumps({'selected_sources':['s1']})))
    r=a.converse('מה מברכים על אלפא?')
    assert 'הברכה הראשונה על אלפא היא ״בורא פרי העץ״' in r['answer']
    assert 'תנאי החיוב לא אומתו' in r['answer']
    assert r['structured_answer']['quotations'][0]['text']==s['text']
    assert not r['halachic_verified']


def test_sentence_layout_keeps_all_conditions_and_original_quote():
    s=source(text='בדיקה סינתטית אלפא: רק אם דגל פעיל מותר אלפא. אם דגל כבוי אסור אלפא. גם תנאי ביתא נדרש.')
    a=agent([s],FixedAnswer(json.dumps({'selected_sources':['s1']})))
    r=a.converse('בדיקה סינתטית אלפא')
    text=r['known_rule_context']['rules'][0]['text']
    assert '\n\n' in text and ' '.join(text.split())==s['text']
    assert r['structured_answer']['quotations'][0]['text']==s['text']


def test_column_name_policy_change_invalidates_previous_display_proof(monkeypatch):
    from kezohar import blessing_context
    s=source(text='אלפא – העץ / נפשות.',reference='לוח ברכות בדיקה א:א')
    v=ExtractiveSourceVerifier().verify('מה מברכים על אלפא? ברכה ראשונה',json.dumps({'selected_sources':['s1']}),[s])
    monkeypatch.setitem(blessing_context.FIRST_NAMES,'העץ','כותרת שונה בבדיקה')
    r=VerifiedAnswerComposer().compose({'verdict':'ok','verification':v,'sources':[s]})
    assert r['verdict']=='invalid_citation' and not r['structured_answer'].get('table_readings')


def test_conditional_column_cannot_be_shortened_to_a_blessing_name():
    s=source(text='אלפא – העץ רק אם דגל פעיל / נפשות.',reference='לוח ברכות בדיקה א:א')
    v=ExtractiveSourceVerifier().verify('מה מברכים על אלפא? ברכה ראשונה',json.dumps({'selected_sources':['s1']}),[s])
    r=VerifiedAnswerComposer().compose({'verdict':'ok','verification':v,'sources':[s]})
    assert s['text'] in r['answer'] and not r['structured_answer']['table_readings'][0]['first_blessing_name']


def test_reference_notes_are_not_split_into_ordinary_rule_paragraphs():
    from kezohar.source_rules import explain
    note='[בדיקה א. בדיקה ב. בדיקה ג.]'
    s=source(text='בדיקת סמל אלפא. אם דגל פעיל מציגים אלפא. '+note)
    rendered=explain(s)
    assert note in rendered and '\n\n' in rendered
    assert 'אם דגל פעיל' in rendered


def test_retrieval_cache_resolves_current_source_and_never_stores_text(monkeypatch):
    a=agent();calls=[];original=a.search.search
    monkeypatch.setattr(a.search,'search',lambda *args,**kw:calls.append(1) or original(*args,**kw))
    first=a.search_only(Q,cache_namespace='alice');second=a.search_only(Q,cache_namespace='alice')
    assert len(calls)==1 and second.metrics['cache_hit']
    first[0]['text']='PRIVATE_USER_MODIFICATION'
    third=a.search_only(Q,cache_namespace='alice')
    assert third[0]['text']==source()['text']
    encoded=json.dumps(list(a.retrieval_cache.entries.items()))
    assert Q not in encoded and source()['text'] not in encoded and 'PRIVATE_USER_MODIFICATION' not in encoded

@pytest.mark.parametrize('change',[{'version':'new-edition'},{'text':TEXT+' שינוי'},{'metadata':{'rag_answers_allowed':False}}])
def test_retrieval_cache_never_returns_old_edition_text_or_grant(change):
    a=agent();old=a.search_only(Q,cache_namespace='alice')
    for k,v in change.items():setattr(a.search.bm25.docs[0],k,v)
    fresh=a.search_only(Q,cache_namespace='alice')
    assert not fresh.metrics['cache_hit'] and fresh
    for k,v in change.items():assert fresh[0][k]==v
    if 'metadata' in change:
        from kezohar.source_snapshot import public_sources
        assert public_sources(fresh)[0]['text']==''


def test_retrieval_cache_disabled_without_trusted_namespace_and_separate_for_owners():
    a=agent()
    assert not a.search_only(Q).metrics['cache_hit']
    assert not a.search_only(Q).metrics['cache_hit']
    assert not a.search_only(Q,cache_namespace='alice').metrics['cache_hit']
    assert not a.search_only(Q,cache_namespace='bob').metrics['cache_hit']
    assert a.search_only(Q,cache_namespace='alice').metrics['cache_hit']
    assert not a.search_only(Q+' PRIVATE_OTHER_CASE',cache_namespace='alice').metrics['cache_hit']


def test_retrieval_cache_expiry_and_capacity_are_bounded(monkeypatch):
    a=agent();now=[10.0];monkeypatch.setattr('kezohar.retrieval_cache.time.monotonic',lambda:now[0])
    a.retrieval_cache.ttl=1;a.retrieval_cache.capacity=2
    a.search_only(Q,cache_namespace='alice');now[0]+=2
    assert not a.search_only(Q,cache_namespace='alice').metrics['cache_hit']
    for i in range(5):a.search_only(Q+str(i),cache_namespace='alice')
    assert len(a.retrieval_cache.entries)<=2


def test_sqlite_wal_changes_invalidate_retrieval_revision(tmp_path):
    import sqlite3
    from kezohar.library_search import SQLiteLibrarySearch
    db=make_db(tmp_path,[source()]);backend=SQLiteLibrarySearch(db)
    with sqlite3.connect(str(db)) as connection:
        connection.execute('PRAGMA journal_mode=WAL')
        initial=backend.revision
        changed=source('other',text=TEXT+' another')
        connection.execute('INSERT INTO records(id,payload) VALUES (?,?)',('other',json.dumps(changed)))
        connection.commit()
        assert backend.revision!=initial


def test_direct_table_reading_uses_no_model_but_same_verifier():
    s=source(text='אלפא – העץ / נפשות.',reference='לוח ברכות בדיקה א:א')
    a=agent([s],FixedAnswer('MALICIOUS_MODEL_OUTPUT'))
    r=a.converse('מה מברכים על אלפא?')
    assert not a.answer_model.calls and r['mode']=='direct-source-reading'
    assert r['verification']['verdict']=='ok' and r['verification_layers']['permissions']=='passed-current-snapshot'
    assert r['structured_answer']['quotations'][0]['text']==s['text']
    assert 'בורא פרי העץ' in r['answer'] and 'תנאי החיוב לא אומתו' in r['answer']


def test_direct_table_cannot_skip_conditions_or_after_blessing_guard():
    s=source(text='אלפא – העץ / נפשות.',reference='לוח ברכות בדיקה א:א')
    a=agent([s],FixedAnswer(json.dumps({'selected_sources':['s1']})))
    r=a.converse('מה הברכה האחרונה על אלפא?')
    assert r['verdict']=='insufficient_context' and not r['structured_answer']['quotations']
    conditional=source(text='אלפא – העץ / נפשות רק אם דגל פעיל.',reference='לוח ברכות בדיקה א:א')
    a=agent([conditional],FixedAnswer(json.dumps({'selected_sources':['s1']})))
    r=a.converse('מה מברכים על אלפא?')
    assert a.answer_model.calls and r['mode']!='direct-source-reading'


def test_timing_breakdown_and_cache_metadata_are_consistent_in_sse(monkeypatch):
    a=agent();monkeypatch.setattr(api,'get_agent',lambda:a)
    r=request('/ask',{'question':Q,'circumstances':complete()}).json()
    assert r['timings']['total_s']>=r['timings']['model_call_s']>=0
    assert r['timings']['model_loading_s'] is None
    done=events(request('/ask',{'question':Q,'circumstances':complete(),'stream':True}).text)[-1][1]
    assert done['timings']['total_s']>=0 and not done['retrieval_metrics']['cache_hit']


def test_local_model_capacity_wait_never_starts_work_after_timeout(tmp_path):
    from kezohar.model_gate import model_slot,ModelBusy
    path=tmp_path/'model.lock'
    with model_slot(1,path=path):
        with pytest.raises(ModelBusy):
            with model_slot(0.01,path=path):pytest.fail('overlapping local model work')
    # A failed waiter never damages/revokes the existing lock or future work.
    with model_slot(1,path=path) as slot:assert 0<slot['remaining_s']<=1


def test_local_model_slot_is_released_on_provider_error(tmp_path):
    from kezohar.model_gate import model_slot
    path=tmp_path/'model.lock'
    with pytest.raises(RuntimeError):
        with model_slot(1,path=path):raise RuntimeError('synthetic provider failure')
    with model_slot(1,path=path):pass


def test_verification_and_presentation_cannot_publish_after_deadline(monkeypatch):
    from kezohar.request_budget import RequestBudget
    now=[10.0];monkeypatch.setattr('kezohar.request_budget.time.monotonic',lambda:now[0])
    a=agent(model=FixedAnswer(json.dumps({'selected_sources':['s1']})))
    original=a.source_verifier.verify
    def late(*args):
        result=original(*args);now[0]+=10;return result
    monkeypatch.setattr(a.source_verifier,'verify',late)
    r=a.converse(Q,circumstances=complete(),request_budget=RequestBudget(seconds=1))
    assert r['verdict']=='budget_exhausted' and not r['structured_answer']['quotations']
    assert not r.get('known_rule_context') and not r['halachic_verified']


def test_vessel_and_personal_immersion_are_not_interchangeable():
    woman=source(text='בדיקה סינתטית: אשה נדה תטבול בלילה; אין לטבול ביום במקרה זה.')
    vessel=source(text='בדיקה סינתטית: כלי זכוכית מותר להטביל ביום, כאשר דגל אלפא פעיל.')
    v=ExtractiveSourceVerifier()
    packet=json.dumps({'selected_sources':['s1']})
    assert v.verify('האם מותר לטבול ביום?\nטבילת כלים',packet,[woman])['verdict']!='ok'
    assert v.verify('האם מותר לטבול ביום?\nטבילת אישה לטהרה',packet,[vessel])['verdict']!='ok'


def test_contents_index_is_not_a_complete_practical_source():
    s=source(work_title='רב פעלים',reference='רב פעלים, מפתחות א:א',
             text='בדיקה סינתטית: האם מותר לטבול ביום? ראו תשובה אחרת בספר.')
    v=ExtractiveSourceVerifier().verify('האם מותר לטבול ביום?\nטבילת אישה לטהרה',json.dumps({'selected_sources':['s1']}),[s])
    assert v['verdict']!='ok'


def local_embedding(tmp_path,monkeypatch):
    from kezohar import config,model_gate
    from kezohar.local_embeddings import LocalEmbeddingModel
    monkeypatch.setattr(model_gate,'ROOT',tmp_path)
    spec=config.EmbeddingSettings('openai-compatible-local','text-embedding-nomic-embed-text-v1.5',3,'test','raw-text+nomic-prefix-v1')
    return LocalEmbeddingModel(spec,base_url='http://127.0.0.1:1234/v1')

@pytest.mark.parametrize('url',['https://example.com/v1','http://8.8.8.8/v1','http://169.254.169.254/v1',
                                'http://localhost/v1?secret=x','http://user:secret@localhost/v1'])
def test_embedding_adapter_cannot_send_books_to_external_or_credential_endpoint(tmp_path,monkeypatch,url):
    from kezohar.local_embeddings import LocalEmbeddingModel
    client=local_embedding(tmp_path,monkeypatch)
    with pytest.raises(ValueError):LocalEmbeddingModel(client.settings,base_url=url)


def test_real_embedding_batch_roles_order_and_dimension_validation(tmp_path,monkeypatch):
    from kezohar import local_embeddings
    client=local_embedding(tmp_path,monkeypatch);bodies=[]
    def transport(url,body,timeout):
        bodies.append(body)
        return {'model':client.settings.model,'data':[{'index':1,'embedding':[0,3,4]},{'index':0,'embedding':[3,4,0]}]}
    monkeypatch.setattr(local_embeddings,'request_embeddings',transport)
    result=client.embed_many(['alpha','beta'],task='query')
    assert result==[[0.6,0.8,0.0],[0.0,0.6,0.8]]
    assert bodies[0]['input']==['search_query: alpha','search_query: beta']
    assert client.spec.normalization=='raw-text+nomic-prefix-v1'

@pytest.mark.parametrize('rows,model',[
    ([{'index':0,'embedding':[1,2]}],None),
    ([{'index':0,'embedding':[True,0,1]}],'same'),
    ([{'index':0,'embedding':[float('nan'),0,1]}],'same'),
    ([{'index':0,'embedding':[0,0,0]}],'same'),
    ([{'index':0,'embedding':[1,2,3]}],'other-model'),
    ([{'index':1,'embedding':[1,2,3]}],'same'),
])
def test_real_embeddings_fail_closed_on_invalid_space_or_values(tmp_path,monkeypatch,rows,model):
    from kezohar import local_embeddings
    from kezohar.embeddings import VectorIndexMismatch
    client=local_embedding(tmp_path,monkeypatch)
    monkeypatch.setattr(local_embeddings,'request_embeddings',lambda *a,**kw:
        {'data':rows,'model':client.settings.model if model=='same' else model})
    with pytest.raises(VectorIndexMismatch):client.embed('alpha')


def test_real_embedding_configuration_does_not_autoload_or_index_corpus(monkeypatch):
    monkeypatch.setenv('EMBEDDINGS_PROVIDER','openai-compatible-local')
    monkeypatch.setenv('EMBEDDINGS_MODEL','text-embedding-nomic-embed-text-v1.5')
    a=agent([source()])
    assert a.search.vector is None
    assert a.knowledge.status()['vector_kind']=='disabled'


def test_embedding_preprocessing_is_an_independent_index_identity(tmp_path,monkeypatch):
    from dataclasses import replace
    from kezohar.embeddings import VectorIndexSpec,VectorIndexMismatch
    client=local_embedding(tmp_path,monkeypatch)
    original=client.spec
    changed=VectorIndexSpec.from_settings(replace(client.settings,normalization='raw-text-v1'))
    assert original.namespace!=changed.namespace
    with pytest.raises(VectorIndexMismatch):original.check_manifest(changed.manifest())


def test_colloquial_speech_and_spelling_variants_only_affect_relevance():
    s=source(text='בדיקה סינתטית: אסור להפסיק בדיבור בין תפילין של יד לתפילין של ראש, רק כשדגל אלפא פעיל.')
    v=ExtractiveSourceVerifier().verify('מותר לשוחח בין תפילין של יד לשל ראש?',json.dumps({'selected_sources':['s1']}),[s])
    assert v['verdict']=='ok' and v['evidence'][0]['quote']==s['text']
    assert not v['halachic_verified']
    fruit=source(text='פקאן – העץ / נפשות.',reference='לוח ברכות בדיקה א:א')
    a=agent([fruit],FixedAnswer(json.dumps({'selected_sources':['s1']})))
    r=a.converse('מה מברכים על פקן?')
    assert r['verification']['verdict']=='ok' and r['structured_answer']['quotations'][0]['text']==fruit['text']

@pytest.mark.parametrize('bad_field,value',[('metadata',None),('metadata',['unverified']),('text',None),('work_title',['bad'])])
def test_malformed_record_cannot_hide_or_replace_a_healthy_source(bad_field,value):
    from kezohar.agent import order_sources
    from kezohar.source_snapshot import admissible,public_sources
    malformed=source('bad');malformed[bad_field]=value
    good=source('good')
    ranked=order_sources([malformed,good],'בדיקת מקור סינתטי')
    assert [s['source_id'] for s in ranked]==['good']
    assert not admissible(malformed)
    assert public_sources([malformed])[0]['text']==''
    assert ExtractiveSourceVerifier().eligible_sources('בדיקת מקור סינתטי',[malformed,good])==[good]

@pytest.mark.parametrize('value',[None,[],{'wrong':'shape'}])
def test_malformed_quote_target_rejected_without_approving_or_crashing(value):
    bad=source('bad');bad['text']=value
    good=source('good')
    v=ExtractiveSourceVerifier()
    blocked=v.verify('בדיקת מקור סינתטי',json.dumps({'selected_sources':['bad']}),[bad,good])
    assert blocked['verdict']=='invalid_citation'
    valid=v.verify('בדיקת מקור סינתטי',json.dumps({'selected_sources':['good']}),[bad,good])
    assert valid['verdict']=='ok' and valid['evidence'][0]['source_id']=='good'


def test_spelling_expansion_does_not_turn_aramaic_issuing_into_a_nut():
    from kezohar.agent import order_sources
    fruit=source('fruit',text='פקאן – העץ / נפשות.',reference='לוח ברכות בדיקה א:א')
    noise=source('noise',text='מפקן בפרק אחר, בדיקה סינתטית שאינה עוסקת באוכל.')
    assert [s['source_id'] for s in order_sources([noise,fruit],'מה מברכים על פקן?')]==['fruit']
