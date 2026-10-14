"""Public thematic search hints and source genres; never statements of law."""
TOPICS=('חסידות','ברסלב','חב״ד','התבודדות','תניא','סיפורי מעשיות','שבחי הבעש״ט',
        'ליקוטי מוהר״ן','קדושת לוי','נועם אלימלך','אהבת ישראל','תשובה','שמחה',
        'מידות','מוסר','מסילת ישרים','חובות הלבבות','אמונה','ביטחון','השגחה פרטית',
        'קבלה','צמצום','ספירות','עץ חיים','שערי קדושה','ספר יצירה','זוהר',
        'סיפורי צדיקים','הבעל שם טוב','רבי נחמן מברסלב','שניאור זלמן מליאדי',
        'תפילה','סידור','פיוט','מנהגים','חגים','שבת','צדקה','שמיטה','כשרות','תפילין','שולחן ערוך')

def question_domains(question):
    import re
    out=[]
    if re.search(r'חסידות|ברסלב|חב[״"]ד|התבודדות|תניא|מוהר|אלימלך',question):out.append('chasidut')
    if re.search(r'סיפור|סיפורי|מעשה בצדיק|שבחי',question):out.append('traditional-narrative')
    if re.search(r'קבלה|צמצום|ספירות|עץ חיים|יצירה|שערי קדושה|זוהר',question):out.append('kabbalah')
    if re.search(r'מידות|מוסר|מסילת ישרים|חובות הלבבות|אמונה|ביטחון|השגחה|אהבת ישראל',question):out.append('jewish-thought')
    if re.search(r'תפילה|סידור|פיוט',question):out.append('prayer')
    return out

def source_genre(categories,title):
    if any(word in title for word in ('Sippurei Maasiyot','Shivchei HaBesht')):return 'traditional-narrative'
    if 'Chasidut' in categories:return 'chasidic-teaching'
    if 'Kabbalah' in categories:return 'kabbalistic-teaching'
    if 'Musar' in categories or 'Jewish Thought' in categories:return 'ethical-or-philosophical-teaching'
    if 'Halakhah' in categories:return 'halachic-text-candidate'
    if 'Tanakh' in categories:return 'biblical-text-or-commentary'
    return 'unclassified-text'
