"""Source-pinned entity relationships. Model suggestions never become edges."""
import hashlib,json,re,sqlite3,time
from pathlib import Path
from .hebrew import strip_niqqud
from .source_snapshot import admissible,fingerprint

BIBLE_BOOKS=('בראשית','שמות','ויקרא','במדבר','דברים','יהושע','שופטים','שמואל','שמואל א','שמואל ב','שמואל א׳','שמואל ב׳','מלכים','מלכים א','מלכים ב','ישעיהו','ירמיהו','יחזקאל','רות','אסתר','דברי הימים')

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
        def add(subject,relation,obj,rule,structured=False,father=None):
            # Values must occur literally in a primary text/metadata record.
            if not structured and relation!='child-count' and (subject not in text or obj not in text):return
            facts.append({'subject':subject,'relation':relation,'object':obj,'source_id':source['source_id'],
                'reference':source['reference'],'version':source['version'],'source_snapshot':pin,
                'quote':source['text'],'method':rule,'support':'bounded-primary-relation',
                'identity_scope':{'qualified_parent':father or (obj if relation in ('father','parent') else None)},
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
            if isinstance(data,dict) and isinstance(data.get('title'),str) and data['title'] and isinstance(data.get('authors'),list):
                for name in data['authors']:
                    if isinstance(name,str) and name:add(data['title'],'author',name,'official-index-author-field',structured=True)
            return facts
        if not biblical(source):return []
        # Explicit plural genealogy: never inferred from co-occurring names.
        for m in re.finditer(r'(?:ושם\s+)?(?:שני\s+)?בני\s+([א-ת]+)\s+([א-ת]+)\s+ו([א-ת]+)(?:\s+(כהנים|כוהנים))?',text):
            parent,c1,c2,role=m.groups()
            complete_pair=bool(re.search(r'שני\s+בני',m[0])) and not re.match(r'\s+ו[א-ת]',text[m.end():])
            for child in (c1,c2):
                add(child,'parent',parent,'explicit-plural-genealogy',father=parent)
                if complete_pair:add(parent,'children',child,'explicit-plural-genealogy-inverse')
                if role:add(child,'role',role,'role-in-explicit-genealogy',father=parent)
            if role and 'ושם' in m[0]:
                place=re.search(r'(?:^|\s)ב([א-ת]+)\s+$',text[:m.start()])
                if place:
                    for child in (c1,c2):add(child,'served_at',place[1],'same-place-explicit-pronoun',father=parent)
        # Marriage + birth in one verse, explicit same subject and pronoun.
        pattern=r'ויקח\s+([א-ת]+)\s+את\s+([א-ת]+)\s+(?:(?:דדתו|דודתו)\s+)?לו\s+לאשה\s+ותלד\s+לו\s+את\s+([א-ת]+)(?:\s+ואת\s+([א-ת]+))?'
        for m in re.finditer(pattern,text):
            father,mother,c1,c2=m.groups();add(father,'wife',mother,'marriage-and-birth-verse')
            for child in (c1,c2):
                if child:
                    add(child,'father',father,'marriage-and-birth-verse');add(child,'mother',mother,'marriage-and-birth-verse',father=father)
                    add(father,'children',child,'explicit-marriage-birth-inverse')
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
        from .entity_questions import qualified,name
        subject,qualifier=qualified(subject)
        if self.path:
            with self.connect() as db:rows=[json.loads(r[0]) for r in db.execute('SELECT payload FROM edges LIMIT 50000')]
        else:rows=list(self.memory.values())
        result=[]
        for edge in rows:
            if name(edge['subject'])!=subject or edge['relation']!=relation:continue
            source=resolver(edge['source_id'])
            if qualifier and name(edge.get('identity_scope',{}).get('qualified_parent') or '')!=qualifier:continue
            if source and admissible(source) and fingerprint(source)==edge['source_snapshot'] and source.get('version')==edge['version'] and edge in self.extract(source):
                result.append(edge)
        return result

JewishKnowledgeGraph=TorahEntityGraph
