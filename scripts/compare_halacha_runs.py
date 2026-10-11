# -*- coding: utf-8 -*-
"""Compare software, bounded support and human ruling review separately."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from kezohar.semantic_claims import units_for
from kezohar.source_quality import exclusion_reason
from kezohar.verification import ExtractiveSourceVerifier

FOCUS={1,4,5,13,19}


def individual_claim_audit(row):
    """Post-run diagnostics, not a replacement for the recorded packet verdict.

    The runtime fails closed at the first rejected claim. Inspect the remaining
    claims too, without ever treating a supported part as an accepted answer.
    """
    try:
        packet=json.loads(row.get('raw_qwen_answer') or '')
    except (ValueError,TypeError):
        return []
    if not isinstance(packet,dict) or not isinstance(packet.get('claims'),list):return []
    verifier=ExtractiveSourceVerifier()
    sources=[s for s in row['selected_sources'] if s['source_id'] in row['qwen_source_ids']]
    return [{'claim':c,'post_run_verification':verifier.verify(
        row['question'],json.dumps({'claims':[c]},ensure_ascii=False),sources)} for c in packet['claims']]


def quality_summary(run):
    rows=run['questions']
    verified=[r for r in rows if r['verification'].get('verdict')=='ok']
    technical=sum(all(r['verification'].get('checks',{}).get(k)=='passed'
                      for k in ('format','source_exists','reference_identity')) for r in rows)
    return {'questions':len(rows),'technical_identity_and_format_passed':technical,
            'bounded_claim_support_passed':sum(r['verification'].get('support')=='source-pinned-reformulations' for r in verified),
            'quotation_only_passed':sum(r['verification'].get('support')=='exact-extract-only' for r in verified),
            'model_outputs_blocked':sum(r['qwen_completed'] and r['verification'].get('verdict') not in ('ok','no_source') for r in rows),
            'generation_gated':sum(not r['qwen_called'] for r in rows),
            'model_no_source':sum(r['verification'].get('verdict')=='no_source' for r in rows),
            'human_halachic_verified':0,'human_review_required':len(rows),
            'total_s_median':round(statistics.median(r['total_s'] for r in rows),3),
            'total_s_range':[min(r['total_s'] for r in rows),max(r['total_s'] for r in rows)],
            'failures':dict(Counter(r['verification'].get('verdict','not-run') for r in rows))}


def render(base,new):
    qs=[r['question'] for r in base['questions']]
    if qs!=[r['question'] for r in new['questions']]:raise ValueError('questions/order changed')
    summary=quality_summary(new)
    trace=Counter((a['backend'],a['status']) for r in new['questions'] for a in r.get('discovery_attempts',[]))
    lines=['# השוואת 20 שאלות — אחזור ואימות טענות','',
           'המודל נשאר Qwen. כל השאלות והסדר זהים לבסיס. השתנו הדירוג, מסנני המקרה, מספר המקורות המבוקש (3 לעומת 5) ופרוטוקול התשובות; זהו ניסוי מערכת, לא השוואת מודלים או הוכחה שכל שינוי בפני עצמו שיפר את התוצאות.','',
           '**אין כאן תשובת ייחוס הלכתית או אישור פסיקה. כל התשובות דורשות בדיקה הלכתית אנושית.**','',
           '## מה תוקן באימות','',
           'אימות פורמט, קיום מקור, זהות ההפניה ותמיכת הטענה מדווחים בנפרד. פרפרזה נתמכת אינה חייבת להיות ציטוט. המסלול הראשון מאפשר ניסוחים חלופיים של שישה משפטים מוגדרים בחמש משפחות מקרה, לאחר עיון הנדסי בטקסט. כל משפט מקובע ל־SHA256 של המקור המלא ולמראה המקום. החלפת מילים לפי דמיון או הופעת מילות נושא אינן מוכיחות תמיכה. תנאים, הסתייגויות וייחוס הם חלק מהמשפט השלם.','',
           'זהו אימות שקילות מוגבל, ולא הבנת משמעות כללית. ניסוח חופשי מחוץ לניסוחים שנבדקו מסומן review_required ונחסם כתשובה, גם עם הפניה תקינה. דעה נגדית מוכרת מסומנת contradicted. השיטה עדיין מחייבת ביקורת הלכתית אנושית של הניסוחים ושל תחולתם. טקסט המקור אינו מנורמל לצורך אימות ציטוטים; שינויים בציטוט מילולי עדיין נדחים.','',
           '## אבחון תוכן לעומת צורה בהרצה החדשה','',
           '- אורז: המקור המתאים רח:ז סופק. הטענה הראשונה משתמשת ב״עליו״ במקום ״לפניו״ ואינה בניסוחים המוכרים; זה אינו מוכיח שגיאה הלכתית. הטענה השנייה אינה שומרת את התנאי ״אורז לבדו״ שבסעיף. היעלמות ״המוציא״ ו״נרות״ מפלט זה אינה מספיקה לאישור כל התשובה.','',
           '- יעלה ויבוא: תכב:א סופק. הטענה הראשונה כוללת שחרית, ראש חודש, סיום ועקירת רגליים אך ניסוחה טרם אומת במסלול המוגבל. הטענה השנייה מקשרת evidence_id של שולחן ערוך למקור קיצור שולחן ערוך יט:יא. יש לבדוק את התמיכה במקור השני לגופו; מזהה ראיה של הספר הראשון אינו מאמת אותו.','',
           '- תה: עונג שבת, פרק ט הלכה ח סופק. הפלט שומר גם היתר מעיקר הדין וגם המלצה להחמיר; הניסוח החופשי עדיין מסומן review_required. אין להסיק מהחסימה שהוא שגוי, ואין להוסיף אותו כמשפט מאושר רק כדי לשפר את המדד.','',
           '- תפילת הדרך: קי:ז סופק, עם זמן, מרחק ולכתחילה. גם כאן הניסוח שונה מהמשפטים המוגדרים; החסימה היא מגבלת אימות ולא הוכחה שהמודל לא הבין את המקור.','',
           '- המתנה אחרי אכילת בשר: הטענה מקושרת לפט:א, שומרת שש שעות והסרת בשר מהשיניים ומייחסת למרן. היא עברה שקילות מוגבלת; אותה יחידת ראיה אינה תקפה למקרה הצ׳יפס בשמן שניצלים.','',
           '- ברכת המזון: הפלט החדש עוסק בעיכול/רעב, בלי פרטי בשר וחלב ולחם שנשרף מהבסיס. הוא עדיין נחסם עקב ציטוטים שאינם מופיעים בשלמותם במקטעים המצוטטים. זהו שיפור התאמת האחזור לצד כשל ציטוט שנותר, בלי אישור התוכן כפסיקה.','',
           '## בחירת המקורות','',
           'שלושה מקורות היו הגדרת runner האבחוני; ברירת המחדל ב־API היא חמישה. הגדלת המספר לבדה עלולה להוסיף רעש. לכן נוספו מסננים למקרה ונושא, הרחבת שאילתת זמן תפילת הדרך/ברכת המזון והקדמת מקור פסיקה ישיר בהתאם לסמכות ולמסורת. מספר המקורות בפועל יכול להיות קטן מחמישה לאחר סינון.','',
           'ברכת המזון: מקור זמן צריך לעסוק בעיכול או רעב, ומקור המתנת בשר וחלב אינו עונה לשאלה זו. תפילת הדרך: נדרש הקשר התפילה וגם זמן/מרחק; המילים ״תפילה״ ו״דרך״ לבדן אינן מספיקות. נוספו הבחנות בין שחרית בראש חודש לבין יום טוב/ברכת המזון, ובין תה בכלי שני לבין אזכור כלי סתמי. מסמכים אזרחיים נשארים חסומים.','',
           '## מחקר הרשת','',
           'בהרצה המקורית אין תיעוד של סיבת כישלון DuckDuckGo; ידוע רק שכל הגילוי הגיע ל־API ויקיטקסט. קוד הגילוי משתמש ב־SearxNG רק אם הוגדר, מנסה DuckDuckGoHTML, ואז ויקיטקסט כשהניסיון לא מספק קישורים או נכשל. בהרצה החדשה נשמר יומן ניסיונות ללא כתובות פנימיות או סודות.','',
           '`'+json.dumps({b+':'+s:n for (b,s),n in trace.items()},ensure_ascii=False)+'`','',
           'ויקיטקסט נשאר טקסט תורני אפשרי ברמת עמוד, עם אימות כותרת ונתיב. נוספה הכרה בדפי תלמוד אחדים בלי להעניק להם סמכות של פסק. אין בהרצה זו הוכחה שהגילוי החינמי הגיע לפסיקה ספרדית ראשונית באתרים אחרים.','',
           '## זמינות הספרים','',
           'נבדק האינדקס בפועל, לא רק ההרשאות: 746,218 מקטעי אפליקציה זמינים ל־RAG בהתאם למדיניות הקיימת, בנוסף ל־15 מקורות הבסיס. במאגר מופיעים בית יוסף (25,437), בן איש חי (3,475), כף החיים (29,668), שולחן ערוך אורח חיים (4,230), יורה דעה (3,831), אבן העזר (1,909), חושן משפט (3,734), ועונג שבת (1,083 ועוד 958 מקורות וטעמים). כף החיים מזוהה לפי הספר גם כששדה המסורת ריק.','',
           '**ילקוט יוסף אינו נמצא כרגע באינדקס, ברשימת קובצי התוכן המיובאים או בשם חבילה/תוכן ב־43 manifests שנבדקו.** אין לפרש זאת כשלילת אישור שימוש. ילקוט שמעוני הוא ספר אחר. קיים קישור לשיעור הרב יצחק יוסף בתיק הצ׳יפס, אך PDF זה אינו מאגר ילקוט יוסף מיובא ומנוע הקריאה הנוכחי אינו מפענח PDF. נדרש מקור נתונים מאושר כדי להוסיף את התוכן, בלי להסיק היקף רישיון מפלט מודל. פירוט האינדקס: `LIBRARY_COVERAGE_2026-10-11.json`.','',
           '## מדדים נפרדים','',
           'בבסיס: 0 אימותי ציטוטים, 17 פלטים חסומים, 2 הודאות שאין מקור וחסימה אחת לפני הפקה. 16 unsupported אינם 16 פסקי הלכה שגויים. הנתונים המקוריים לא שונו.','',
           '```json',json.dumps(summary,ensure_ascii=False,indent=2),'```','',
           'הצלחה טכנית פירושה רק שפורמט, מזהה והפניה תואמים. quotation_only הוא ציטוט שנבדק, בלי הוכחת משמעות כללית. bounded_claim_support הוא שקילות המשפט המוגדר למקור המקובע, בלי אישור הלכתי. אין לחבר את שלוש הספירות לציון הצלחה הלכתי.','',
           '| # | שאלה | בסיס | עכשיו: פורמט / מקור / הפניה / תמיכה | מצב הפלט | זמן בסיס / עכשיו (ש׳) |',
           '|---|---|---|---|---|---:|']
    for a,b in zip(base['questions'],new['questions']):
        v=b['verification'];c=v.get('checks',{})
        checks=' / '.join(str(c.get(k,'לא נבדק')) for k in ('format','source_exists','reference_identity','claim_support'))
        lines.append('| {} | {} | {} | {} | {} | {} / {} |'.format(b['number'],b['question'],
            a['verification'].get('verdict','לפני הפקה'),checks,v.get('verdict','לפני הפקה'),a['total_s'],b['total_s']))
    lines.extend(['','## חמש בדיקות האיכות הממוקדות',''])
    for row in new['questions']:
        if row['number'] not in FOCUS:continue
        lines.extend(['### {}. {}'.format(row['number'],row['question']),'',
                      'מקורות שסופקו בפועל:', ''])
        ids=set(row['qwen_source_ids'])
        for s in row['selected_sources']:
            if s['source_id'] not in ids:continue
            lines.append('- `{}` — {}. מחבר: {}; מהדורה: {}.'.format(s['source_id'],s['reference'],s['author'] or 'לא תועד',s['version'] or 'לא תועדה'))
            for u in units_for(row['question'],s):
                lines.append('  משפט בעל שקילות מוגדרת: '+u['variants'][0]+' תנאים: '+'; '.join(u['conditions'])+'.')
        old=base['questions'][row['number']-1]
        lines.extend(['','פלט Qwen המקורי בבסיס:', '', '```text',old['raw_qwen_answer'] or 'לא הופק פלט','```','',
                      'פלט Qwen המקורי בהרצה החדשה:', '', '```text',row['raw_qwen_answer'] or 'לא הופק פלט','```','',
                      'תוצאת חבילת התשובה בזמן ההרצה:', '', '```json',json.dumps(row['verification'],ensure_ascii=False,indent=2),'```','',
                      'אבחון נפרד של כל טענה לאחר ההרצה (אינו מחליף את תוצאת החבילה; גם טענה נתמכת אינה מאשרת תשובה שיש בה טענה לא נתמכת):', '',
                      '```json',json.dumps(individual_claim_audit(row),ensure_ascii=False,indent=2),'```','',
                      'התשובה שנמסרה לאחר ההגנה:', '',row['answer'],'',
                      '**בדיקה הלכתית אנושית עדיין נדרשת.** מקורות שאינם רשומים ביחידת שקילות אינם מוכרזים כלא נכונים; תמיכת פרפרזה בהם טרם אומתה.'])
    lines.extend(['','## קבצים ושחזור','',
                  'נתוני כל 20 השאלות, מקורות, prompts בפועל, פלטים ומדדי סיום נשמרים בנפרד מהבסיס. דוח מפורט: `E2E_HALACHA_2026-10-11_V4.md`. הבסיס והרצת V2 לא שונו. הרצת V3 תועדה גם היא; חשפה בלבול בין מסלול quotes למסלול claims, ולא הוחלפה בניסוי המצליח יותר.','',
                  'המשך: אימות הלכתי אנושי והרחבת ניסוחי השקילות באופן מבוקר; גילוי ספרדי ו־PDF; בדיקת מהירות הייצור בנפרד. לא הוחלף Qwen, לא נוספו שירותים בתשלום ולא שונו האפליקציה המקורית, LM Studio או NAS.',''])
    return '\n'.join(lines),summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--report',required=True)
    args=p.parse_args()
    run=(ROOT/args.run).resolve();report=(ROOT/args.report).resolve()
    if ROOT not in run.parents or ROOT not in report.parents:raise ValueError('project artifacts only')
    base=json.loads((ROOT/'bench/frozen/halacha_2026-10-11.json').read_text())
    new=json.loads(run.read_text());text,summary=render(base,new)
    report.write_text(text)
    print(json.dumps(summary,ensure_ascii=False))
