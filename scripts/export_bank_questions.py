"""The bank's checked answers for the app's "מאגר השאלות" (owner, 2026-10-18: "only what passed the check — the source
does not matter as long as the answer is right"; spread over the existing categories, opened at once with no agent run).

The list's rows: [category, topic, question]; the answers per category in rav-bari/<category>.json — category is the app's halacha category id (HALACHA_TOPICS)
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
    'prayer': ['מנחה וערבית', 'בית הכנסת', 'קריאת שמע', 'תפילת שחרית', 'תפילת הדרך'],
    'holidays': ['ראש חודש', 'חנוכה', 'ראש השנה', 'סוכות', 'תעניות', 'ספירת העומר', 'פסח', 'פורים', 'חול המועד', 'ט״ו בשבט'],
    'family': ['אבלות', 'כיבוד הורים', 'ברית מילה', 'חתונה', 'חינוך ילדים'], 'money': ['צדקה ומעשרות'], 'ethics': ['לשון הרע'],
    'daily': ['ציצית ומזוזה', 'מנהגי עדות המזרח', 'נטילת ידיים', 'שמיטה'],
}


def category_of(topic):
    return next((cat for cat, starts in CATEGORY.items() if any(topic.startswith(s) for s in starts)), 'torah')


def main(target):
    bank = ROOT / 'data/store/qa-bank'
    new = reworded()  # the questions as people ask them (build_qa_bank.py wording)
    retopic = json.loads((bank / 'retopic.json').read_text()) if (bank / 'retopic.json').exists() else {}
    good = {r['key'] for r in map(json.loads, (bank / 'checks.jsonl').read_text().splitlines()) if r['ok']}
    key = lambda r: hashlib.sha256((r['q'] + '|' + r['answer']).encode()).hexdigest()[:20]
    seen, out = set(), []
    for r in map(json.loads, (bank / 'answers.jsonl').read_text().splitlines()):
        q = new.get(r['q'], r['q'])  # two wordings may become one question: it is listed once
        if not r.get('answer') or 'הקטע' in r['answer'] or q in seen or key(r) not in good:
            continue
        seen.add(q)
        # The old "במדבר ודברים" subject, split by book (build_qa_bank.py retopic).
        topic = retopic.get(r['q']) or r['topic'].split(' › ')[0].strip()
        sourced = bool(r.get('quote') and r.get('cite'))
        cat = category_of(topic)
        if cat in ('shabbat', 'kashrut') and ' – ' in topic:  # "שבת – מוקצה וטלטול" under שבת reads "מוקצה וטלטול"
            topic = topic.split(' – ', 1)[1]
        out.append([cat, topic, q, r['answer'], r['quote'] if sourced else None, r['cite'] if sourced else None])
    # The blessings table of עונג שבת (owner, 2026-10-18: "more questions"): each food's question answered from the book's
    # own line, no model in between — before and after, the book's words as the quote, its page as the source.
    table = bank / '..' / 'food-blessings.json'
    if table.exists():
        for food in json.loads(table.read_text()):
            if not food.get('book'):
                continue
            name = food['names'][0].split('[')[0].strip()
            q = f'מה מברכים על {name}?'
            if q in seen:
                continue
            seen.add(q)
            answer = f'על {name} מברכים «{food["before"]}», ולאחר האכילה «{food["after"]}».'
            out.append(['blessings', 'לוח הברכות — עונג שבת', q, answer, food['book'], food['cite']])
    # The list holds the questions only (it opens at once — owner, 2026-10-18: "still slow"); each category's answers are
    # their own file beside it, read when an answer of that category opens: rav-bari/<category>.json {question: [answer, quote, cite]}.
    target = Path(target)
    target.write_text(json.dumps([row[:3] for row in out], ensure_ascii=False, separators=(',', ':')))
    shards = target.with_name('rav-bari')
    shards.mkdir(exist_ok=True)
    for old in shards.glob('*.json'):
        old.unlink()
    for cat in {row[0] for row in out}:
        answers = {row[2]: row[3:] for row in out if row[0] == cat}
        (shards / f'{cat}.json').write_text(json.dumps(answers, ensure_ascii=False, separators=(',', ':')))
    # The list by category too (owner, 2026-10-21: "split it, so it is easier"): rav-bari-list/<category>.json rows
    # [topic, question], and rav-bari-list/index.json {category: count} — the bank's first screen reads only the index.
    lists = target.with_name('rav-bari-list')
    lists.mkdir(exist_ok=True)
    for old in lists.glob('*.json'):
        old.unlink()
    counts = {}
    for cat in sorted({row[0] for row in out}):
        rows = [[row[1], row[2]] for row in out if row[0] == cat]
        counts[cat] = len(rows)
        (lists / f'{cat}.json').write_text(json.dumps(rows, ensure_ascii=False, separators=(',', ':')))
    (lists / 'index.json').write_text(json.dumps(counts, ensure_ascii=False))
    print(len(out), 'checked answers')


if __name__ == '__main__':
    assert category_of('שבת – מוקצה וטלטול') == 'shabbat' and category_of('נביאים ראשונים') == 'torah'
    main(sys.argv[1])
