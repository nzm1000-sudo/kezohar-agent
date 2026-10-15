from kezohar.answer_gate import gate

def result(answer_source='aza'):
    return {'verdict': 'ok', 'answer': 'לפי המקור: שחקי סמנין',
            'known_rule_context': {'rules': [{'source_id': answer_source}]},
            'sources': [{'source_id': 'aza', 'reference': 'עבודה זרה כח', 'text': 'עין שמרדה מותר לכוחלה בשבת ... שחקי סמנין'},
                        {'source_id': 'oneg', 'reference': 'עונג שבת יב כז', 'text': 'משחקי קלפים וכדומה בשבת ...'}]}

def test_confirmed_answer_is_kept(monkeypatch):
    monkeypatch.setenv('LLM_BASE_URL', 'http://127.0.0.1:1')
    r = gate('q', result('oneg'), ask=lambda q, c, t: {'source_id': 'oneg', 'per_passage': [{'id': 'oneg', 'topic': 't', 'same_action': True}], 'asked_action': 'a'})
    assert r['answer_gate']['status'] == 'confirmed' and r['answer'] == 'לפי המקור: שחקי סמנין'

def test_wrong_passage_is_replaced_by_the_one_that_answers(monkeypatch):
    monkeypatch.setenv('LLM_BASE_URL', 'http://127.0.0.1:1')
    r = gate('מותר לשחק בברידג׳ בשבת?', result(), ask=lambda q, c, t: {'source_id': 'oneg', 'per_passage': [{'id': 'oneg', 'topic': 't', 'same_action': True}], 'asked_action': 'a'})
    assert r['answer_gate']['status'] == 'reselected'
    assert 'משחקי קלפים' in r['answer'] and 'סמנין' not in r['answer'] and r['sources'][0]['source_id'] == 'oneg'

def test_no_direct_answer_declines(monkeypatch):
    monkeypatch.setenv('LLM_BASE_URL', 'http://127.0.0.1:1')
    r = gate('q', result(), ask=lambda q, c, t: {'source_id': None, 'per_passage': [], 'asked_action': 'a'})
    assert r['verdict'] == 'irrelevant' and 'סמנין' not in r['answer']

def test_invented_id_declines_and_unavailable_model_keeps_answer(monkeypatch):
    monkeypatch.setenv('LLM_BASE_URL', 'http://127.0.0.1:1')
    assert gate('q', result(), ask=lambda q, c, t: {'source_id': 'made-up', 'reason': ''})['verdict'] == 'irrelevant'
    def down(q, c, t):
        from kezohar.llm import LLMUnavailable
        raise LLMUnavailable('down')
    r = gate('q', result(), ask=down)
    assert r['verdict'] == 'ok' and r['answer_gate']['status'] == 'unavailable'


def test_choice_not_judged_same_action_declines(monkeypatch):
    monkeypatch.setenv('LLM_BASE_URL', 'http://127.0.0.1:1')
    r = gate('q', result(), ask=lambda q, c, t: {'source_id': 'aza', 'asked_action': 'a',
                                                 'per_passage': [{'id': 'aza', 'topic': 'כתישת סממנים', 'same_action': False}]})
    assert r['verdict'] == 'irrelevant'


def test_cited_passage_on_the_asked_action_is_kept_even_if_another_is_preferred(monkeypatch):
    monkeypatch.setenv('LLM_BASE_URL', 'http://127.0.0.1:1')
    r = gate('q', result('aza'), ask=lambda q, c, t: {'source_id': 'oneg', 'asked_action': 'a', 'per_passage': [
        {'id': 'aza', 'topic': 't', 'same_action': True}, {'id': 'oneg', 'topic': 't', 'same_action': True}]})
    assert r['answer_gate']['status'] == 'confirmed' and r['answer'] == 'לפי המקור: שחקי סמנין'
