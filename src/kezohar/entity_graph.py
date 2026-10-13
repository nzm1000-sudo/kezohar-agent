"""Source-pinned entity relationships. Model suggestions never become edges."""
import hashlib,json,re,sqlite3,time
from pathlib import Path
from .hebrew import strip_niqqud
from .source_snapshot import admissible,fingerprint

BIBLE_BOOKS=('בראשית','שמות','ויקרא','במדבר','דברים','יהושע','שופטים','שמואל','מלכים','ישעיהו','ירמיהו','יחזקאל','רות','אסתר','דברי הימים')

def biblical(source):
    return (source.get('metadata',{}).get('knowledge_primary_kind')=='biblical-text'
        or source.get('work_title','') in BIBLE_BOOKS)

class TorahEntityGraph:
    def __init__(self,path=None):
        self.path=Path(path) if path else None;self.memory={}
        if self.path:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with self.connect() as db:db.execute('CREATE TABLE IF NOT EXISTS edges(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    def connect(self):return sqlite3.connect(str(self.path),timeout=2)
    @staticmethod
    def extract(source):
        if not admissible(source) or not source.get('version'):return []
        meta=source.get('metadata',{})
        if meta.get('private') is True or meta.get('visibility')=='private' or meta.get('owner_id') or meta.get('user_id'):return []
        facts=[];text=strip_niqqud(source['text'].replace('־',' '));text=re.sub(r'\s+',' ',text);pin=fingerprint(source)
        def add(subject,relation,obj,rule):
            # Values must occur literally in a primary text/metadata record.
            if relation!='child-count' and (subject not in text or obj not in text):return
            facts.append({'subject':subject,'relation':relation,'object':obj,'source_id':source['source_id'],
                'reference':source['reference'],'version':source['version'],'source_snapshot':pin,
                'quote':source['text'],'method':rule,'support':'bounded-primary-relation',
                'halachic_verified':False,'human_review':'not-a-halachic-ruling'})
        if source.get('metadata',{}).get('knowledge_primary_kind')=='secondary-encyclopedia':
            from .question_intent import PUBLIC_ENTITIES
            subject=source.get('metadata',{}).get('encyclopedia_title','')
            for match in re.finditer(r'(?:מתלמידי|תלמידו של|תלמיד של)\s+([^,.\n]{1,70})',text):
                for name in PUBLIC_ENTITIES:
                    if name!=subject and match[1].startswith(name) and subject in text:
                        add(subject,'teacher',name,'encyclopedia-explicit-student-attribution')
                        facts[-1]['support']='reported-secondary-relationship'
            return facts
        if source.get('metadata',{}).get('knowledge_primary_kind')=='bibliographic-metadata':
            data=json.loads(source['text'])
            if data.get('title') and isinstance(data.get('authors'),list):
                for name in data['authors']:
                    if isinstance(name,str) and name:add(data['title'],'author',name,'official-index-author-field')
            return facts
        if not biblical(source):return []
        # Marriage + birth in one verse, explicit same subject and pronoun.
        pattern=r'ויקח\s+([א-ת]+)\s+את\s+([א-ת]+)\s+(?:(?:דדתו|דודתו)\s+)?לו\s+לאשה\s+ותלד\s+לו\s+את\s+([א-ת]+)(?:\s+ואת\s+([א-ת]+))?'
        for m in re.finditer(pattern,text):
            father,mother,c1,c2=m.groups();add(father,'wife',mother,'marriage-and-birth-verse')
            for child in (c1,c2):
                if child:add(child,'father',father,'marriage-and-birth-verse');add(child,'mother',mother,'marriage-and-birth-verse')
        for m in re.finditer(r'ותהר\s+([א-ת]+)\s+ותלד\s+בן\s+ותקרא\s+את\s+שמו\s+([א-ת]+)',text):
            add(m[2],'mother',m[1],'named-mother-and-naming-birth-verse')
        for m in re.finditer(r'([א-ת]+)\s+בן\s+([א-ת]+)',text):
            if m[1] not in ('כל','איש','ויהי','אחד','אשר'):add(m[1],'father',m[2],'explicit-ben-lineage')
        numbers={'שנים עשר':12,'שנים-עשר':12,'שלושה':3,'שלשה':3,'ארבעה':4,'חמשה':5,'חמישה':5}
        for wording,count in numbers.items():
            for m in re.finditer(r'בני\s+([א-ת]+)\s+'+wording,text):add(m[1],'child-count',str(count),'explicit-children-count')
        return facts
    def ingest(self,source):
        edges=self.extract(source)
        for edge in edges:
            key=hashlib.sha256(json.dumps(edge,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if self.path:
                with self.connect() as db:
                    if db.execute('SELECT count(*) FROM edges').fetchone()[0]<50000:
                        db.execute('INSERT OR IGNORE INTO edges VALUES(?,?)',(key,json.dumps(edge,ensure_ascii=False)))
            else:self.memory[key]=edge
        return edges
    def find(self,subject,relation,resolver):
        if self.path:
            with self.connect() as db:rows=[json.loads(r[0]) for r in db.execute('SELECT payload FROM edges LIMIT 50000')]
        else:rows=list(self.memory.values())
        result=[]
        for edge in rows:
            if edge['subject']!=subject or edge['relation']!=relation:continue
            source=resolver(edge['source_id'])
            if source and admissible(source) and fingerprint(source)==edge['source_snapshot'] and source.get('version')==edge['version']:
                result.append(edge)
        return result

JewishKnowledgeGraph=TorahEntityGraph
