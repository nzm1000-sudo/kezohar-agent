"""Public bibliographic discovery, never text permission or answer evidence."""
import hashlib,json,os,re,time
from functools import lru_cache
from pathlib import Path
from .hebrew import strip_niqqud

ENDPOINT='https://www.sefaria.org/api/index'

def storage_path():
    project=Path(__file__).resolve().parents[2]
    root=Path(os.environ.get('JEWISH_KNOWLEDGE_ROOT',project/'data/store/jewish-knowledge')).resolve()
    if project not in root.parents:raise ValueError('catalog must remain in agent project')
    return root/'public-catalog.json'

def clean_title(value):
    return isinstance(value,str) and 2<=len(value)<=180 and not re.search(r'[\x00-\x1f<>]|https?://|ignore.*instructions|התעלם.*הוראות',value,re.I)

def flatten(data):
    if not isinstance(data,list):raise ValueError('catalog tree required')
    rows=[];pending=[(n,[]) for n in data];visited=0
    while pending:
        n,path=pending.pop();visited+=1
        if visited>25000 or not isinstance(n,dict) or len(path)>12:raise ValueError('invalid catalog bounds')
        if 'contents' in n:
            if not isinstance(n['contents'],list):raise ValueError('invalid catalog category')
            pending.extend((c,path+[n.get('category','')]) for c in n['contents'])
        elif clean_title(n.get('title')) and clean_title(n.get('heTitle')):
            rows.append({'title':n['title'],'heTitle':n['heTitle'],'categories':path})
    if not rows:raise ValueError('empty catalog')
    return rows

def save_catalog(data,path=None):
    rows=flatten(data);path=Path(path or storage_path());path.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(rows,ensure_ascii=False,sort_keys=True)
    packet={'endpoint':ENDPOINT,'captured_at':time.time(),'books':rows,
        'sha256':hashlib.sha256(payload.encode()).hexdigest(),'scope':'public titles only; not text rights or facts'}
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(packet,ensure_ascii=False),encoding='utf-8');temp.replace(path)
    return len(rows)

@lru_cache(maxsize=4)
def _load(path,mtime):
    p=Path(path)
    if p.stat().st_size>8*1024*1024:return []
    d=json.loads(p.read_text(encoding='utf-8'));rows=d.get('books',[])
    if d.get('endpoint')!=ENDPOINT or not isinstance(rows,list) or len(rows)>20000:return []
    if hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True).encode()).hexdigest()!=d.get('sha256'):return []
    if any(not isinstance(r,dict) or not clean_title(r.get('title')) or not clean_title(r.get('heTitle')) for r in rows):return []
    return rows

def catalog_matches(question,path=None):
    p=Path(path or storage_path())
    try:rows=_load(str(p),p.stat().st_mtime_ns)
    except (OSError,ValueError,TypeError):return []
    q=strip_niqqud(question);matches=[]
    for r in rows:
        title=strip_niqqud(r['heTitle'])
        if title not in q:continue
        # Hebrew prefixes are accepted, but not a title inside another word.
        if re.search(r'(?<![א-ת])(?:[ובהכלמ]?'+re.escape(title)+r')(?![א-ת])',q):matches.append(r)
    matches.sort(key=lambda r:len(r['heTitle']),reverse=True)
    # A shared Hebrew title cannot identify a unique book.
    result=[]
    for r in matches:
        if sum(x['heTitle']==r['heTitle'] and x['title']!=r['title'] for x in matches):continue
        if not any(r['heTitle'] in old['heTitle'] for old in result):result.append(r)
    if not result:
        # Unique one-character spelling correction against public book titles.
        # No unknown title is exported, and no author/fact is inferred here.
        m=re.fullmatch(r'מי (?:כתב|חיבר) (?:את )?([^?\n]{5,180})\??',q.strip())
        if m:
            written=m[1].strip()
            def one_edit(a,b):
                if abs(len(a)-len(b))>1:return False
                if len(a)==len(b):return sum(x!=y for x,y in zip(a,b))==1
                if len(a)>len(b):a,b=b,a
                return any(b[:i]+b[i+1:]==a for i in range(len(b)))
            nearby=[r for r in rows if one_edit(written,strip_niqqud(r['heTitle']))]
            if len(nearby)==1:result=[dict(nearby[0],search_spelling_hint=written)]
    return result[:4]

def catalog_status():
    p=storage_path()
    try:count=len(_load(str(p),p.stat().st_mtime_ns))
    except (OSError,ValueError,TypeError):count=0
    return {'public_books':count,'scope':'title discovery; source verification required','book_bodies_copied':False}
