"""Lossless condition inventory: text spans, not inferred independent rules."""
import hashlib,re
from .source_snapshot import admissible,fingerprint
MARKERS=r'(?<!\w)(?:אם|ואם|אבל|אלא|ובלבד|בתנאי|רק|כאשר|כל זמן|כל עוד|כש\w+)(?!\w)'

def inventory(source):
    if not admissible(source):return None
    text=source['text'];pin=fingerprint(source);clauses=[]
    for m in re.finditer(r'[^.!?\n]+(?:[.!?]|\n|$)',text):
        quote=m.group()
        if not quote.strip():continue
        conditions=[{'text':c.group(),'start':m.start()+c.start(),'end':m.start()+c.end()} for c in re.finditer(MARKERS,quote)]
        modality=[name for name,pat in [('custom',r'מנהג|נוהגים'),('stringency',r'מחמיר|חומרה'),('obligation',r'חייב|צריך'),('permission',r'מותר|אסור')] if re.search(pat,quote)]
        clauses.append({'unit_id':hashlib.sha256((pin+':'+str(m.span())).encode()).hexdigest()[:24],
            'source_id':source['source_id'],'reference':source['reference'],'source_snapshot':pin,
            'quote':quote,'start':m.start(),'end':m.end(),'condition_markers':conditions,'modality_candidates':modality,
            'kind':'explicit-source-language','support':'text-span-verified-only',
            'independent_quotation_unit':False,'applicability_verified':False})
    return {'source_id':source['source_id'],'source_snapshot':pin,'version':source.get('version',''),
            'clauses':clauses,'conditions_complete':False,'exceptions_complete':False,
            'halachic_verified':False,'warning':'יחידות המשפט אינן היתר להשמיט הקשר או תנאי מן המקור המלא.'}

def current(item,source):
    return bool(admissible(source) and item['source_snapshot']==fingerprint(source)
                and all(source['text'][c['start']:c['end']]==c['quote'] for c in item['clauses']))
