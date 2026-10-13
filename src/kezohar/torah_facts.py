"""Knowledge answers are verified independently from halachic applicability.

Direct facts require a typed primary relationship. Other outputs are bounded
source readings; the model never supplies a reference or an unchecked fact.
"""
import copy,json,re,sqlite3,time,os
from pathlib import Path
from . import hebrew
from .source_snapshot import admissible,fingerprint,unique_sources
from .question_intent import QuestionIntentRouter
from .entity_graph import TorahEntityGraph
from .jewish_web import JewishKnowledgeWebSearch,knowledge_queries
from .jewish_encyclopedia import JewishEncyclopediaEngine
from .request_budget import RequestBudget,BudgetedAnswerModel,BudgetExceeded
from .llm import LLMUnavailable

class FactSourceStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:db.execute('CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    def connect(self):return sqlite3.connect(str(self.path),timeout=2)
    def remember(self,s):
        if not admissible(s):return
        with self.connect() as db:
            old=db.execute('SELECT payload FROM sources WHERE id=?',(s['source_id'],)).fetchone()
            if old:
                previous=json.loads(old[0]);candidate=dict(s,ingested_at=previous.get('ingested_at',''))
                if fingerprint(candidate)==fingerprint(previous):s=previous
            if old or db.execute('SELECT count(*) FROM sources').fetchone()[0]<300:
                db.execute('INSERT OR REPLACE INTO sources VALUES(?,?)',(s['source_id'],json.dumps(s,ensure_ascii=False)))
        return s
    def get(self,sid):
        with self.connect() as db:r=db.execute('SELECT payload FROM sources WHERE id=?',(sid,)).fetchone()
        return json.loads(r[0]) if r else None

class CrossSourceVerification:
    @staticmethod
    def fact(edge,source):
        if not admissible(source) or fingerprint(source)!=edge['source_snapshot']:return False
        return edge in TorahEntityGraph.extract(source)
    @staticmethod
    def quotation(source,quote):
        # This verifies a reading, NOT a conclusion derived from similar words.
        return admissible(source) and bool(quote.strip()) and quote in source['text']

class _KnowledgeModel:
    def __init__(self,delegate):self.delegate=delegate
    @property
    def identity(self):return self.delegate.identity
    def generate(self,question,sources,timeout=4.5,cancel_event=None):
        method=getattr(self.delegate,'generate_knowledge',self.delegate.generate)
        import inspect
        opts={'timeout':timeout}
        if cancel_event is not None and 'cancel_event' in inspect.signature(method).parameters:opts['cancel_event']=cancel_event
        return method(question,sources,**opts)

class TorahFactAnswerEngine:
    def __init__(self,agent,root=None):
        self.agent=agent
        root=Path(root or os.environ.get('JEWISH_KNOWLEDGE_ROOT') or Path(__file__).resolve().parents[2]/'data/store/jewish-knowledge')
        self.store=FactSourceStore(root/'source-units.sqlite3');self.graph=TorahEntityGraph(root/'entities.sqlite3')
        self.current={};self.fresh=set();self.web=None;self.encyclopedia=None;self.used_web=False;self.errors=[]
    def remember(self,s):
        if s is None or not admissible(s):return
        local=self.agent.knowledge.source_by_id(s['source_id'])
        if not local:s=self.store.remember(s) or s
        self.current[s['source_id']]=s;self.fresh.add(s['source_id']);self.graph.ingest(s)
    def resolve(self,sid,budget,force=False):
        budget.check('knowledge identity revalidation')
        local=self.agent.knowledge.source_by_id(sid,request_budget=budget)
        if local:return local if admissible(local) else None
        if not force and sid in self.fresh:return self.current[sid] if admissible(self.current[sid]) else None
        old=self.current.get(sid) or self.store.get(sid)
        if not old:return None
        try:
            self.used_web=True
            kind=old.get('metadata',{}).get('knowledge_primary_kind')
            if kind=='bibliographic-metadata':
                fresh=self.web.index(old['metadata']['api_index_title'],budget)
                if fresh:fresh['metadata']['api_index_title']=old['metadata']['api_index_title']
            elif kind=='secondary-encyclopedia':fresh=self.encyclopedia.read(old['metadata']['encyclopedia_title'],budget)
            else:fresh=self.web.read(old['source_url'],budget)
            if fresh is None or fresh['source_id']!=sid:return None
            fresh=self.store.remember(fresh) or fresh;self.current[sid]=fresh;self.fresh.add(sid)
            return fresh
        except (OSError,ValueError,LLMUnavailable) as exc:
            self.errors.append({'stage':'knowledge-source-refresh','error':type(exc).__name__});return None
        except Exception as exc:
            self.errors.append({'stage':'knowledge-source-refresh','error':type(exc).__name__});return None
    def facts(self,route,budget):
        if not route['relation'] or not route['entity']:return []
        return self.graph.find(route['entity'],route['relation'],lambda sid:self.resolve(sid,budget))
    def result(self,answer,sources,route,budget,kind='knowledge-reading',facts=None,quotes=None):
        facts=facts or [];quotes=quotes or []
        return {'answer':answer,'sources':sources,'verdict':'fact_supported' if facts else 'knowledge_reading' if quotes else 'knowledge_insufficient',
            'mode':kind,'question_intent':route,'clarifications':[],
            'verification':{'verdict':'ok' if facts or quotes else 'insufficient_context',
                'support':'bounded-primary-relationship' if facts else 'literal-reading-only' if quotes else 'no-direct-support',
                'facts':facts,'evidence':quotes,'general_entailment_verified':False},
            'verification_layers':{'quotation_integrity':'exact' if facts or quotes else 'not-proved',
                'claim_support':'typed-primary-fact' if facts else 'quoted-reading-only' if quotes else 'not-proved',
                'human_review':'required','halachic_verified':False},
            'structured_answer':{'short_answer':answer,'sources':sources,'quotations':[
                {'source_id':s['source_id'],'text':s['text'],'reference':s['reference']} for s in sources] if facts else [
                {'source_id':e['source_id'],'text':e['quote'],'reference':e['reference']} for e in quotes]},
            'answer_status':{'message':'מידע תורני מבוסס מקור; אינו פסיקה הלכתית.'},
            'fact_verified':bool(facts),'human_review':'required','halachic_verified':False,
            'internet_used':self.used_web,'search_status':{'partial':bool(self.errors),'errors':self.errors},
            'knowledge_discovery':{'sources':list(self.current.values())[:50],
                'attempts':self.web.attempts if self.web else [],'method':'bounded relationship and subject routes'},
            'orchestration':{'stages':['question-intent-router','knowledge-retrieval','independent-fact-verification'],
                'budget':budget.report(),'complexity':route['complexity']}}
    def render_facts(self,edges,route,budget):
        if not edges:return None
        # Conflicting explicit objects cannot be resolved by model confidence.
        if len({e['object'] for e in edges})!=1:
            return self.result('נמצאו קשרים שונים במקורות; יש לברר את זהות האדם וההקשר לפני תשובה יחידה.',[],route,budget)
        edge=edges[0];source=self.resolve(edge['source_id'],budget)
        if not source or not CrossSourceVerification.fact(edge,source):return None
        subject,obj=edge['subject'],edge['object']
        labels={'father':'אביו של {} היה {}.','mother':'אמו של {} הייתה {}.',
                'wife':'אשתו של {} הייתה {}.','child-count':'ל{} היו {} בנים.',
                'author':'ברשומת ספריא מופיע {} עם מחבר: {}.'}
        answer=labels.get(edge['relation'],'{} — {}.').format(subject,obj)+' ('+source['reference']+').'
        result=self.result(answer,[source],route,budget,'direct-torah-fact',[edge])
        result['knowledge_context']={'focus_entity':obj,'previous_subject':subject,'previous_relation':edge['relation'],
            'source_id':edge['source_id'],'source_snapshot':edge['source_snapshot']}
        return result
    def local_search(self,route,budget):
        from .ranking import RetrievalQuery
        queries=knowledge_queries(route['normalized_question'],route)
        if not queries:queries=[route['entity'] or route['normalized_question']]
        for query in queries[:2]:
            budget.check('knowledge local retrieval')
            # A separate action/relationship group prevents a frequent name
            # alone winning over a passage explicitly stating the relationship.
            rq=RetrievalQuery(query,[])
            relation_terms={'father':['ותלד','בני','בן'],'mother':['ותהר','אם','ותלד'],
                'wife':['אשת','אשה'],'child-count':['בני'],'teacher':['תלמיד','למד']}
            rq.concept_groups=[frozenset(hebrew.normalize(route['entity']).split())] if route['entity'] else []
            if route['relation'] in relation_terms:rq.concept_groups.append(frozenset(hebrew.normalize(w) for w in relation_terms[route['relation']]))
            found=self.agent.knowledge.search.search(rq,top_k=30,request_budget=budget)
            self.errors.extend(getattr(found,'errors',[]))
            for s in found:
                if admissible(s) and len(s['text'].encode())<=32000:self.remember(s)
            if self.facts(route,budget):break
    def answer(self,question,route,budget,history=None):
        self.web=JewishKnowledgeWebSearch();self.encyclopedia=JewishEncyclopediaEngine(self.web.transport)
        # Follow-up focus is derived anew from verified previous evidence. Raw
        # conversation statements are never accepted as source-backed facts.
        if not route['entity'] and history and route['relation']:
            previous=QuestionIntentRouter().route(history[-1]);previous_edges=self.facts(previous,budget)
            if len({e['object'] for e in previous_edges})==1:
                route=dict(route,entity=previous_edges[0]['object'],domains=previous['domains'])
                route['normalized_question']='מי הייתה אשתו של '+route['entity']+'?' if route['relation']=='wife' else question
        answer=self.render_facts(self.facts(route,budget),route,budget)
        if answer:return answer
        self.local_search(route,budget)
        answer=self.render_facts(self.facts(route,budget),route,budget)
        if answer:return answer
        # Only public registered subjects may be sent outside. A user-written
        # private/unresolved name is never exported by query generation.
        books={'כוזרי':'Kuzari','משנה תורה':'Mishneh Torah, Human Dispositions','הבהיר':'Sefer HaBahir'}
        if route['relation']=='author':
            title=next((v for k,v in books.items() if k in route['normalized_question']),None)
            if title:
                self.used_web=True
                try:
                    s=self.web.index(title,budget)
                    if s:
                        s['metadata']['api_index_title']=title;self.remember(s)
                        route=dict(route,entity=json.loads(s['text'])['title'])
                        answer=self.render_facts(self.facts(route,budget),route,budget)
                        if answer:return answer
                except Exception as exc:self.errors.append({'stage':'bibliography','error':type(exc).__name__})
        if knowledge_queries(question,route):
            self.used_web=True
            for url in self.web.search(question,route,budget,limit=6):
                try:self.remember(self.web.read(url,budget))
                except Exception as exc:self.errors.append({'stage':'knowledge-web-read','error':type(exc).__name__})
                answer=self.render_facts(self.facts(route,budget),route,budget)
                if answer:return answer
            if route['relation'] not in ('father','mother','wife','child-count'):
                try:
                    for title in self.encyclopedia.search(route,budget):self.remember(self.encyclopedia.read(title,budget))
                except Exception as exc:self.errors.append({'stage':'encyclopedia','error':type(exc).__name__})
        # Source reading is useful for explanation/history, but does not create
        # an unchecked direct relationship fact or a personal halachic ruling.
        candidates=list(self.current.values());keywords=knowledge_queries(question,route)
        tokens=hebrew.tokens(' '.join(keywords))
        candidates=sorted(candidates,key=lambda s:-sum(t in hebrew.normalize(s['text']) for t in tokens))[:6]
        if candidates and not route['relation']:
            model=BudgetedAnswerModel(_KnowledgeModel(self.agent.answer_model),budget)
            try:
                generated=model.generate(question,candidates,timeout=min(30,budget.remaining()))
                packet=json.loads(generated['answer']);ids=packet.get('selected_sources') if set(packet)=={'selected_sources'} else None
                if not isinstance(ids,list) or not 1<=len(ids)<=2 or len(set(ids))!=len(ids):raise ValueError('invalid knowledge source selection')
                quotes=[];sources=[]
                for sid in ids:
                    sent=next((s for s in candidates if s['source_id']==sid),None);fresh=self.resolve(sid,budget,force=True)
                    if not sent or not fresh or fingerprint(sent)!=fingerprint(fresh):raise ValueError('knowledge source changed')
                    paragraphs=[p.strip() for p in sent['text'].split('\n') if p.strip() and len(p.strip())<=1500]
                    if not paragraphs:continue
                    p=max(paragraphs,key=lambda p:sum(t in hebrew.normalize(p) for t in tokens))
                    if not CrossSourceVerification.quotation(fresh,p):raise ValueError('quote mismatch')
                    sources.append(fresh);quotes.append({'source_id':sid,'reference':fresh['reference'],'quote':p})
                if quotes:
                    answer='\n'.join('לפי '+e['reference']+':\n״'+e['quote']+'״' for e in quotes)
                    return self.result(answer,sources,route,budget,quotes=quotes)
            except (ValueError,TypeError,LLMUnavailable) as exc:self.errors.append({'stage':'knowledge-generation','error':type(exc).__name__})
        return self.result('לא נמצא מקור ישיר שמוכיח את הפרט המבוקש. נעשה חיפוש ממוקד נוסף; אין להשלים את העובדה מזיכרון המודל.',[],route,budget)

FastJewishQA=TorahFactAnswerEngine

class JewishResearchOrchestrator:
    def __init__(self,agent):self.agent=agent
    def answer(self,question,route,request_budget=None,study_mode='normal',conversation_history=None,**kwargs):
        budget=request_budget or RequestBudget(seconds=90 if study_mode=='deep' else 45,max_context_bytes=96000 if study_mode=='deep' else 48000)
        try:
            return TorahFactAnswerEngine(self.agent).answer(question,route,budget,conversation_history)
        except BudgetExceeded:
            return {'answer':'החיפוש הגיע למגבלת הזמן. לא מוצגת עובדה שלא אומתה.','sources':[],
                'verdict':'budget_exhausted','mode':'knowledge-sources-only','question_intent':route,
                'search_status':{'partial':True,'errors':[{'stage':'knowledge','error':'deadline-exhausted'}]},
                'halachic_verified':False,'human_review':'required'}
