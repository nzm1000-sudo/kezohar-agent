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
from .torah_web import ResearchError

class FactSourceStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
            db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS source_search USING fts5(id UNINDEXED,text)')
            db.execute('CREATE TABLE IF NOT EXISTS source_search_meta(revision INTEGER)')
            revision=db.execute('SELECT revision FROM source_search_meta').fetchone()
            if revision!=(2,):
                db.execute('DELETE FROM source_search')  # Search index only; source payloads stay intact.
                db.execute('DELETE FROM source_search_meta');db.execute('INSERT INTO source_search_meta VALUES(2)')
            for sid,payload in db.execute('SELECT id,payload FROM sources WHERE id NOT IN (SELECT id FROM source_search)').fetchall():
                s=json.loads(payload)
                if self.public(s):db.execute('INSERT INTO source_search VALUES(?,?)',(sid,self.index_text(s)))
    def connect(self):return sqlite3.connect(str(self.path),timeout=2)
    @staticmethod
    def public(s):
        if not admissible(s):return False
        meta=s.get('metadata',{})
        return not (meta.get('private') is True or meta.get('visibility')=='private' or meta.get('owner_id') or meta.get('user_id'))
    @staticmethod
    def index_text(s):return hebrew.normalize(' '.join(s.get(k,'') for k in ('work_title','reference','text')))
    def remember(self,s):
        if not self.public(s):return
        with self.connect() as db:
            old=db.execute('SELECT payload FROM sources WHERE id=?',(s['source_id'],)).fetchone()
            if old:
                previous=json.loads(old[0]);candidate=dict(s,ingested_at=previous.get('ingested_at',''))
                if fingerprint(candidate)==fingerprint(previous):s=previous
            if old or db.execute('SELECT count(*) FROM sources').fetchone()[0]<1000:
                db.execute('INSERT OR REPLACE INTO sources VALUES(?,?)',(s['source_id'],json.dumps(s,ensure_ascii=False)))
                db.execute('DELETE FROM source_search WHERE id=?',(s['source_id'],))
                db.execute('INSERT INTO source_search VALUES(?,?)',(s['source_id'],self.index_text(s)))
        return s
    def get(self,sid):
        with self.connect() as db:r=db.execute('SELECT payload FROM sources WHERE id=?',(sid,)).fetchone()
        s=json.loads(r[0]) if r else None
        return s if s and self.public(s) else None
    def search(self,query,limit=4,min_text_chars=0):
        tokens=list(dict.fromkeys(hebrew.tokens(query)))[:12]
        if not tokens:return []
        match=' AND '.join('"'+t.replace('"','""')+'"' for t in tokens)
        with self.connect() as db:
            rows=db.execute("SELECT s.payload FROM source_search JOIN sources s ON s.id=source_search.id WHERE source_search MATCH ? ORDER BY CASE WHEN json_extract(s.payload,'$.work_title') LIKE ? AND coalesce(json_extract(s.payload,'$.metadata.knowledge_primary_kind'),'')!='secondary-encyclopedia' THEN 0 ELSE 1 END,bm25(source_search) LIMIT ?",
                (match,query.strip()+'%',24)).fetchall()
        return [s for (payload,) in rows for s in [json.loads(payload)] if self.public(s) and len(s['text'])>=min_text_chars][:max(1,min(6,limit))]
    def count(self):
        with self.connect() as db:return db.execute('SELECT count(*) FROM source_search').fetchone()[0]

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
    BOOK_ALIASES={'כוזרי':'Kuzari','משנה תורה':'Mishneh Torah, Human Dispositions','הבהיר':'Sefer HaBahir'}
    def __init__(self,agent,root=None):
        self.agent=agent
        root=Path(root or os.environ.get('JEWISH_KNOWLEDGE_ROOT') or Path(__file__).resolve().parents[2]/'data/store/jewish-knowledge')
        project=Path(__file__).resolve().parents[2]
        if root.resolve()!=project and project not in root.resolve().parents:raise ValueError('knowledge storage must remain inside agent project')
        self.store=FactSourceStore(root/'source-units.sqlite3');self.graph=TorahEntityGraph(root/'entities.sqlite3')
        self.current={};self.fresh=set();self.conflicted=set();self.web=None;self.encyclopedia=None;self.used_web=False;self.errors=[]
    @staticmethod
    def _read_all(items,read):
        """[(item, document or the exception)] in the items' order; the reads run at the same time (owner, 2026-10-16:
        these lookups ran one after another)."""
        from concurrent.futures import ThreadPoolExecutor
        items=list(items)
        def safe(item):
            try:return read(item)
            except Exception as exc:return exc
        with ThreadPoolExecutor(4) as pool:return list(zip(items,pool.map(safe,items)))

    def _remember_all(self,items,read):
        for _,doc in self._read_all(items,read):
            if isinstance(doc,Exception):raise doc
            self.remember(doc)

    def remember(self,s):
        if s is None or not admissible(s):return
        meta=s.get('metadata',{})
        if meta.get('private') is True or meta.get('visibility')=='private' or meta.get('owner_id') or meta.get('user_id'):
            self.errors.append({'stage':'knowledge-privacy','error':'private-source-not-eligible-for-shared-graph'});return
        sid=s['source_id']
        if sid in self.conflicted:return
        if sid in self.current and fingerprint(self.current[sid])!=fingerprint(s):
            self.conflicted.add(sid);self.current.pop(sid,None);self.errors.append({'stage':'knowledge-identity','error':'conflicting-source-id','source_id':sid});return
        local=self.agent.knowledge.source_by_id(s['source_id'])
        if not local:s=self.store.remember(s) or s
        self.current[s['source_id']]=s;self.fresh.add(s['source_id']);self.graph.ingest(s)
    def resolve(self,sid,budget,force=False):
        budget.check('knowledge identity revalidation')
        if sid in self.conflicted:return None
        local=self.agent.knowledge.source_by_id(sid,request_budget=budget)
        if local:return local if admissible(local) else None
        if not force and sid in self.fresh:return self.current[sid] if admissible(self.current[sid]) else None
        old=self.current.get(sid) or self.store.get(sid)
        if not old:return None
        try:
            self.used_web=True
            kind=old.get('metadata',{}).get('knowledge_primary_kind')
            # Freshness reads share the request budget, but are not constrained
            # by the discovery transport's deliberately smaller stage cap.
            web=JewishKnowledgeWebSearch() if force else self.web
            encyclopedia=JewishEncyclopediaEngine(web.transport) if force else self.encyclopedia
            if kind=='bibliographic-metadata':
                fresh=web.index(old['metadata']['api_index_title'],budget)
                if fresh:fresh['metadata']['api_index_title']=old['metadata']['api_index_title']
            elif kind=='secondary-encyclopedia':fresh=encyclopedia.read(old['metadata']['encyclopedia_title'],budget)
            else:fresh=web.read(old['source_url'],budget)
            if fresh is None or fresh['source_id']!=sid:return None
            fresh=self.store.remember(fresh) or fresh;self.current[sid]=fresh;self.fresh.add(sid)
            self.graph.ingest(fresh)  # Fresh extraction; historical edges remain invalid.
            return fresh
        except (OSError,ValueError,LLMUnavailable) as exc:
            self.errors.append({'stage':'knowledge-source-refresh','error':type(exc).__name__});return None
        except Exception as exc:
            from .torah_web import ResearchError
            self.errors.append({'stage':'knowledge-source-refresh','error':type(exc).__name__,
                'reason':str(exc)[:150] if isinstance(exc,ResearchError) else 'refresh failed'});return None
    def facts(self,route,budget):
        if not route['relation'] or not route['entity']:return []
        return self.graph.find(route['entity'],route['relation'],lambda sid:self.resolve(sid,budget))
    def result(self,answer,sources,route,budget,kind='knowledge-reading',facts=None,quotes=None):
        facts=facts or [];quotes=quotes or []
        primary_fact=bool(facts) and all(e['support']=='bounded-primary-relation' for e in facts)
        errors=self.errors+(self.web.errors if self.web else [])
        search_errors=[e for e in errors if e.get('stage')!='knowledge-generation']
        return {'answer':answer,'sources':sources,'verdict':'fact_supported' if primary_fact else 'reported_fact' if facts else 'knowledge_reading' if quotes else 'knowledge_insufficient',
            'mode':kind,'question_intent':route,'clarifications':[],
            'verification':{'verdict':'ok' if facts or quotes else 'insufficient_context',
                'support':'bounded-primary-relationship' if primary_fact else 'reported-secondary-relationship' if facts else 'literal-reading-only' if quotes else 'no-direct-support',
                'facts':facts,'evidence':quotes,'general_entailment_verified':False},
            'verification_layers':{'quotation_integrity':'exact' if facts or quotes else 'not-proved',
                'claim_support':'typed-primary-fact' if primary_fact else 'reported-secondary-relationship' if facts else 'quoted-reading-only' if quotes else 'not-proved',
                'human_review':'not-performed','halachic_verified':False},
            'structured_answer':{'short_answer':answer,'sources':sources,'quotations':[
                {'source_id':s['source_id'],'text':s['text'],'reference':s['reference']} for s in sources] if facts else [
                {'source_id':e['source_id'],'text':e['quote'],'reference':e['reference']} for e in quotes]},
            'answer_status':{'message':'מידע תורני מבוסס מקור; אינו פסיקה הלכתית.'},
            'fact_verified':primary_fact,'answer_complete':primary_fact,
            'human_review':'not-performed','halachic_verified':False,
            'internet_used':self.used_web,'search_status':{'partial':bool(search_errors),'errors':search_errors},
            'knowledge_discovery':{'sources':list(self.current.values())[:50],
                'attempts':self.web.attempts if self.web else [],'method':'bounded relationship and subject routes'},
            'knowledge_research_dossier':{'scope':route['complexity'],
                'primary':[{'source_id':s['source_id'],'reference':s['reference']} for s in self.current.values()
                    if s.get('metadata',{}).get('knowledge_primary_kind') in ('biblical-text','bibliographic-metadata')],
                'interpretations':[{'source_id':s['source_id'],'reference':s['reference']} for s in self.current.values()
                    if s.get('metadata',{}).get('knowledge_primary_kind')=='text'],
                'secondary':[{'source_id':s['source_id'],'reference':s['reference']} for s in self.current.values()
                    if s.get('metadata',{}).get('knowledge_primary_kind')=='secondary-encyclopedia'],
                'comparison_status':'not-adjudicated; different wording is not disagreement',
                'answer_sources':[s['source_id'] for s in sources]},
            'orchestration':{'stages':['question-intent-router','knowledge-retrieval','independent-fact-verification'],
                'budget':budget.report(),'complexity':route['complexity']}}
    @staticmethod
    def unqualified_single_identity(route):
        request=route.get('identity_request') or {}
        subjects=request.get('subjects',[])
        return request.get('identity_kind')=='people' and len(subjects)==1 and not subjects[0]['father_qualifier']
    def render_facts(self,edges,route,budget):
        if route['relation']=='children':return None
        if not edges:return None
        # Conflicting explicit objects cannot be resolved by model confidence.
        if len({e['object'] for e in edges})!=1:
            return self.result('נמצאו קשרים שונים במקורות; יש לברר את זהות האדם וההקשר לפני תשובה יחידה.',[],route,budget)
        edge=edges[0];source=self.resolve(edge['source_id'],budget)
        if not source or not CrossSourceVerification.fact(edge,source):return None
        subject,obj=edge['subject'],edge['object']
        labels={'father':'אביו של {} היה {}.','mother':'אמו של {} הייתה {}.',
                'wife':'אשתו של {} הייתה {}.','child-count':'ל{} היו {} בנים.',
                'author':'לפי רשומת ספריא, מחבר ״{}״ הוא {}.'}
        answer=labels.get(edge['relation'],'{} — {}.').format(subject,obj).rstrip('.')+' ('+source['reference']+').'
        if edge['relation']=='teacher':
            answer='לפי המקור, '+subject+' היה מתלמידי '+obj+'. ('+source['reference']+'). המקור אינו מוכיח שהיה לו רב אחד בלבד.'
        elif edge['support']=='reported-secondary-relationship':answer='לפי '+source['reference']+': '+answer
        result=self.result(answer,[source],route,budget,'direct-torah-fact',[edge])
        result['knowledge_context']={'focus_entity':obj,'previous_subject':subject,'previous_relation':edge['relation'],
            'source_id':edge['source_id'],'source_snapshot':edge['source_snapshot']}
        return result
    def render_excerpt(self,question,route,budget,candidates=None):
        from .knowledge_catalog import catalog_matches
        from .knowledge_evidence import issue
        if not re.search(r'(?:תן|הבא|הצג) קטע',question) or not catalog_matches(route['normalized_question']):return None
        for candidate in (list(self.current.values()) if candidates is None else candidates):
            if issue(question,route,candidate):continue
            passages=[p.strip() for p in candidate['text'].split('\n') if 120<=len(p.strip())<=700
                      and not issue(question,route,dict(candidate,text=p.strip()))]
            if not passages:continue
            fresh=self.resolve(candidate['source_id'],budget,force=True)
            if not fresh or fingerprint(fresh)!=fingerprint(candidate):continue
            text=passages[0]
            if not CrossSourceVerification.quotation(fresh,text):continue
            narrative='traditional-narrative' in route['domains']
            answer=('קטע מספרות הסיפורים והמסורת; אין כאן אימות היסטורי של האירוע:\n' if narrative else '')+'״'+text+'״ ('+fresh['reference']+').'
            result=self.result(answer,[fresh],route,budget,kind='verified-book-reading',quotes=[{'source_id':fresh['source_id'],'reference':fresh['reference'],'quote':text}])
            if narrative:result['verification_layers']['historical_event_verified']=False
            return result
        return None
    def local_search(self,route,budget):
        from .ranking import RetrievalQuery
        queries=knowledge_queries(route['normalized_question'],route)
        from .knowledge_catalog import catalog_matches
        named=[book['heTitle'] for book in catalog_matches(route['normalized_question'])]
        # Rich/private wording stays local. A narrow public vocabulary must
        # never erase the user's actual subject from local retrieval.
        queries=list(dict.fromkeys([route['normalized_question']]+named+queries))
        definition=route.get('definition_request')
        if definition:queries=list(dict.fromkeys(list(definition['queries'])+[definition['target']]))
        for query in queries[:2]:
            budget.check('knowledge local retrieval')
            # A separate action/relationship group prevents a frequent name
            # alone winning over a passage explicitly stating the relationship.
            rq=RetrievalQuery(query,[])
            if definition:rq.concept_groups=[frozenset(hebrew.normalize(t) for t in definition['aliases'])]
            relation_terms={'father':['ותלד','בני','בן'],'mother':['ותהר','אם','ותלד'],
                'wife':['אשת','אשה'],'child-count':['בני'],'teacher':['תלמיד','למד']}
            rq.concept_groups=[frozenset(hebrew.normalize(route['entity']).split())] if route['entity'] else []
            if route['relation'] in relation_terms:rq.concept_groups.append(frozenset(hebrew.normalize(w) for w in relation_terms[route['relation']]))
            found=self.agent.knowledge.search.search(rq,top_k=100 if definition else 30,request_budget=budget)
            self.errors.extend(getattr(found,'errors',[]))
            for s in found:
                if admissible(s) and len(s['text'].encode())<=32000:self.remember(s)
            if self.facts(route,budget):break
            # Cached text is discovery only. Re-read public source and current
            # permissions before it can become context or graph evidence.
            if route.get('export_allowed') is not False:
                minimum=80 if re.search(r'קטע|סיפור',route['normalized_question']) and named else 0
                for cached in self.store.search(query,min_text_chars=minimum):
                    budget.check('learned source refresh')
                    fresh=self.resolve(cached['source_id'],budget)
                    if fresh:self.remember(fresh)
            if self.facts(route,budget):break
    def answer(self,question,route,budget,history=None):
        answer_started=time.perf_counter()
        self.web=JewishKnowledgeWebSearch();self.encyclopedia=JewishEncyclopediaEngine(self.web.transport)
        # Follow-up focus is derived anew from verified previous evidence. Raw
        # conversation statements are never accepted as source-backed facts.
        if not route['entity'] and history and route['relation']:
            previous=QuestionIntentRouter().route(history[-1]);previous_edges=self.facts(previous,budget)
            if len({e['object'] for e in previous_edges})==1:
                route=dict(route,entity=previous_edges[0]['object'],domains=previous['domains'])
                route['normalized_question']='מי הייתה אשתו של '+route['entity']+'?' if route['relation']=='wife' else question
        if route['relation'] and route['relation']!='author' and route['entity'] is None:
            return self.result('לא ברור לאיזה אדם מתייחסת השאלה. על מי שאלת?',[],route,budget)
        answer=self.render_facts(self.facts(route,budget),route,budget)
        if answer:return answer
        self.local_search(route,budget)
        from .knowledge_evidence import issue as evidence_issue
        from .knowledge_units import explanatory_units
        def has_definition():
            return bool(route.get('definition_request') and any(
                not re.search(r'מותר|אסור|חייב|רשאי|להתיר|להחמיר|להקל|אוסר',hebrew.normalize(u['text']))
                and not evidence_issue(question,route,dict(s,text=u['text']))
                for s in self.current.values() for u in explanatory_units(s,question)))
        local_definition_ready=has_definition()
        if (route.get('definition_request') or {}).get('id') and not local_definition_ready and route.get('export_allowed') is not False:
            self.used_web=True
            try:
                self._remember_all(self.encyclopedia.search(route,budget),lambda title:self.encyclopedia.read(title,budget))
                local_definition_ready=has_definition()
            except (OSError,ValueError,ResearchError) as exc:self.errors.append({'stage':'definition-discovery','error':type(exc).__name__})
        from .identity_answers import resolve_identity
        identity=resolve_identity(self,route,budget)
        if identity and not self.unqualified_single_identity(route):return identity
        answer=self.render_facts(self.facts(route,budget),route,budget)
        if answer:return answer
        excerpt=self.render_excerpt(question,route,budget)
        if excerpt:return excerpt
        # Only public registered subjects may be sent outside. A user-written
        # private/unresolved name is never exported by query generation.
        books=self.BOOK_ALIASES
        if route['relation']=='author' and route.get('export_allowed') is not False:
            title=next((v for k,v in books.items() if k in route['normalized_question']),None)
            from .knowledge_catalog import catalog_matches
            matches=catalog_matches(route['normalized_question']) if route.get('export_allowed') is not False else []
            if len(matches)==1:title=matches[0]['title']
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
        # Owner decision 2026-10-15: the encyclopedia comes first for every knowledge question ("מי היה", relations,
        # concepts); phrase search in primary texts finds every passage that merely contains the words.
        encyclopedia_tried=False
        if route.get('export_allowed') is not False and not (local_definition_ready and route['complexity']!='deep'):
            encyclopedia_tried=True;self.used_web=True
            try:
                self._remember_all(self.encyclopedia.search(route,budget),lambda title:self.encyclopedia.read(title,budget))
                identity=resolve_identity(self,route,budget)
                if identity and not self.unqualified_single_identity(route):return identity
                answer=self.render_facts(self.facts(route,budget),route,budget)
                if answer:return answer
            except Exception as exc:self.errors.append({'stage':'encyclopedia-first','error':type(exc).__name__})
        if knowledge_queries(question,route) and not (local_definition_ready and route['complexity']!='deep' and not route.get('explicit_web_requested')):
            self.used_web=True
            # The pages are read at the same time; they are then taken in order, with the same early answer check.
            for url,doc in self._read_all(self.web.search(question,route,budget,limit=6),lambda url:self.web.read(url,budget)):
                if isinstance(doc,Exception):self.errors.append({'stage':'knowledge-web-read','error':type(doc).__name__})
                else:self.remember(doc)
                identity=resolve_identity(self,route,budget)
                if identity and not self.unqualified_single_identity(route):return identity
                answer=self.render_facts(self.facts(route,budget),route,budget)
                if answer:return answer
            if not encyclopedia_tried:
                try:
                    self._remember_all(self.encyclopedia.search(route,budget),lambda title:self.encyclopedia.read(title,budget))
                    answer=self.render_facts(self.facts(route,budget),route,budget)
                    if answer:return answer
                except Exception as exc:self.errors.append({'stage':'encyclopedia','error':type(exc).__name__})
        identity=resolve_identity(self,route,budget)
        if identity:return identity
        # Source reading is useful for explanation/history, but does not create
        # an unchecked direct relationship fact or a personal halachic ruling.
        if route['relation']=='author':
            from .knowledge_catalog import catalog_matches
            titles={hebrew.normalize(r[k]) for r in catalog_matches(route['normalized_question'])
                    for k in ('heTitle','search_spelling_hint') if r.get(k)}
            for candidate in self.current.values():
                if candidate.get('metadata',{}).get('knowledge_primary_kind')!='secondary-encyclopedia':continue
                if hebrew.normalize(candidate['work_title']) not in titles:continue
                paragraphs=[p.strip() for p in candidate['text'].split('\n') if 20<=len(p.strip())<=750
                            and re.search(r'ספרו של|מאת|שחיבר|מחבר|נכתב על ידי',p)]
                if not paragraphs:continue
                fresh=self.resolve(candidate['source_id'],budget,force=True)
                if not fresh or fingerprint(fresh)!=fingerprint(candidate):continue
                quote=paragraphs[0]
                if not CrossSourceVerification.quotation(fresh,quote):continue
                return self.result('הייחוס מופיע במקור אנציקלופדי משני:\n״'+quote+'״ ('+fresh['reference']+').',
                    [fresh],route,budget,quotes=[{'source_id':fresh['source_id'],'reference':fresh['reference'],'quote':quote}])
        from .knowledge_evidence import issue,expected_kind
        from .knowledge_catalog import catalog_matches
        candidates=[s for s in self.current.values() if not issue(question,route,s)];keywords=knowledge_queries(question,route)
        tokens=hebrew.tokens(' '.join(keywords))
        from .knowledge_evidence import select_candidates
        candidates=select_candidates(question,route,candidates)
        excerpt=self.render_excerpt(question,route,budget,candidates)
        if excerpt:return excerpt
        if candidates and not route['relation']:
            model=BudgetedAnswerModel(_KnowledgeModel(self.agent.answer_model),budget)
            retrieval_s=time.perf_counter()-answer_started
            generation_started=time.perf_counter();generated=None
            try:
                generated=model.generate(question,candidates,timeout=min(30,budget.remaining()))
                generation_s=time.perf_counter()-generation_started;verification_started=time.perf_counter()
                packet=json.loads(generated['answer'])
                if route.get('definition_request') and isinstance(packet,dict) and set(packet)=={'meaning','example'}:
                    if len(candidates)!=1:raise ValueError('ambiguous-definition-evidence-binding')
                    from .knowledge_units import explanatory_units
                    source=candidates[0]
                    offered=explanatory_units(source,question)
                    if not offered:raise ValueError('missing-definition-evidence')
                    if any(not isinstance(packet[k],str) for k in packet):raise ValueError('invalid-definition-text')
                    packet={'claims':[{'claim_id':'C'+str(i+1),'kind':'paraphrase','statement':packet[k],
                        'evidence':[{'source_id':source['source_id'],'unit_id':u['unit_id']} for u in offered]}
                        for i,k in enumerate(('meaning','example'))]}
                if packet=={'status':'no_source'}:
                    # A basic definition may still be useful, while explicitly
                    # NOT answering every part (e.g. a requested complete list).
                    if expected_kind(question,route)=='definition':
                        for candidate in candidates:
                            if candidate.get('metadata',{}).get('knowledge_primary_kind')!='secondary-encyclopedia':continue
                            paragraphs=[p.strip() for p in candidate['text'].split('\n') if 20<=len(p.strip())<=750
                                and not issue(question,route,dict(candidate,text=p.strip()))]
                            if not paragraphs:continue
                            fresh=self.resolve(candidate['source_id'],budget,force=True)
                            if not fresh or fingerprint(fresh)!=fingerprint(candidate):continue
                            text=paragraphs[0]
                            if not CrossSourceVerification.quotation(fresh,text):continue
                            result=self.result('מקורות לעיון — לא נוצר הסבר לשאלה. קטע הגדרה חלקי:\n״'+text+'״ ('+fresh['reference']+').',
                                [fresh],route,budget,kind='partial-knowledge-reading',quotes=[{'source_id':fresh['source_id'],'quote':text,'reference':fresh['reference']}])
                            result.update(verdict='partial_knowledge',answer_complete=False)
                            result['generation_status']={'started':True,'completed':True,'used_for_answer':False,
                                'finish_reason':generated.get('finish_reason'),'usage':generated.get('usage') or None}
                            return result
                    return self.result('המקורות שנמצאו אינם מספיקים לתשובה המבוקשת. לא נוצרה מסקנה מזיכרון המודל.',[],route,budget)
                if isinstance(packet,dict) and 'claims' in packet:
                    from .knowledge_claims import validate,answer_packet
                    packet,removed=answer_packet(packet,allow_inference=route['complexity']=='deep')
                    if route.get('definition_request') and sum(len(c['statement']) for c in packet['claims'])>900:
                        raise ValueError('definition-explanation-too-long')
                    claims,sources=validate(packet,candidates,lambda sid:self.resolve(sid,budget,force=True),question,route)
                    quotes=[e for c in claims for e in c['evidence']]
                    lines=[]
                    for c in claims:
                        prefix='' if route.get('definition_request') else 'הצעת פרשנות: ' if c['kind']=='interpretation' else 'הסקה מוצעת: ' if c['kind']=='inference' else 'הסבר מוצע לפי המקור: ' if c['kind']=='paraphrase' else ''
                        refs=list(dict.fromkeys(e['reference'] for e in c['evidence']))
                        lines.append(c['statement'] if route.get('definition_request') else prefix+c['statement']+' ('+'; '.join(refs)+').')
                    if route.get('definition_request'):
                        lines.append('מקור: '+'; '.join(dict.fromkeys(e['reference'] for c in claims for e in c['evidence'])))
                    result=self.result('\n'.join(lines),sources,route,budget,kind='source-linked-explanation',quotes=quotes)
                    # What the app shows (owner, 2026-10-16): the statements alone — no "הסבר מוצע לפי המקור:" label and
                    # no references in parentheses; the quotation and its reference go in the source box below.
                    first=next((e for c in claims for e in c['evidence'] if e.get('quote')),None)
                    result['bari']={'answer':' '.join(c['statement'].strip() for c in claims),
                                    'quote':first['quote'] if first else None,
                                    'cite':'; '.join(dict.fromkeys(e['reference'] for c in claims for e in c['evidence'])) or None,
                                    'source':'library'}
                    result.update(verdict='knowledge_explanation',answer_complete=False,claims=claims,
                        claim_generation={'model':generated.get('model'),'finish_reason':generated.get('finish_reason')})
                    result['claim_status']={'removed':removed,'partial':bool(removed),
                        'meaning_verified':False,'kind_classification':'model-labelled; not semantic proof'}
                    result['verification']['support']='exact-evidence; proposed-meaning-not-certified'
                    result['verification_layers']['claim_support']='source-linked-proposal'
                    result['verification_layers']['semantic_entailment_verified']=False
                    result['generation_status']={'started':True,'completed':True,'used_for_answer':True,
                        'task':'definition-explanation' if route.get('definition_request') else 'knowledge-explanation',
                        'model_returned':generated.get('model'),'finish_reason':generated.get('finish_reason'),
                        'usage':generated.get('usage') or None}
                    result['timings']={'retrieval_s':round(retrieval_s,3),'generation_s':round(generation_s,3),
                        'verification_s':round(time.perf_counter()-verification_started,3)}
                    return result
                if route.get('definition_request'):raise ValueError('definition-requires-explanation-not-source-selection')
                ids=packet.get('selected_sources') if isinstance(packet,dict) and set(packet)=={'selected_sources'} else None
                if not isinstance(ids,list) or not 1<=len(ids)<=2 or len(set(ids))!=len(ids):raise ValueError('invalid knowledge source selection')
                quotes=[];sources=[]
                for sid in ids:
                    sent=next((s for s in candidates if s['source_id']==sid),None);fresh=self.resolve(sid,budget,force=True)
                    if not sent or not fresh or fingerprint(sent)!=fingerprint(fresh):raise ValueError('knowledge source changed')
                    max_chars=1500 if route['complexity']=='deep' else 750
                    paragraphs=[p.strip() for p in sent['text'].split('\n') if p.strip() and len(p.strip())<=max_chars
                        and not issue(question,route,dict(sent,text=p.strip()))]
                    if not paragraphs:continue
                    p=max(paragraphs,key=lambda p:sum(t in hebrew.normalize(p) for t in tokens))
                    if not CrossSourceVerification.quotation(fresh,p):raise ValueError('quote mismatch')
                    sources.append(fresh);quotes.append({'source_id':sid,'reference':fresh['reference'],'quote':p})
                if quotes:
                    if route['complexity']=='deep':
                        chosen={s['source_id'] for s in sources}
                        for extra in self.current.values():
                            if len(quotes)>=3:break
                            if extra['source_id'] in chosen or extra.get('metadata',{}).get('knowledge_primary_kind') in ('biblical-text','bibliographic-metadata'):continue
                            if issue(question,route,extra):continue
                            passages=[p.strip() for p in extra['text'].split('\n') if 30<=len(p.strip())<=1500
                                and sum(t in hebrew.normalize(p) for t in tokens)>=min(2,len(tokens))]
                            names=route.get('public_entities',[])
                            if names:passages=[p for p in passages if all(hebrew.normalize(name) in hebrew.normalize(p) for name in names)]
                            if not passages:continue
                            if 'לא נכנס' in route['normalized_question']:
                                passages=[p for p in passages if re.search(r'(?<![א-ת])(?:לא נכנס|לא בא|לא יבוא|לא תביאו)(?![א-ת])',hebrew.normalize(p))]
                            if not passages:continue
                            fresh=self.resolve(extra['source_id'],budget,force=True)
                            if not fresh or fingerprint(fresh)!=fingerprint(extra) or not CrossSourceVerification.quotation(fresh,passages[0]):continue
                            sources.append(fresh);quotes.append({'source_id':fresh['source_id'],'reference':fresh['reference'],
                                'quote':passages[0],'reading_kind':'interpretation; not a new historical fact'})
                            chosen.add(fresh['source_id'])
                    answer='\n'.join('״'+e['quote']+'״ ('+e['reference']+').' for e in quotes)
                    narrative=any(s.get('metadata',{}).get('knowledge_genre')=='traditional-narrative' for s in sources)
                    if narrative:answer='קטע מספרות הסיפורים והמסורת; אין כאן אימות היסטורי של האירוע:\n'+answer
                    result=self.result(answer,sources,route,budget,quotes=quotes)
                    if narrative:result['verification_layers']['historical_event_verified']=False
                    return result
            except BudgetExceeded:raise
            except (ValueError,TypeError,LLMUnavailable) as exc:self.errors.append({'stage':'knowledge-generation','error':type(exc).__name__,
                'category':'model-unavailable' if isinstance(exc,LLMUnavailable) else 'invalid-model-format' if isinstance(exc,json.JSONDecodeError) else 'technical-generation-error' if isinstance(exc,TypeError) else 'unsupported-model-claim',
                'reason':str(exc)[:160] if isinstance(exc,ValueError) else 'local-model-unavailable'})
        generation_errors=[e for e in self.errors if e.get('stage')=='knowledge-generation']
        if generation_errors:
            category=generation_errors[-1]['category']
            message={'model-unavailable':'נמצאו מקורות, אך המודל המקומי אינו זמין ולכן לא נוצר הסבר.',
                'invalid-model-format':'נמצאו מקורות, אך המודל החזיר פלט במבנה פגום. לא הוצג הסבר.',
                'technical-generation-error':'נמצאו מקורות, אך אירעה תקלה טכנית בהפקת ההסבר.'}.get(category,
                'נמצאו מקורות, אך ההסבר שהמודל ניסח נפסל בבדיקת התמיכה. הוא לא הוחלף בציטוט ולא הוצג כתשובה מאומתת.')
            result=self.result(message,[],route,budget)
            result['failure_details']={'category':generation_errors[-1]['category'],'errors':generation_errors}
            result['generation_status']={'started':True,'completed':generated is not None,'used_for_answer':False,
                'finish_reason':generated.get('finish_reason') if generated else None,'usage':generated.get('usage') if generated else None}
            return result
        return self.result('לא נמצא מקור ישיר שמוכיח את הפרט המבוקש. נעשה חיפוש ממוקד נוסף; אין להשלים את העובדה מזיכרון המודל.',[],route,budget)

FastJewishQA=TorahFactAnswerEngine

class JewishResearchOrchestrator:
    def __init__(self,agent):self.agent=agent
    def answer(self,question,route,request_budget=None,study_mode='normal',conversation_history=None,**kwargs):
        budget=request_budget or RequestBudget(seconds=90 if study_mode=='deep' else 45,max_context_bytes=96000 if study_mode=='deep' else 48000)
        if study_mode=='deep':route=dict(route,complexity='deep')
        try:
            return TorahFactAnswerEngine(self.agent).answer(question,route,budget,conversation_history)
        except BudgetExceeded:
            return {'answer':'החיפוש הגיע למגבלת הזמן. לא מוצגת עובדה שלא אומתה.','sources':[],
                'verdict':'budget_exhausted','mode':'knowledge-sources-only','question_intent':route,
                'search_status':{'partial':True,'errors':[{'stage':'knowledge','error':'deadline-exhausted'}]},
                'halachic_verified':False,'human_review':'not-performed'}
