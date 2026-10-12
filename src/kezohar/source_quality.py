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
    if (any(w in q for w in ('תפילינ','תפלינ')) and 'יד' in q and 'ראש' in q
            and any(w in q for w in ('לדבר','דיבור','דבור','בשיחה'))):
        if not re.search(r'(?:להפסיק|יפסיק).{0,15}(?:בדיבור|בדבור|בשיחה|בדברימ)|(?:מותר|אסור|אינ|לא).{0,15}(?:לדבר|ישיח)', t):
            return 'explicit speech interruption absent; related action is not a substitute'
    if 'דג' in q and 'חלב' in q:
        # Kashrut of each item alone does not answer mixing fish and milk.
        if not (re.search(r'(?:דג(?:ימ)?\s+(?:עמ\s+(?:ה)?חלב|בחלב)|חלב\s+עמ\s+דג|דג.{0,40}(?:תערובת|תערב|לבשל.{0,12}בחלב))', t)
                or re.search(r'(?:לאכול|לאכל|אכיל|לבשל|סכנה).{0,60}(?:דג(?:ימ)? וחלב|חלב ודג)', t)):
            return 'fish/milk combination not established'
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
