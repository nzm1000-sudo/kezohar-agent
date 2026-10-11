# -*- coding: utf-8 -*-
"""Engineering audit of explicit retrieved statements, not halachic gold answers.

Rules are pinned to full text hashes and stored locators. They authorize bounded
reformulations only; every other paraphrase remains unverified for human review.
"""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
base={s['source_id']:s for s in map(json.loads,(ROOT/'data/store/sources.jsonl').open())}
frozen=json.loads((ROOT/'bench/frozen/halacha_2026-10-11.json').read_text())
tea=next(s for s in frozen['questions'][12]['selected_sources'] if s['work_title']=='עונג שבת')
RULES=[
 ('rice-cooked',base['f9aa579f53dc87c8'],'rice',
  ['לפי הסעיף וההגה, על אורז לבדו שבושל עד שנתמעך מברכים בורא מיני מזונות ואחריו בורא נפשות.',
   'על אורז מבושל לבדו, כשהתמעך, מברכים לפי הקטע מזונות ולבסוף בורא נפשות.'],
  ['אורז לבדו','מבושל עד שנתמעך','סעיף והגה; לא הכרעה בין מסורות'],
  ['על אורז מבושל מברכים המוציא לחם.','על אורז מבושל מברכים נרות.']),
 ('rice-raw',base['f9aa579f53dc87c8'],'rice',
  ['הכוסס אורז מברך לפניו בורא פרי האדמה ואחריו בורא נפשות.',
   'אם כוססים אורז, הברכה הראשונה היא בורא פרי האדמה והאחרונה בורא נפשות.'],
  ['כוסס אורז'],['הכוסס אורז מברך לפניו מזונות.']),
 ('yaaleh-finished',base['fcd456ee2fcfdfb6'],'yaaleh-shachrit',
  ['אם שכח יעלה ויבוא בשחרית של ראש חודש, סיים את תפילתו ועקר את רגליו, עליו לחזור לראש התפילה.',
   'בשחרית של ראש חודש, מי ששכח יעלה ויבוא וכבר סיים ועקר רגליו צריך להתפלל שוב מתחילת התפילה.'],
  ['ראש חודש','שחרית','שכח יעלה ויבוא','סיים ועקר רגליו'],
  ['אם שכח יעלה ויבוא בשחרית של ראש חודש אינו צריך לחזור.']),
 ('tea-second',tea,'tea',
  ['לפי עונג שבת, מעיקר הדין מותר לתת שקית תה בכלי שני, אך טוב להחמיר ולהכין בכלי שלישי.',
   'עונג שבת מתיר מעיקר הדין שקית תה בכלי שני, וממליץ להחמיר ולהשתמש בכלי שלישי.'],
  ['שקית תה','כלי שני','מעיקר הדין','טוב להחמיר בכלי שלישי'],
  ['לפי עונג שבת אסור מעיקר הדין לתת שקית תה בכלי שני.']),
 ('travel-start',base['b8e3cf50c56a9c26'],'travel',
  ['בנסיעה של פרסה לפחות אומרים תפילת הדרך אחרי שהחזיק בדרך, ולכתחילה בפרסה הראשונה.',
   'כאשר יש לו ללכת לפחות פרסה, זמן תפילת הדרך הוא לאחר שהחזיק בדרך; לכתחילה אומרים אותה בפרסה הראשונה.'],
  ['נסיעה של פרסה לפחות','אחר שהחזיק בדרך','לכתחילה בפרסה ראשונה'],
  ['אומרים תפילת הדרך לפני שהחזיק בדרך.']),
 ('meat-wait',base['a66ea6c2f6145764'],'meat-wait',
  ['לפי מרן, אחרי אכילת בשר ממתינים שש שעות לפני אכילת גבינה; גם לאחר מכן יש להסיר בשר שנשאר בין השיניים.',
   'מרן דורש שש שעות בין אכילת בשר לגבינה, ובנוסף הסרת בשר שנותר בין השיניים.'],
  ['אכילת בשר ממש; לא הוכחה לשמן ששימש לבשר','שש שעות','הסרת בשר בין השיניים','דעת מרן; הגה בנפרד'],
  ['לפי מרן אחרי אכילת בשר מותר לאכול גבינה מיד.']),
]
items=[]
for key,s,intent,variants,conditions,contradictions in RULES:
 items.append(dict(evidence_id=key, source_id=s['source_id'],work_title=s['work_title'],reference=s['reference'],
                   source_text_sha256=hashlib.sha256(s['text'].encode()).hexdigest(),
                   quote=s['text'],intent=intent,variants=variants,conditions=conditions,
                   contradicted_examples=contradictions,review_status='engineering-source-reading; human-halachic-review-required'))
p=ROOT/'data/claim_reformulations.json'
p.write_text(json.dumps({'version':1,'method':'bounded whole-statement equivalence pinned to original text; not keyword entailment',
                          'halachic_verified':False,'rules':items},ensure_ascii=False,indent=2)+'\n')
print('Pinned',len(items),'explicit statement reformulations')
