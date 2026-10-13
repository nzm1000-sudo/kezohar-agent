"""Source genre and necessary case coverage; never a semantic psak verifier.

Domain, authority, tradition, relevance and evidence remain separate. A hosting
site's reputation does not turn every hosted document into a halachic source.
"""
import re
from urllib.parse import unquote, urlsplit
from .hebrew import normalize


def classify(source):
    title = source.get('work_title', '')
    label = title + ' ' + unquote(urlsplit(source.get('source_url', '')).path).replace('_',' ')
    # A contents/index entry is a locator aid, not the complete ruling unit.
    if re.search(r'מפתחות|תוכן עניינימ|תוכן עניינים',normalize(source.get('reference',''))):
        return {'domain':'torah-study','source_type':'reference-index',
                'halachic_authority':'unclassified','classification_basis':'explicit index locator'}
    # Title/path override claimed metadata: Wikisource also hosts Israeli laws.
    if (re.search(r'(?:תקנות|פקודת)\s+[א-ת]', label)
            or re.search(r'חוק\s+(?:התקשורת|העונשין|שירות|רישוי|יסוד)|צו\s+(?:הפיקוח|רישוי)', label)):
        return {'domain': 'civil-law', 'source_type': 'civil-regulation',
                'halachic_authority': 'none', 'classification_basis': 'civil title/path'}
    registry = (
        ('חזון עובדיה', 'psak-code', 'sephardi-posek'),
        ('יביע אומר', 'responsa', 'sephardi-posek'),
        ('יחוה דעת', 'responsa', 'sephardi-posek'),
        ('קיצור שולחן ערוך – ילקוט יוסף', 'psak-code', 'sephardi-posek'),
        ('שולחן ערוך', 'psak-code', 'maran'),
        ('בית יוסף', 'halachic-commentary', 'maran'),
        ('בן איש חי', 'psak-code', 'sephardi-posek'),
        ('כף החיים', 'halachic-commentary', 'sephardi-posek'),
        ('כף חיים', 'halachic-commentary', 'sephardi-posek'),
        ('עונג שבת', 'psak-code', 'sephardi-posek'),
        ('ילקוט יוסף', 'psak-code', 'sephardi-posek'),
        ('רב פעלים', 'responsa', 'sephardi-posek'),
        ('משנה ברורה', 'halachic-commentary', 'ashkenazi-posek'),
        ('קיצור שולחן ערוך', 'psak-code', 'ashkenazi-posek'),
        ('קיצור שלחן ערוך', 'psak-code', 'ashkenazi-posek'),
        ('ערוך השולחן', 'halachic-commentary', 'ashkenazi-posek'),
        ('טור', 'psak-code', 'rishon'),
        ('חבל נחלתו', 'responsa', 'posek-tradition-unclassified'),
    )
    for prefix, kind, authority in registry:
        if title.startswith(prefix):
            return {'domain': 'halacha', 'source_type': kind,
                    'halachic_authority': authority, 'classification_basis': 'curated work title'}
    # The Radzin chassidic work and other works can share this title.
    if title.startswith('סוד ישרים') and ('radzin' in source.get('author','').lower()
            or 'chassidut' in source.get('source_file','')):
        domain, kind = 'torah-study', 'mysticism'
    elif source.get('category') in ('chassidut','kabbalah'):
        domain, kind = 'torah-study', 'mysticism'
    elif (title.startswith(('משנה ', 'תלמוד ', 'בבלי ', 'ירושלמי ', 'עבודה זרה', 'רמב"ם', 'רמב״ם', 'ספרי ', 'ויקרא', 'בראשית'))
          or re.match(r'(?:ברכות|פסחים|שבת|נדרים|חולין|קידושין)\s+[א-ת]+\s+[אב](?:\s|$)',title)):
        domain, kind = 'torah-study', 'primary-torah-text'
    elif source.get('category') in ('halacha', 'responsa'):
        domain, kind = 'halacha', source['category']
    elif re.search(r'הלכה|הלכות|שו[״"]ת|שאלות ותשובות', title):
        domain, kind = 'halacha', 'ruling-candidate'
    else:
        domain, kind = 'unknown', 'unclassified'
    return {'domain': domain, 'source_type': kind,
            'halachic_authority': 'unclassified', 'classification_basis': 'genre only; authority unverified'}


def applicability_issue(question, text):
    """Necessary scenario facets, not proof of entailment or a reference answer."""
    q, t = normalize(question), normalize(text)
    # Retrieval aliases may match a neighbouring action (e.g. a physical
    # interruption compared with speech). That is not evidence for the asked
    # action. Require explicit speech language, independently of book priority.
    if (any(w in q for w in ('תפילינ','תפלינ')) and 'בינ' in q
            and any(w in q for w in ('לדבר','דיבור','דבור','בשיחה','לשוחח','לפטפט'))):
        if not re.search(r'(?:להפסיק|יפסיק).{0,15}(?:בדיבור|בדבור|בשיחה|בדברימ)|(?:מותר|אסור|אינ|לא).{0,15}(?:לדבר|ישיח)', t):
            return 'explicit speech interruption absent; related action is not a substitute'
    # A general topic does not establish the particular requested facet. These
    # are necessary textual checks only, never an inference of the ruling.
    if 'ברכת המזונ' in q:
        facets=[(('נשימ','אישה','אשה'),('נשימ','אישה','אשה')),
                (('מסופק','מסופקימ','ספק'),('ספק','מסופק')),
                (('בישיבה','בעמידה'),('ישיבה','יושב','בישיבה','בעמידה','עומד'))]
        for asked,required in facets:
            if any(w in q for w in asked) and not any(w in t for w in required):
                return 'requested meal-blessing facet absent; timing rule is not a substitute'
    if 'שבת' in q and any(w in q for w in ('להתקלח','מקלחת')):
        if not any(w in t for w in ('כל גופו','כל הגופ','רוב גופו','מקלחת','להתקלח')):
            return 'whole-body bathing absent; washing face/hands/feet is not a shower ruling'
    if 'שבת' in q and any(w in q for w in ('תרופה','תרופות','גלולה')):
        if not any(w in t for w in ('תרופה','תרופות','גלולה','גלולות','כדורימ','כדורי','רפואות')):
            return 'medication subject absent; food eaten for health is not a medication ruling'
    if (any(w in q for w in ('מצאתי','מוצא','מציאה'))
            and any(w in q for w in ('כספ','מעות','מטבע')) and 'שבת' not in q):
        ownership=('אבדה','אבידה','יאוש','ייאוש','סימנ','להכריז','הרי אלו שלו','הרי אלוה שלו','זכה','זוכה')
        if not any(w in t for w in ownership):
            return 'lost-money ownership absent; movement of money is not permission to acquire it'
    if (any(w in q for w in ('לטבול','טבילה','טובל')) and ('ביומ' in q or 'בלילה' in q)):
        explicit_purity='לטהרה' in q and any(w in q for w in ('אישה','אשה'))
        if not explicit_purity and not any(w in q for w in ('טבילת אישה','טבילת אשה','נדה','נידה','טבילת כלימ','כלי','טבילת גבר','כמנהג')):
            return 'immersion purpose unspecified; distinct types cannot be assumed'
        if 'טבילת כלימ' in q and not any(w in t for w in ('כלי','כלימ')):
            return 'vessel immersion not established by personal ritual immersion'
        if (explicit_purity or any(w in q for w in ('טבילת אישה','טבילת אשה','נדה','נידה'))) and not any(w in t for w in ('נדה','נידה','אשה','אישה','נשימ')):
            return 'personal purity subject not established by vessel or custom immersion'
        clauses=[normalize(c) for c in re.split(r'[.!?;:\n]',text)]
        if not any(re.search(r'(?:טביל|לטבול|טובל|יטבול|תטבול).{0,100}(?:ביומ|בליל)|(?:ביומ|בליל).{0,100}(?:טביל|לטבול|טובל|יטבול|תטבול)',c) for c in clauses):
            return 'immersion timing absent; bathing time does not prove immersion time'
    if 'דג' in q and 'חלב' in q:
        # Kashrut of each item alone does not answer mixing fish and milk.
        if not (re.search(r'(?:דג(?:ימ)?\s+(?:עמ\s+(?:ה)?חלב|בחלב)|חלב\s+עמ\s+דג|דג.{0,40}(?:תערובת|תערב|לבשל.{0,12}בחלב))', t)
                or re.search(r'(?:לאכול|לאכל|אכיל|לבשל|סכנה).{0,60}(?:דג(?:ימ)? וחלב|חלב ודג)', t)):
            return 'fish/milk combination not established'
    if 'דג' in q and 'בשר' in q and 'חלב' not in q:
        if not re.search(r'(?:דג(?:ימ)?\s+(?:עמ\s+(?:ה)?בשר|ובשר|בבשר)|בשר\s+(?:עמ\s+דג|ודג)|דג.{0,60}(?:לאכל|לאכול|סכנה|תערובת).{0,60}בשר)',t):
            return 'fish/meat combination absent; meat/milk rule is not a substitute'
    if any(w in q for w in ('להטביל','טבילת כלימ')):
        if not any(w in t for w in ('טביל','להטביל','מטביל','לטבול','יטבול')):
            return 'immersion action absent; kashering is a different operation'
        if 'פלסטיק' in q and not any(w in t for w in ('פלסטיק','פלסטיכ','פלאסטיק','פלאסטיכ')):
            return 'requested vessel material absent; other materials cannot establish its rule'
    if 'שהחיינו' in q and any(w in q for w in ('לפני', 'קודמ', 'סדר')):
        if not ('שהחיינו' in t and any(w in t for w in ('קודמ', 'לפני', 'תחילה', 'אחר ככ'))):
            return 'order of blessings absent'
    if 'תפילת הדרכ' in q and any(w in q for w in ('מתי', 'מאימתי')):
        if not ('תפילת הדרכ' in t and any(w in t for w in ('פרסה', 'יצא', 'יציאה', 'החזיק', 'בדרכ'))):
            return 'travel prayer timing absent'
    if 'מיחמ' in q and any(w in q for w in ('להוסיפ', 'להכניס')):
        if not re.search(r'(?:להוסיפ|להכניס|לתת|לשפוכ|לערות).{0,90}(?:למיחמ|לתוכ המיחמ|במיחמ)', t):
            return 'water into urn absent; reverse direction is insufficient'
    return None


def exclusion_reason(question, source, web=False):
    from .ranking import intent_issue
    from .semantic_claims import units_for
    quality = classify(source)
    if quality['domain'] == 'civil-law':
        return 'civil document cannot support halachic ruling'
    if quality['source_type']=='reference-index':
        return 'source is a contents/index entry; locate the complete source unit'
    if quality['source_type'] == 'mysticism':
        return 'mystical study is not an applicable ruling source'
    if web and quality['domain'] == 'unknown':
        return 'web document genre unverified'
    if units_for(question,source):
        return None  # pinned full text + locator resolves anaphoric wording, not token overlap
    return intent_issue(question,source) or applicability_issue(question, source.get('text', ''))


def web_locator_issue(title, url):
    """Verify Wikisource page title against its URL; never infer siman/seif."""
    parsed = urlsplit(url)
    if parsed.hostname != 'he.wikisource.org':
        return None
    if not parsed.path.startswith('/wiki/'):
        return 'Wikisource canonical page locator absent'
    page = unquote(parsed.path[len('/wiki/'):]).replace('_', ' ')
    declared = re.sub(r'\s*[-–—|]\s*ויקיטקסט\s*$', '', title).strip()
    if normalize(page) != normalize(declared):
        return 'Wikisource page title and URL disagree'
    return None
