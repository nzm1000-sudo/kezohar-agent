"""Query interpretation is a retrieval aid, never evidence for a ruling."""
import re
from .hebrew import normalize

ALIASES = {
    'שו"ע': 'שולחן ערוך', 'שו״ע': 'שולחן ערוך',
    'או"ח': 'אורח חיים', 'או״ח': 'אורח חיים',
    'יו"ד': 'יורה דעה', 'יו״ד': 'יורה דעה',
    'נטבנ"ט': 'נותן טעם בר נותן טעם', 'נ״ט בר נ״ט': 'נותן טעם בר נותן טעם',
    'בדיעבד': 'דיעבד', 'לכתחילה': 'לכתחלה',
    'אשתהי': 'המתנה', 'אישתלי': 'שכח', 'אכתי': 'עדיין',
}
SPELLINGS = (('שולחן','שלחן'), ('תפילה','תפלה'), ('תפילת','תפלת'),
             ('ראש חודש','ראש חדש'), ('יעלה ויבוא','יעלה ויבא'), ('לכתחילה','לכתחלה'))


def interpret(question):
    q = normalize(question)
    expansions = [value for alias, value in ALIASES.items() if normalize(alias) in q]
    for alternatives in SPELLINGS:
        if any(normalize(word) in q for word in alternatives):expansions.extend(alternatives)
    possible = []
    oil = ('שמנ' in q and any(t in q for t in ('שניצל', 'בשר'))
           and any(t in q for t in ('ציפס', "צ'יפס", 'טיג', 'טוג')))
    waiting = any(t in q for t in ('לחכות', 'להמתינ', 'שש שעות', 'מחכ'))
    if oil:
        possible = ['שמן שטיגנו בו בשר', 'תבשיל של בשר', 'טעם כעיקר',
                    'נותן טעם בר נותן טעם', 'שומן בשר', 'שיירי בשר']
        if waiting: possible.insert(0, 'המתנה בין בשר לחלב')
        expansions.extend(possible)
    # Parse only what was written. This is not a canonical citation, and does
    # not supply missing seif numbers or establish which edition was intended.
    references = []
    pattern = r'(?:סימן|סי[\'׳])\s+([א-ת\"״׳\'0-9]+)(?:\s*[,;]?\s*(?:סעיף|ס[\"״]ק)\s+([א-ת\"״׳\'0-9]+))?'
    for match in re.finditer(pattern, question):
        references.append({'literal': match.group(0), 'siman_as_written': match.group(1),
                           'seif_as_written': match.group(2), 'status': 'query-hint-only'})
    books = [title for title in ('שולחן ערוך', 'ילקוט יוסף', 'חזון עובדיה', 'יביע אומר',
                                'יחוה דעת', 'משנה ברורה', 'כף החיים', 'בית יוסף')
             if normalize(title) in normalize(' '.join([question] + expansions))]
    return {'expansions': list(dict.fromkeys(expansions)), 'possible_topics': possible,
            'reference_hints': references, 'work_hints': books,
            'shared_oil_candidate': oil, 'waiting_requested': waiting,
            'dairy_target_explicit': any(t in q for t in ('חלב', 'גבינה')),
            'method': 'curated query expansion; no doctrine inferred'}


class SourceDiscoveryAgent:
    def __init__(self, agent):
        self.agent = agent

    def discover(self, question, top_k=5, retrieved_sources=None, request_budget=None):
        from .retrieval_budget import accepts_budget
        if request_budget:request_budget.check('source discovery')
        analysis = interpret(question)
        if retrieved_sources is None:
            kwargs={'top_k':top_k}
            if request_budget and accepts_budget(self.agent.search_only):kwargs['request_budget']=request_budget
            sources=self.agent.search_only(question,**kwargs)
        else:sources=retrieved_sources
        # Hints cannot manufacture an identity or turn a pending row into RAG.
        return {'sources': sources, 'query_analysis': analysis,
                'search_status':getattr(sources,'status',{'partial':False,'errors':[]}),
                'reused_retrieval': retrieved_sources is not None}
