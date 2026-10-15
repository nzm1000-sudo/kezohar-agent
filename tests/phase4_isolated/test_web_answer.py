import kezohar.web_answer as w

WIKI = {'source_id': 'w1', 'reference': 'שמשון — ויקיפדיה', 'text': 'שמשון הוא שופט מקראי. שמשון היה בנו של מנוח משבט דן, מן העיר צרעה.'}

def run(monkeypatch, reply, sources=(WIKI,)):
    monkeypatch.setattr(w, '_gather', lambda q, r, b, d: (list(sources), []))
    return w.answer('מי היה אביו של שמשון?', {'normalized_question': 'q'}, ask=lambda q, l, t: reply)

def test_verbatim_quote_yields_a_short_cited_answer(monkeypatch):
    r = run(monkeypatch, {'asked': 'a', 'quote_states_the_answer': True, 'source_index': 0, 'quote': 'שמשון היה בנו של מנוח משבט דן', 'answer': 'אביו של שמשון היה מנוח.'})
    assert r['verdict'] == 'fact_supported' and r['answer'].startswith('אביו של שמשון היה מנוח.')
    assert 'שמשון — ויקיפדיה' in r['answer'] and r['web_answer']['quote_verified']

def test_invented_quote_or_index_or_null_is_rejected(monkeypatch):
    assert run(monkeypatch, {'asked': 'a', 'quote_states_the_answer': True, 'source_index': 0, 'quote': 'שמשון היה בנו של אברהם', 'answer': 'אברהם'}) is None
    assert run(monkeypatch, {'asked': 'a', 'quote_states_the_answer': True, 'source_index': 5, 'quote': 'שמשון היה בנו של מנוח', 'answer': 'מנוח'}) is None
    assert run(monkeypatch, {'source_index': None, 'quote': '', 'answer': ''}) is None

def test_private_question_never_searches(monkeypatch):
    monkeypatch.setattr(w, '_gather', lambda *a: (_ for _ in ()).throw(AssertionError('searched')))
    assert w.answer('q', {'export_allowed': False}) is None


def test_real_quote_that_does_not_state_the_answer_is_rejected(monkeypatch):
    assert run(monkeypatch, {'asked': 'שם אביו של שמשון', 'quote_states_the_answer': False, 'source_index': 0,
                             'quote': 'שמשון הוא שופט מקראי', 'answer': 'שמשון היה שופט'}) is None


def test_quote_check_ignores_typographic_quote_styles(monkeypatch):
    source = dict(WIKI, text='אחות משה מרים הנביאה, מציעה לבת פרעה „למצוא לה מינקת מן העבריות”.')
    r = run(monkeypatch, {'asked': 'a', 'quote_states_the_answer': True, 'source_index': 0,
                          'quote': 'אחות משה מרים הנביאה, מציעה לבת פרעה "למצוא לה מינקת מן העבריות"', 'answer': 'מרים'},
            sources=(source,))
    assert r and r['verdict'] == 'fact_supported'


def test_unanswered_halacha_question_falls_back_to_the_web(monkeypatch):
    import kezohar.orchestration as orchestration
    from kezohar.agent import Agent
    monkeypatch.setenv('WEB_ANSWER', '1')
    monkeypatch.setattr(orchestration.HalachicOrchestrator, 'answer',
                        lambda self, q, c=None, r=False, **k: {'verdict': 'irrelevant', 'answer': 'אין'})
    asked = []
    monkeypatch.setattr(w, 'answer', lambda q, route, discovered=(): asked.append(route) or {
        'verdict': 'fact_supported', 'answer': 'מהאינטרנט', 'sources': []})
    result = Agent(sources=[]).converse('מותר לשחק בברידג׳ בשבת?')
    assert result['answer'] == 'מהאינטרנט' and asked and asked[0]['normalized_question']
