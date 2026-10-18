"""The bank's checked answers for the app's "מאגר השאלות" (owner, 2026-10-18: "only what passed the check — the source
does not matter as long as the answer is right"; spread over the existing categories, opened at once with no agent run).

Each row: [category, topic, question, answer, quote, cite] — category is the app's halacha category id (HALACHA_TOPICS)
or 'torah' for the Tanakh, people and thought; topic is the bank's own subject. quote/cite are null when no source.

Usage: export_bank_questions.py <app>/public/data/rav-bari-questions.json
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_qa_bank import reworded

CATEGORY = {
    'shabbat': ['שבת –'], 'kashrut': ['כשרות –'],
    'blessings': ['ברכה אחרונה', 'ברכות הנהנין', 'ברכות הראייה'],
    'prayer': ['מנחה וערבית', 'בית הכנסת', 'קריאת שמע', 'תפילת שחרית'],
    'holidays': ['ראש חודש', 'חנוכה', 'ראש השנה', 'סוכות', 'תעניות', 'ספירת העומר', 'פסח', 'פורים'],
    'family': ['אבלות', 'כיבוד הורים'], 'money': ['צדקה ומעשרות'], 'ethics': ['לשון הרע'],
    'daily': ['ציצית ומזוזה', 'מנהגי עדות המזרח'],
}


def category_of(topic):
    return next((cat for cat, starts in CATEGORY.items() if any(topic.startswith(s) for s in starts)), 'torah')


def main(target):
    bank = ROOT / 'data/store/qa-bank'
    new = reworded()  # the questions as people ask them (build_qa_bank.py wording)
    good = {r['key'] for r in map(json.loads, (bank / 'checks.jsonl').read_text().splitlines()) if r['ok']}
    key = lambda r: hashlib.sha256((r['q'] + '|' + r['answer']).encode()).hexdigest()[:20]
    seen, out = set(), []
    for r in map(json.loads, (bank / 'answers.jsonl').read_text().splitlines()):
        if not r.get('answer') or 'הקטע' in r['answer'] or r['q'] in seen or key(r) not in good:
            continue
        seen.add(r['q'])
        topic = r['topic'].split(' › ')[0].strip()
        sourced = bool(r.get('quote') and r.get('cite'))
        cat = category_of(topic)
        if cat in ('shabbat', 'kashrut') and ' – ' in topic:  # "שבת – מוקצה וטלטול" under שבת reads "מוקצה וטלטול"
            topic = topic.split(' – ', 1)[1]
        out.append([cat, topic, new.get(r['q'], r['q']), r['answer'], r['quote'] if sourced else None, r['cite'] if sourced else None])
    Path(target).write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print(len(out), 'checked answers')


if __name__ == '__main__':
    assert category_of('שבת – מוקצה וטלטול') == 'shabbat' and category_of('נביאים ראשונים') == 'torah'
    main(sys.argv[1])
