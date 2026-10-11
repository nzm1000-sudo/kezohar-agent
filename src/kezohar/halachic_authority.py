"""Curated authority and tradition, separate from relevance and claim support."""
from .hebrew import normalize
from .source_quality import classify


def profile(source):
    quality=classify(source)
    title=normalize(source.get('work_title',''))
    author=normalize(source.get('author',''))
    tradition=source.get('tradition','')
    authority=quality['halachic_authority']
    if authority=='maran': tradition='sephardi'
    elif title.startswith(('חזונ עובדיה','יביע אומר','יחוה דעת')) and any(name in author for name in ('עובדיה יוספ','ovadia yosef','ovadiah yosef')):
        tradition='sephardi';authority='rav-ovadia-yosef'
    elif 'ילקוט יוספ' in title and quality['domain']=='halacha':
        tradition='sephardi';authority='yalkut-yosef'
    elif authority=='sephardi-posek': tradition='sephardi'
    elif authority=='ashkenazi-posek': tradition='ashkenazi'
    source_type=quality['source_type']
    role=('foundation' if source_type=='primary-torah-text' else
          'practical-ruling' if source_type in ('psak-code','responsa') else 'context')
    if source.get('book_id')=='Beit_Yosef' or title.startswith('בית יוספ'):role='foundation-and-analysis'
    return {'authority':authority,'tradition':tradition,'role':role,
            'edition':source.get('version') or 'unknown',
            'embedded_other_views':any(t in source.get('text','') for t in ('הרמ״א','הרמ"א','הגה ')),
            'attribution_scope':'work identity; individual passages may quote other opinions',
            'evidence_support':'not-established-by-authority'}


def selection_key(source, question, tradition):
    """Contextual prompt selection, never a score that adjudicates a dispute.

    Specific case coverage takes precedence over the preferred work. A Talmud
    passage is a foundation, not automatically the practical answer. No author
    or work preference can establish claim support.
    """
    p=source['authority_profile']
    study=any(word in question for word in ('יסוד הדין','מקור בתלמוד','טעם הדין','סוגיה'))
    desired_role=('foundation','foundation-and-analysis') if study else ('practical-ruling',)
    matching=tradition=='both' or p['tradition']==tradition
    preferred=p['authority'] in ('maran','rav-ovadia-yosef','yalkut-yosef') and tradition!='ashkenazi'
    source['selection_policy']={'requested_tradition':tradition,'purpose':'study' if study else 'practical-case',
                                'role_matches':p['role'] in desired_role,
                                'preferred_sephardic_work':preferred,
                                'basis':'case coverage, role and tradition; not an adjudication'}
    contextual=(p['role'] not in desired_role,not matching) if study else (not matching,p['role'] not in desired_role)
    return (-source.get('case_coverage',0), contextual,
            -source.get('topical_overlap',0), not preferred,
            p['authority']!='maran' if preferred else False,
            p['authority']!='rav-ovadia-yosef' if preferred else False,
            -source.get('score',0))


def differences(question, sources):
    """Report explicit attributed difference language, never infer machloket by polarity."""
    import re
    from .ranking import topic_overlap
    result=[]
    for s in sources:
        if topic_overlap(s.get('text',''),question)==0:continue
        for sentence in re.split(r'(?<=[.!?])\s+|\n+', s.get('text','')):
            aliases={'מרן':('מרן',),'הרמ״א':('הרמ״א','הרמ"א'), 'הרב עובדיה':('הרב עובדיה',),
                     'ילקוט יוסף':('ילקוט יוסף',),'האשכנזים':('האשכנזים',),'הספרדים':('הספרדים',)}
            names=[name for name,forms in aliases.items() if any(form in sentence for form in forms)]
            if len(names)>=2 and any(w in sentence for w in ('חולק','לעומת','אבל','ואילו','נחלק','אולם')):
                result.append({'source_ids':[s['source_id']], 'reference':s['reference'],
                               'quote':sentence,'named_views':names,
                               'status':'attributed-difference-candidate; human-context-review-required',
                               'halachic_verified':False})
    return result[:5]
