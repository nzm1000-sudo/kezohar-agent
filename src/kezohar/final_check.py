"""The one last step every answer passes (owner, 2026-10-16): does the text shown actually answer the question?

The agent reaches an answer by many paths (the library, a quotation lookup, identity facts, encyclopedia reading, the
web). Each once showed text that does not answer: where a phrase appears instead of who wrote the book, a raw
encyclopedia sentence without the author. One check here instead of one patch per path: a short model call judges the
shown answer; when it does not answer, the sources are read again for a direct, complete answer, and failing that the
model answers from its own knowledge (owner rule 2026-10-16, labelled "ללא מקור").
"""
import json
from . import config
from .llm import _post

# Already written for this question by a reading step, computed, or not an answer to judge.
DONE = {'model-knowledge', 'summary-with-quote', 'web-quote-answer', 'scope', 'clarification', 'rule-with-clarification',
        'refuse', 'fast'}
SCHEMA = {'type': 'object', 'properties': {'answers': {'type': 'boolean'}}, 'required': ['answers'], 'additionalProperties': False}
PROMPT = ('בדוק אם הטקסט עונה ישירות ובמלואו על השאלה. answers=true רק אם קורא שאינו מכיר את הנושא יקבל ממנו את התשובה '
          'למה שנשאל (למשל לשאלה "מי כתב את משלי" — שם המחבר). answers=false אם הוא רק מזכיר את הנושא, מצטט קטע שאינו '
          'אומר את התשובה, מציין איפה מופיעות המילים, או עונה על חלק מהשאלה בלבד. החזר JSON בלבד.')


def answers(question, text, timeout=15):
    """True/False from the model; None when it cannot be asked (then the answer is kept as it is)."""
    from .model_gate import model_slot
    body = {'model': config.llm_model(), 'temperature': 0, 'max_tokens': 30, 'stream': False,
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'final_check', 'strict': True, 'schema': SCHEMA}},
            'messages': [{'role': 'system', 'content': PROMPT},
                         {'role': 'user', 'content': 'שאלה: ' + question + '\n\nהטקסט:\n' + text[:2500]}]}
    try:
        with model_slot(timeout) as slot:
            resp = _post(config.llm_base_url(), '/chat/completions', body, timeout=slot['remaining_s'])
        return bool(json.loads(resp['choices'][0]['message']['content'])['answers'])
    except Exception:
        return None


def finish(question, result):
    if not isinstance(result, dict) or config.get('FINAL_CHECK', '1') == '0' or result.get('mode') in DONE:
        return result
    # A commentator's own words (commentary_lookup.py) are never replaced by an answer from memory (owner, 2026-10-18:
    # a model "Ramban" replaced them and said the Torah was written after the conquest).
    # A checked bank answer (qa_bank.py) was judged already; it is not judged again.
    if result.get('commentary_lookup') or result.get('qa_bank') or result.get('blessing_lookup'):
        return result
    text = ((result.get('bari') or {}).get('answer') or result.get('answer') or '').strip()
    if not text:
        return result
    from concurrent.futures import ThreadPoolExecutor
    from .web_answer import read_and_answer, model_answer
    sources = [s for s in result.get('sources', []) if isinstance(s, dict) and s.get('text')][:3]
    # The check and both replacements (re-reading the sources, the model's own answer) start together: a rejected
    # answer no longer waits for the check before its replacement begins (~1.5-2 s). When the check passes, the
    # replacements are simply not used (a fraction of a cent).
    pool = ThreadPoolExecutor(3)
    try:
        verdict = pool.submit(answers, question, text)
        reread = pool.submit(read_and_answer, question, sources, chars=1500) if sources else None
        known_future = pool.submit(model_answer, question)
        if verdict.result() is not False:
            return result
        found = reread.result() if reread else None
        jewish, known = known_future.result()
    finally:
        pool.shutdown(wait=False)
    if found:
        answer, quote, source, _ = found
        result.update(answer=answer + '\n\nמקור: ״' + quote + '״ (' + source.get('reference', '') + ').',
                      mode='summary-with-quote', final_check='reread',
                      bari={'answer': answer, 'quote': quote, 'cite': source.get('reference', ''), 'source': 'library'})
        return result
    if known:
        return {'verdict': 'model_knowledge', 'mode': 'model-knowledge', 'sources': [], 'halachic_verified': False,
                'answer': known, 'bari': {'answer': known, 'quote': None, 'cite': None, 'source': 'model'},
                'source_status': 'no-source: model knowledge', 'final_check': 'model'}
    return result
