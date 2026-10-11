"""Read-only live corpus/web/Qwen diagnostic; checkpoints each real question.

Does not load/switch models, modify LM Studio, or persist research into knowledge.
Run only when real external web and the already configured local Qwen are wanted.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import statistics
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlsplit
import ipaddress

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from kezohar import api, config
from kezohar.web_research import WebResearchEngine


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def source_description(source):
    return {key: source.get(key, '') for key in
            ('source_id', 'work_title', 'author', 'reference', 'reference_en', 'source_url',
             'source_project', 'source_file', 'tradition', 'license', 'version', 'text')}


class RecordedModel:
    def __init__(self, delegate):
        self.delegate = delegate
        self.calls = []

    @property
    def identity(self):
        return self.delegate.identity

    def health(self, timeout=8):
        return self.delegate.health(timeout)

    def generate(self, question, sources, timeout=90):
        call = {'source_ids': [s['source_id'] for s in sources], 'timeout_s': timeout}
        self.calls.append(call)
        start = time.perf_counter()
        try:
            result = self.delegate.generate(question, sources, timeout=timeout)
            call.update(answer=result['answer'], completed=True)
            return result
        except Exception as exc:
            # Error class only: do not log server addresses, credentials or request bodies.
            call.update(completed=False, error=type(exc).__name__)
            raise
        finally:
            call['elapsed_s'] = round(time.perf_counter() - start, 3)


class RecordedResearch(WebResearchEngine):
    def __init__(self, timeout):
        super().__init__(store_path=None)
        self.inference_timeout = timeout
        self.last_research = None

    def research(self, *args, **kwargs):
        start = time.perf_counter()
        result = super().research(*args, **kwargs)
        self.last_research = {**result, 'elapsed_s': round(time.perf_counter() - start, 3)}
        return result

    def answer(self, *args, **kwargs):
        # Longer diagnostic request timeout only; production default stays 15s.
        kwargs['timeout'] = self.inference_timeout
        return super().answer(*args, **kwargs)


def citation_status(row):
    verification = row.get('verification', {})
    if not row.get('qwen_completed'):
        return 'לא נבדק — לא התקבל פלט Qwen'
    verdict = verification.get('verdict')
    if verdict == 'ok':
        return 'עבר אימות תוכנה של ציטוטים בלבד'
    if verdict == 'no_source':
        return 'אין טענה לאימות — המודל הודה שאין מקור'
    return 'לא עבר: ' + (verdict or 'ללא תוצאת אימות')


def summarize(rows):
    times = [row['total_s'] for row in rows]
    return {'tested': len(rows),
            'qwen_completed': sum(row['qwen_completed'] for row in rows),
            'qwen_called': sum(row['qwen_called'] for row in rows),
            'citation_software_passed': sum(row['qwen_completed'] and row['verification'].get('verdict') == 'ok' for row in rows),
            'citation_verdicts': dict(Counter(row['verification'].get('verdict', 'not-run') for row in rows)),
            'qwen_received_web_sources': sum(bool({s['source_id'] for s in row['web_sources']} & set(row['qwen_source_ids'])) for row in rows),
            'discovery_backends': dict(Counter(row['discovery_backend'] for row in rows)),
            'total_s_min': min(times) if times else None,
            'total_s_max': max(times) if times else None,
            'total_s_median': round(statistics.median(times), 3) if times else None,
            'qwen_above_local_4_5s': sum(row['qwen_s'] > 4.5 for row in rows),
            'human_halachic_verified': 0}


def render_report(run):
    lines = ['# בדיקת קצה לקצה חיה — 20 שאלות הלכתיות', '',
             'הרצה: ' + run['started_at'] + '. מודל: `' + run['model'] + '`.', '',
             'הספרייה המקומית, מחקר הרשת והמודל המקומי הופעלו בפועל. פלט Qwen נרשם לפני מנגנון ההגנה, לצד התשובה שהמערכת החזירה. אין כאן אישור פסיקה אנושי.', '',
             'כל התשובות מסומנות **דורשות בדיקה הלכתית אנושית**. הצלחת בדיקת תוכנה מעידה רק על התאמת ציטוט לטקסט שנשלף ועל בדיקות הסף הקיימות; היא אינה מוכיחה תחולה הלכתית או שהקטע שלם.', '',
             'מקטעים במאגר המקומי: {:,}. הגבלת זמן הפקה באבחון: {} שניות; ברירת המחדל במסלול מחקר היא 15 שניות ובמענה מקומי 4.5 שניות. ההגדרות הקיימות לא שונו.'.format(run['source_count'], run['timeout_s']), '',
             'הזמן הכולל הוא זמן תהליך האבחון: אחזור מקומי מקדים למדידה, ואחריו מסלול Agent.research שמאחזר שוב, חוקר ומפיק. הוא אינו מדידת HTTP או SSE של ה־API; זמן Qwen ומחקר הרשת נמדדים בנפרד. לא הופעל מטמון תשובות.', '',
             'המחקר משתמש בגילוי הרשת הקיים ללא מקורות ידניים או תשובות ייחוס שהוזנו למודל. מקורות רשת נשמרו בדוח לפי מדיניות הקטעים של המערכת; אין שמירת טקסטי רשת מלאים או הוספתם למאגר הפעיל.', '',
             '| # | שאלה | זמן כולל (ש׳) | מקורות מקומיים / רשת | Qwen | אימות ציטוטים | בדיקה הלכתית |',
             '|---|---|---:|---:|---|---|---|']
    for row in run['questions']:
        qwen = 'התקבל פלט' if row['qwen_completed'] else ('כשל/חריגה' if row['qwen_called'] else 'נחסם לפני הפקה')
        lines.append('| {} | {} | {} | {} / {} | {} | {} | נדרשת |'.format(
            row['number'],row['question'],row['total_s'],len(row['local_sources']),len(row['web_sources']),qwen,citation_status(row)))
    for row in run['questions']:
        lines.extend(['', '## {}. {}'.format(row['number'],row['question']), '',
                      '**בדיקה הלכתית אנושית: נדרשת; לא ניתנה הכרעה אנושית לדוח זה.**', '',
                      'זמנים: מקומי {} ש׳; מחקר רשת {} ש׳; Qwen {} ש׳; כולל {} ש׳.'.format(
                          row['local_s'],row['web_s'],row['qwen_s'],row['total_s']), '',
                      'אימות ציטוטים: **{}**. מצב המערכת: `{}` / `{}`.'.format(citation_status(row),row['mode'],row['verdict']), ''])
        lines.extend(['פירוט בדיקת התוכנה: `' + json.dumps(row.get('verification', {}), ensure_ascii=False) + '`.', ''])
        if row['qwen_s'] > 15:
            lines.extend(['**הפקת Qwen חרגה ממגבלת 15 השניות הרגילה של מסלול המחקר.**', ''])
        for title, key in [('מקורות מקומיים שנמצאו','local_sources'),('מקורות רשת שנמצאו','web_sources')]:
            lines.extend(['### '+title, ''])
            sources = row[key]
            if not sources:
                lines.append('לא נמצאו מקורות במסלול זה.')
            for s in sources:
                lines.append('- **{}** — {}. מחבר: {}; מהדורה: {}; מזהה: `{}`.'.format(
                    s['work_title'], s['reference'], s['author'] or 'לא מזוהה', s['version'] or 'לא תועדה', s['source_id']))
                if s['reference_en']:
                    lines.append('  מראה מקום קנוני: `{}`.'.format(s['reference_en']))
                if s['source_url']:
                    lines.append('  [עמוד המקור]({}).'.format(s['source_url']))
        lines.extend(['', 'מקורות שהועברו בפועל ל־Qwen: ' + (', '.join('`'+sid+'`' for sid in row['qwen_source_ids']) or 'לא הועברו'), '',
                      '### פלט Qwen המקורי בהרצה זו', ''])
        if row['raw_qwen_answer'] is not None:
            lines.extend(['```text', row['raw_qwen_answer'], '```'])
        else:
            lines.append('לא התקבל פלט. ' + ('אירעה חריגה או חריגת זמן.' if row['qwen_called'] else 'מנגנון הראיות עצר את ההפקה.'))
        lines.extend(['', '### התשובה שהמערכת החזירה', '', row['answer'] or 'לא הוחזרה תשובה עקב כשל.', '',
                      'נדרש לבחון אנושית את תחולת כל מקור, תנאיו, המסורת, מהדורתו והשלמת ההקשר. אם התשובה נחסמה, אין להציג את פלט המודל המקורי כפסיקה.'])
        if row['web_errors']:
            lines.extend(['', 'שגיאות מחקר: `' + json.dumps(row['web_errors'], ensure_ascii=False) + '`.'])
        if row.get('error'):
            lines.extend(['', 'כשל בהרצה: `' + row['error'] + '`.'])
    summary = run.get('summary', {})
    lines.extend(['', '## סיכום מדידות', '',
                  'נבדקו {} שאלות; התקבל פלט Qwen ב־{} מהן; {} תשובות עברו אימות ציטוטים בתוכנה. אפס תשובות קיבלו אישור הלכתי אנושי במסגרת הרצה זו.'.format(summary.get('tested', len(run['questions'])), summary.get('qwen_completed', 0), summary.get('citation_software_passed', 0)), '',
                  '`unsupported` מציין כשל במבנה הציטוט או בעיגונו. בדיקת נכונות הפסיקה ההלכתית דורשת עיון נפרד; היעדר התאמה לתבנית אינו לבדו הכרעה הלכתית.', '',
                  '```json', json.dumps(summary,ensure_ascii=False,indent=2), '```', ''])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--timeout', type=float, default=90)
    parser.add_argument('--top-k', type=int, default=3)
    parser.add_argument('--output', default='data/store/e2e-halacha-2026-10-11')
    parser.add_argument('--report', default='docs/E2E_HALACHA_2026-10-11.md')
    args = parser.parse_args()
    out, report = (ROOT/args.output).resolve(), (ROOT/args.report).resolve()
    if ROOT not in out.parents or ROOT not in report.parents:
        raise ValueError('artifacts must stay inside project')
    if report.exists() or (out/'results.json').exists():
        raise ValueError('choose new artifact paths; do not overwrite an earlier live run')
    settings=config.answer_settings()
    host=urlsplit(settings.base_url).hostname or ''
    try: local=host=='localhost' or ipaddress.ip_address(host).is_private
    except ValueError: local=host.endswith('.local')
    if settings.provider!='openai-compatible' or 'qwen' not in settings.model.lower() or not local:
        raise ValueError('this diagnostic requires an already configured local Qwen')
    ag=api.get_agent()
    ok, models=ag.answer_model.health(timeout=8)
    if not ok or settings.model not in models:
        raise ValueError('configured Qwen unavailable; no model loading or server changes attempted')
    ag.answer_model=RecordedModel(ag.answer_model)
    ag.research_engine=RecordedResearch(args.timeout)
    questions=json.loads((ROOT/'bench/e2e_halacha_questions.json').read_text(encoding='utf-8'))
    if len(questions)!=20 or len(set(questions))!=20:
        raise ValueError('expected 20 distinct real halachic questions')
    out.mkdir(parents=True,exist_ok=True)
    run={'started_at':datetime.now(timezone.utc).isoformat(), 'model':settings.model,
         'source_count':ag.knowledge.status()['source_count'], 'timeout_s':args.timeout,
         'top_k':args.top_k, 'kind':'live-local-library-web-Qwen', 'human_review':'required-for-all',
         'git_commit':os.popen('git rev-parse HEAD').read().strip(), 'questions':[]}
    for number, question in enumerate(questions,1):
        print(json.dumps({'event':'started','number':number,'question':question},ensure_ascii=False),flush=True)
        start=time.perf_counter()
        local_start=time.perf_counter()
        local_sources=ag.search_only(question,top_k=args.top_k)
        local_s=round(time.perf_counter()-local_start,3)
        ag.answer_model.calls=[];ag.research_engine.last_research=None
        error=None
        try:
            result=ag.research(question,top_k=args.top_k)
        except Exception as exc:
            error=type(exc).__name__;result={'answer':'','mode':'error','verdict':'error'}
        research=ag.research_engine.last_research or {}
        calls=ag.answer_model.calls
        row={'number':number,'question':question,'local_s':local_s,'web_s':research.get('elapsed_s',0),
             'qwen_s':round(sum(c['elapsed_s'] for c in calls),3),'total_s':round(time.perf_counter()-start,3),
             'local_sources':[source_description(s) for s in local_sources],
             'web_sources':[source_description(s) for s in research.get('sources',[])],
             'selected_sources':[source_description(s) for s in result.get('sources',[])],
             'qwen_called':bool(calls),'qwen_completed':any(c.get('completed') for c in calls),
             'qwen_source_ids':[sid for c in calls for sid in c['source_ids']],
             'raw_qwen_answer':next((c.get('answer') for c in calls if c.get('completed')),None),
             'qwen_calls':calls,'answer':result.get('answer',''),'mode':result.get('mode'),
             'verdict':result.get('verdict'),'verification':result.get('verification',{}),
             'web_errors':research.get('errors',[]),'discovery_backend':research.get('discovery_backend'),
             'human_review':'required','error':error}
        run['questions'].append(row)
        run['summary']=summarize(run['questions'])
        write_json(out/'results.json',run)
        report.write_text(render_report(run),encoding='utf-8')
        print(json.dumps({'event':'completed','number':number,'qwen_completed':row['qwen_completed'],
                          'citation_verdict':row['verification'].get('verdict'),'total_s':row['total_s']},ensure_ascii=False),flush=True)
    run['finished_at']=datetime.now(timezone.utc).isoformat()
    write_json(out/'results.json',run)
    report.write_text(render_report(run),encoding='utf-8')
    print(json.dumps({'event':'finished','summary':run['summary']},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
