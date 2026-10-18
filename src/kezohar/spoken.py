"""A question that came by voice, set right before it is answered (owner, 2026-10-18: "עשרת הדיברות" was heard as
"הסרט הדיברות" and answered about films). The model corrects only words the speech recognizer plainly misheard in a
Jewish question, keeps the meaning, and returns the question; on any failure the question goes on as heard.
"""
import json

from . import config

SCHEMA = {'type': 'object', 'properties': {'question': {'type': 'string'}}, 'required': ['question'], 'additionalProperties': False}
PROMPT = ('לפניך שאלה ביהדות שהוקלטה בקול ותומללה אוטומטית. תקן רק מילים שתומללו בטעות בבירור — לפי ההקשר התורני '
          '(למשל "מה הם הסרט הדיברות" → "מה הם עשרת הדיברות", "ברכת המזונות" → "ברכת המזון", "תפילין של ראש חודש" '
          'נשאר כמות שהוא). אל תשנה את משמעות השאלה, אל תוסיף ואל תשמיט פרטים, ואם אין טעות — החזר אותה כמות שהיא. JSON בלבד.')


def correct(question, timeout=8):
    from .llm import _post
    body = {'model': config.llm_model(), 'temperature': 0, 'max_tokens': 120, 'stream': False,
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'spoken', 'strict': True, 'schema': SCHEMA}},
            'messages': [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': question}]}
    try:
        fixed = ' '.join(json.loads(_post(config.llm_base_url(), '/chat/completions', body, timeout=timeout)['choices'][0]['message']['content'])['question'].split())
    except Exception:
        return question
    # A correction is a few words, never a new question.
    return fixed if fixed and len(fixed) <= len(question) * 1.6 + 10 else question
