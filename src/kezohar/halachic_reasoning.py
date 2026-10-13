"""Evidence inventory and case distinctions; not a general entailment engine."""
import re
from .ranking import topic_overlap
from .semantic_claims import units_for
from .halachic_authority import differences

DISTINCTIONS = {
    'initial-versus-occurred': ('לכתחילה', 'לכתחלה', 'בדיעבד'),
    'obligation-versus-custom': ('מנהג', 'חיוב'),
    'dry-versus-liquid': ('יבש', 'לח'),
    'vessel-age': ('בן יומו', 'אינו בן יומו'),
    'substance-versus-taste': ('ממשות', 'טעם'),
    'torah-versus-rabbinic': ('מן התורה', 'מדרבנן'),
}


class HalachicReasoningAgent:
    def analyze(self, question, question_analysis, sources):
        from .rule_inventory import inventory
        inventories=[i for s in sources if (i:=inventory(s)) is not None]
        supported = []
        distinctions = []
        for source in sources:
            if topic_overlap(source.get('text', ''), question) == 0: continue
            for unit in units_for(question, source):
                supported.append({'source_id': source['source_id'], 'evidence_id': unit['evidence_id'],
                                  'quote': unit['quote'], 'conditions': unit['conditions'],
                                  'status': 'bounded-source-pinned-statement'})
            for sentence in re.split(r'(?<=[.!?])\s+|\n+', source.get('text', '')):
                if topic_overlap(sentence, question) == 0: continue
                for name, markers in DISTINCTIONS.items():
                    present = [m for m in markers if m in sentence]
                    if len(present) >= 2:
                        distinctions.append({'kind': name, 'source_id': source['source_id'],
                                             'quote': sentence, 'markers': present,
                                             'status': 'source-language-candidate; applicability-not-proved'})
        components={
            'shared-oil':('בירור המתנה לאחר אכילה','מאכל שטוגן ושמן הטיגון'),
            'rice':('בירור ברכה','אורז'),
            'yaaleh-shachrit':('בירור השלמת תפילה','יעלה ויבוא בשחרית'),
            'travel':('בירור זמן אמירה','תפילת הדרך'),
            'tea':('בירור הכנה בשבת','תה וכלי שני'),
            'phone-shabbat':('בירור טלטול בשבת','טלפון'),
            'water-urn':('בירור הוספת מים','מיחם'),
        }
        act,obj=components.get(question_analysis['intent'],('לא סווג באופן מבוקר','לא סווג באופן מבוקר'))
        return {'case': {'intent': question_analysis['intent'], 'requested_act':act,'object_or_food':obj,
                         'component_scope':'bounded interpretation of requested subject, not assumed occurrence',
                         'user_circumstances': {k:v for k,v in question_analysis['circumstances'].items()
                                               if question_analysis.get('fact_origins',{}).get(k)!='policy-default'},
                         'tradition_policy':question_analysis['circumstances']['tradition'],
                         'fact_origins':question_analysis.get('fact_origins',{}),
                         'missing_fields': question_analysis['missing_fields'],
                         'requested_ruling': question},
                'supported_statement_units': supported, 'distinction_candidates': distinctions[:8],
                'rule_inventories':inventories,
                'difference_candidates': differences(question, sources),
                'unresolved': ['טענות שאינן בקטלוג והשוואת מחלוקות בין מקורות דורשות בדיקה אנושית'],
                'halachic_verified': False}
