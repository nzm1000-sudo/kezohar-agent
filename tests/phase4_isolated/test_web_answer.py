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


def test_summary_puts_a_direct_answer_above_its_verified_sentence():
    source = {'source_id': 's', 'reference': 'רמב״ם מאכלות אסורות ט ד',
              'text': 'בשר עוף בחלב אינו אסור באכילה מן התורה. ואסור באכילה מדברי סופרים כדי שלא יפשעו העם.'}
    result = {'verdict': 'ok', 'answer': 'לפי המקור, על תנאיו: ...', 'sources': [source]}
    out = w.summarize('למה אסור עוף וחלב?', dict(result), ask=lambda q, l, t: {
        'asked': 'הטעם', 'source_index': 0, 'quote_states_the_answer': True,
        'quote': 'ואסור באכילה מדברי סופרים כדי שלא יפשעו העם', 'answer': 'עוף בחלב אסור מדרבנן, כדי שלא יבואו לאיסור תורה.'})
    assert out['answer'].startswith('עוף בחלב אסור מדרבנן') and 'מקור: ״ואסור באכילה' in out['answer']
    assert out['source_answer'] == 'לפי המקור, על תנאיו: ...' and out['mode'] == 'summary-with-quote'
    kept = w.summarize('q', dict(result), ask=lambda q, l, t: {'asked': 'a', 'source_index': 0,
        'quote_states_the_answer': True, 'quote': 'משפט שלא קיים במקור בכלל', 'answer': 'x'})
    assert kept['answer'] == 'לפי המקור, על תנאיו: ...'  # unverifiable summary: the source answer stays


def test_summary_reads_only_the_cited_passage():
    cited = {'source_id': 'yy', 'reference': 'ילקוט יוסף', 'text': 'בארץ ישראל שואלים טל ומטר מליל שבעה בחשון.'}
    other = {'source_id': 'ks', 'reference': 'קיצור שו״ע', 'text': 'מתחילין לומר טל ומטר ביום ששים לתקופה.'}
    seen = []
    w.summarize('מתי?', {'verdict': 'ok', 'answer': 'x', 'sources': [other, cited], 'answer_gate': {'cited': ['yy']}},
                ask=lambda q, l, t: seen.append(l) or {'source_index': None})
    assert 'שבעה בחשון' in seen[0] and 'ששים' not in seen[0]


def test_cloud_model_falls_back_to_lite_then_local(monkeypatch):
    import kezohar.llm as llm
    monkeypatch.setenv('GEMINI_API_KEY', 'k'); monkeypatch.setenv('CLOUD_LLM', '1'); monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setenv('GEMINI_MODEL', 'big'); monkeypatch.setenv('GEMINI_FALLBACK_MODELS', 'lite')
    calls = []
    def send(url, body, timeout, headers=None):
        calls.append((url.split('/')[2], body['model'], body.get('reasoning_effort')))
        if 'googleapis' in url:
            raise llm.LLMUnavailable('503')
        return {'choices': [{'message': {'content': '{}'}}]}
    monkeypatch.setattr(llm, '_send', send)
    llm._post('http://127.0.0.1:1234/v1', '/chat/completions', {'model': 'qwen', 'reasoning_effort': 'none'}, timeout=30)
    assert [c[1] for c in calls] == ['big', 'lite', 'qwen/qwen3.5-35b-a3b']
    assert calls[0][2] == 'low' and calls[2][0] == '127.0.0.1:1234'


def test_only_approved_torah_sites_are_read():
    from kezohar.torah_sites import allowed
    assert not allowed('https://www.hidabroot.org/question/288650')  # not on the owner's list
    assert allowed('https://din.org.il/2026/04/15/x')
    assert allowed('https://www.yalkutyosef.co.il/x') and allowed('https://hebrew.yoatzot.org/x')
    assert not allowed('https://www.kipa.co.il/x')  # not on the owner's list
    assert not allowed('https://www.youtube.com/watch?v=x')
    assert not allowed('http://din.org.il/x')  # https only
    assert not allowed('https://din.org.il.evil.com/x')


def test_site_pages_and_searches_are_cached(tmp_path, monkeypatch):
    import kezohar.torah_sites as t
    monkeypatch.setenv('TORAH_SITES_CACHE', str(tmp_path / 'c.sqlite3'))
    downloads = []
    monkeypatch.setattr(t, '_download', lambda url, timeout=8: downloads.append(url) or ('כותרת', ['פסקה']))
    assert t._fetch('https://din.org.il/a') == ('כותרת', ['פסקה'])
    assert t._fetch('https://din.org.il/a') == ('כותרת', ['פסקה'])
    assert downloads == ['https://din.org.il/a']
    assert t._clean_title('הדלקת מזגן - ישיבת כסא רחמיםכלי נגישותהגדל טקסט') == 'הדלקת מזגן - ישיבת כסא רחמים'



def test_openai_first_then_gemini_with_translated_params(monkeypatch):
    import kezohar.llm as llm
    monkeypatch.setenv('CLOUD_LLM', '1'); monkeypatch.setenv('OPENAI_API_KEY', 'o'); monkeypatch.setenv('GEMINI_API_KEY', 'g')
    monkeypatch.setenv('GEMINI_MODEL', 'lite'); monkeypatch.setenv('GEMINI_FALLBACK_MODELS', '')
    calls = []
    def send(url, body, timeout, headers=None):
        calls.append((url.split('/')[2], body['model'], body.get('max_tokens'), body.get('max_completion_tokens')))
        if 'openai.com' in url:
            raise llm.LLMUnavailable('429')
        return {'choices': [{'message': {'content': '{}'}}]}
    monkeypatch.setattr(llm, '_send', send)
    llm._post('http://127.0.0.1:1234/v1', '/chat/completions', {'model': 'q', 'max_tokens': 300, '_prefer_strong': True}, timeout=30)
    assert calls[0] == ('api.openai.com', 'gpt-6-luna', None, 300)
    assert calls[1][:2] == ('generativelanguage.googleapis.com', 'lite')
