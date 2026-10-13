"""Bounded whole-unit language edits and source-derived clarification facts.

No free paraphrase entailment or automatic ruling. Every word/condition stays in
the full unit, except explicit spelling/style replacements. Unknown wording fails.
"""
import hashlib
import json
import re
from .hebrew import strip_niqqud, normalize
from .source_snapshot import fingerprint

STYLE = (
    ('עד אימתי','עד מתי'), ('יכול לברך','אפשר לברך'),
    ('כל זמן שאינו','כל עוד אינו'), ('כל זמן שאינה','כל עוד אינה'),
    ('בדבור','בדיבור'), ('תפלה של יד','תפילין של יד'), ('תפלה של ראש','תפילין של ראש'), ('לתפלה של ראש','לתפילין של ראש'),
    ('ולכתחלה','ולכתחילה'),
    ('כנתעכל לגמרי דיינינן ליה','נחשב כאילו התעכל לגמרי'),
    ('מחמת','בגלל'), ('וכן נמי','וכך גם'), ('אע"פ','אף על פי'),
)

def revision():
    from .blessing_context import FIRST_NAMES,LAST_NAMES
    return hashlib.sha256(json.dumps({'version':3,'edits':STYLE,'table_names':FIRST_NAMES,'last_column_names':LAST_NAMES,
        'format':'whole-unit-sentence-paragraphs-v3'},sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def explain(source):
    text=strip_niqqud(source.get('text','')).strip()
    for old,new in STYLE:
        text=re.sub(r'(?<!\w)'+re.escape(old)+r'(?!\w)',lambda _:new,text)
    # Layout only: every clause/condition remains in original order.
    parts=re.split(r'(\[[^\[\]]*\])',text)
    for i in range(0,len(parts),2):
        part=parts[i]
        part=re.sub(r'^עד מתי ([^?:.]{1,60}?)\s+עד(?=\s+ש)',r'עד מתי \1? עד',part)
        part=re.sub(r'\s+(?=וכמה שיעורו\b)','\n\n',part)
        part=re.sub(r'וכמה שיעורו\s+', 'וכמה שיעורו?\n',part)
        part=re.sub(r'\s+(?=ומשעה\b)','\n\n',part)
        parts[i]=re.sub(r'([.!?])\s+(?=[א-ת])',r'\1\n\n',part)
    return ''.join(parts)

def validate_answers(answers):
    if answers is None:return {}
    if (not isinstance(answers,dict) or len(answers)>8
            or any(not isinstance(k,str) or not re.fullmatch(r'[a-f0-9]{32}',k)
                   or v not in ('yes','no','unknown') for k,v in answers.items())):
        raise ValueError('rule_answers must contain source-bound ids and yes/no/unknown values')
    return dict(answers)

def conditions(source, question):
    # Only an explicit negative duration predicate is understood. Other clauses
    # stay in the whole explanation; this is NOT a claim of complete case intake.
    clean=strip_niqqud(source.get('text',''))
    pattern=r'כל זמן ש(?:אינו|אינה)\s+(.+?)(?=\s+(?:ומשעה|ואם|אבל|וכן)|[,.;:]|$)'
    result=[]
    for match in re.finditer(pattern,clean):
        predicate=match.group(1).strip()
        if not 2<=len(predicate)<=100:continue
        key=hashlib.sha256((fingerprint(source)+'|'+normalize(question)+'|'+str(match.span())+'|'+match.group()).encode()).hexdigest()[:32]
        result.append({'condition_id':key,'source_id':source['source_id'],
            'source_snapshot':fingerprint(source),'reference':source.get('reference',''),
            'description':predicate,'required_value':'no',
            'scope':'explicit-duration-predicate; other conditions remain in full source',
            'question':'האם במקרה שלך מתקיים התיאור הבא: ״'+explain({'text':predicate})+'״?',
            'kind':'source-condition','field':key,
            'options':[{'value':'yes','label':'כן, התיאור מתקיים'},
                       {'value':'no','label':'לא, התיאור אינו מתקיים'},
                       {'value':'unknown','label':'לא ידוע לי'}]})
    return result[:3]

def context(verification,sources,question,answers):
    index={s['source_id']:s for s in sources}
    rules=[];conditions_found=[]
    for evidence in verification.get('evidence',[]):
        s=index.get(evidence['source_id'])
        # Short reviewed extracts don't establish the full rule's conditions.
        if not s or evidence['quote']!=s.get('text','').strip():continue
        rules.append({'source_id':s['source_id'],'reference':s['reference'],
                      'text':explain(s),'kind':'whole-unit-bounded-explanation',
                      'method_revision':revision(),'source_snapshot':fingerprint(s)})
        conditions_found.extend(conditions(s,question))
    ids={c['condition_id'] for c in conditions_found}
    stale=bool(set(answers)-ids)
    for condition in conditions_found:
        value=answers.get(condition['condition_id']) if not stale else None
        condition['reported_value']=value
        condition['status']=('missing' if value is None else 'unknown' if value=='unknown' else
                              'user-reported-met' if value==condition['required_value'] else 'user-reported-not-met')
    return {'rules':rules,'conditions':conditions_found,'stale_answers':stale,
            'case_ruling_verified':False,'human_review':'required',
            'scope':'whole-unit style equivalence and reported predicate only; not general entailment'}
