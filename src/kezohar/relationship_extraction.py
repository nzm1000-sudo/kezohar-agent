"""Exact locator witnesses yield proposals, never automatic agreement edges."""
import re
from .source_snapshot import admissible,fingerprint
RELATION_MARKERS={
    'disagrees':r'חולק|חלק עליו|אינו מסכים','qualifies':r'ובלבד|בתנאי|דוקא|דווקא',
    'adds-condition':r'בתנאי|הוסיף|צריך גם','custom':r'מנהג|נוהגים',
    'reported-view':r'יש אומרים|כתב בשם|הביא בשם','interprets':r'פירש|מבאר|הסביר'}

def mentions(source):
    if not admissible(source):return []
    # Capture exactly the written bibliography; never invent missing seif,
    # edition, page or endpoint ID. Resolution/review is a separate operation.
    pattern=r'(?:ילקוט יוסף|ילקו[״\"\']+י|יביע אומר|יחוה דעת|חזון עובדיה|שולחן ערוך|שלחן ערוך|שו[״\"]ע|משנ[״\"]ב|בית יוסף|בן איש חי)[^\n\].;]{0,150}'
    return [{'source_id':source['source_id'],'source_snapshot':fingerprint(source),
             'quote':m.group(),'start':m.start(),'end':m.end(),
             'target_source_id':None,'status':'unresolved-bibliographic-mention',
             'usable_as_claim_support':False,'halachic_verified':False}
            for m in re.finditer(pattern,source['text'])][:20]

def proposals(sources):
    sources=[s for s in sources if admissible(s)];out=[]
    for a in sources:
        for b in sources:
            if a['source_id']==b['source_id']:continue
            locator=b['reference'];start=a['text'].find(locator)
            if start<0:continue
            left=max(a['text'].rfind('\n',0,start),a['text'].rfind('.',0,start))+1
            ends=[n for n in (a['text'].find('\n',start),a['text'].find('.',start+len(locator))) if n>=0]
            end=min(ends)+1 if ends else len(a['text'])
            quote=a['text'][left:end]
            relation=next((name for name,pat in RELATION_MARKERS.items() if re.search(pat,quote)),'cites')
            out.append({'subject':a['source_id'],'object':b['source_id'],'relation':relation,
                'quote':quote,'start':left,'end':end,'locator_span':[start,start+len(locator)],
                'subject_snapshot':fingerprint(a),'object_snapshot':fingerprint(b),
                'status':'proposed','technical_certainty':'literal-locator-witness',
                'relation_meaning_verified':False,'usable_as_claim_support':False,'halachic_verified':False})
    return out[:40]

def persist(graph,sources):
    index={s['source_id']:s for s in sources};rows=proposals(sources)
    for row in rows:
        row['edge_id']=graph.propose(index[row['subject']],index[row['object']],row['relation'],
            'literal locator plus explicit relation-language candidate',quote=row['quote'],witness=index[row['subject']])
    return rows
