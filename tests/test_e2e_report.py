"""Report must distinguish real model output, software evidence and human review."""
from scripts.e2e_halacha import citation_status, render_report


def row(completed=True, verdict='ok'):
    return {'number':1,'question':'מה מברכים על אורז?','total_s':3,'local_s':0.1,'web_s':1,
            'qwen_s':1.9,'local_sources':[],'web_sources':[],'qwen_completed':completed,
            'qwen_called':completed,'verification':{'verdict':verdict},'mode':'web-llm-verified',
            'verdict':verdict,'raw_qwen_answer':'פלט מקורי' if completed else None,
            'answer':'תשובה מסוננת','qwen_source_ids':[],'web_errors':[]}


def test_software_success_never_becomes_human_psak_verification():
    run={'started_at':'2026-10-11','model':'local-qwen','source_count':10,'timeout_s':90,
         'questions':[row()], 'summary':{'human_halachic_verified':0}}
    report=render_report(run)
    assert 'עבר אימות תוכנה של ציטוטים בלבד' in report
    assert 'דורשות בדיקה הלכתית אנושית' in report
    assert 'לא ניתנה הכרעה אנושית' in report
    assert 'פלט מקורי' in report and 'תשובה מסוננת' in report
    assert '"human_halachic_verified": 0' in report


def test_timeout_and_guard_are_not_counted_as_quote_verification():
    assert citation_status(row(completed=False))=='לא נבדק — לא התקבל פלט Qwen'
    assert citation_status(row(verdict='invalid_citation'))=='לא עבר: invalid_citation'
    assert citation_status(row(verdict='no_source'))=='אין טענה לאימות — המודל הודה שאין מקור'
