"""Curated authority and tradition, separate from relevance and claim support."""
from .hebrew import normalize
from .source_quality import classify


def profile(source):
    quality=classify(source)
    title=normalize(source.get('work_title',''))
    author=normalize(source.get('author',''))
    rank=5
    tradition=source.get('tradition','')
    authority=quality['halachic_authority']
    if authority=='maran': rank=0;tradition='sephardi'
    elif title.startswith(('חזונ עובדיה','יביע אומר','יחוה דעת')) and any(name in author for name in ('עובדיה יוספ','ovadia yosef','ovadiah yosef')):
        rank=1;tradition='sephardi';authority='rav-ovadia-yosef'
    elif 'ילקוט יוספ' in title and quality['domain']=='halacha':
        rank=2;tradition='sephardi';authority='yalkut-yosef'
    elif authority=='sephardi-posek': rank=3;tradition='sephardi'
    elif authority=='ashkenazi-posek': rank=4;tradition='ashkenazi'
    return {'authority':authority,'priority':rank,'tradition':tradition,
            'embedded_other_views':any(t in source.get('text','') for t in ('הרמ״א','הרמ"א','הגה ')),
            'attribution_scope':'work identity; individual passages may quote other opinions',
            'evidence_support':'not-established-by-authority'}


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
