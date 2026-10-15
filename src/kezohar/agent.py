"""Agent orchestration: fastpath -> retrieval (code) -> one LLM call -> safety check."""
import time
from . import fastpath, llm as llm_client
from .knowledge import KnowledgeBase
from .answer_models import ConfiguredAnswerModel
from .verification import ExtractiveSourceVerifier
from .ranking import topic_tokens, retrieval_query, topic_overlap, concept_coverage
from .permissions import rag_eligible
from . import evidence
from .source_quality import classify, exclusion_reason
from .halachic_authority import profile as authority_profile, selection_key
from .question_understanding import analyze, case_coverage
from .source_snapshot import fingerprint,structurally_valid
from .hybrid import SearchResults
from .semantic_claims import catalog_revision


def diverse_sources(ordered, limit):
    """Keep relevant authority order while avoiding one work filling the prompt.

    This changes selection only, never text/locator or evidence approval.
    Distinct excerpts/editions stay separate records, including on the second pass.
    """
    if limit<1:return []
    tables=[s for s in ordered if s.get('explicit_food_table') and rag_eligible(s)]
    if tables:
        # A syntactically general first-blessing query has an exact food row.
        # Do not crowd its prompt with laws about toppings, mixtures or order.
        return tables[:limit]
    # Diversity must not promote a tangential work over a complete case match.
    sims=[s['relevance_score'] for s in ordered if isinstance(s.get('relevance_score'),float)]
    best=max(sims) if sims else None
    # A unit in the top meaning band is a direct match even when its wording
    # differs from the question (לשוחח vs להפסיק בדיבור).
    complete=[s for s in ordered if s.get('concept_coverage',{}).get('complete')
              or (best is not None and s.get('relevance_score',-1)>=best-RERANK_TIER)]
    if complete and len(complete)<len(ordered):
        # Do not fill unused prompt slots with partial-topic matches when a
        # directly matching unit exists. A smaller context is preferable here;
        # the verifier's support and source guards are completely unchanged.
        return diverse_sources(complete,limit)
    chosen=[];works=set();ids=set()
    for source in ordered:
        work=(source.get('work_title'),source.get('author'),source.get('tradition'))
        if work in works or source['source_id'] in ids:continue
        chosen.append(source);works.add(work);ids.add(source['source_id'])
        if len(chosen)>=limit:return chosen
    for source in ordered:
        if source['source_id'] not in ids:
            chosen.append(source);ids.add(source['source_id'])
            if len(chosen)>=limit:break
    return chosen

def order_sources(sources, question=""):
    """Maran/Sephardi first, then others — stable within groups."""
    sources = [s for s in sources if structurally_valid(s) and not exclusion_reason(question, s)]
    if question:
        from .locator_search import parse,matches
        locator=parse(question)
        terms = topic_tokens(question)
        if terms:
            sources = [s for s in sources if topic_overlap(s.get('text',''),question)>0 or (locator and matches(s,locator))]
    for source in sources:
        source.update(classify(source))
        source['topical_overlap'] = topic_overlap(source.get('text',''),question) if question else 0
        covered,total=concept_coverage(source.get('text',''),question)
        source['concept_coverage']={'matched':covered,'total':total,'complete':bool(total) and covered==total}
        source.setdefault('search_relevance', source.get('score',0))
        source.setdefault('source_reliability', source.get('metadata',{}).get('source_reliability','import-provenance-only'))
        source.setdefault('halachic_authority', source.get('authority_level','') or ('maran' if source.get('work_title','').startswith('שולחן ערוך') or source.get('book_id')=='Beit_Yosef' else 'unclassified'))
        source.setdefault('evidence_support', 'not-claim-verified')
        source['authority_profile']=authority_profile(source)
        source['halachic_authority']=source['authority_profile']['authority']
        source['retrieval_tradition']=source['authority_profile']['tradition']
        source['case_coverage']=case_coverage(question,source) if question else 0
    preferred=analyze(question)['circumstances']['tradition'] if question else 'sephardi'
    for source in sources:
        source['_selection_key']=selection_key(source,question,preferred)
    from .blessing_context import matching_first_table, food_subject
    subject=food_subject(question)
    for source in sources:
        source['explicit_food_table']=bool(matching_first_table(question,source)
            and source['authority_profile']['tradition']==preferred)
        # Query-specific opening coverage improves retrieval precision, without
        # shortening the source or establishing semantic support.
        source['opening_subject_match']=bool(subject and concept_coverage(source['text'][:160],question)[0]==concept_coverage(source['text'][:160],question)[1])
        opened,total=concept_coverage(source['text'][:320],question)
        source['opening_topic_coverage']=opened/total if total else 0
    return sorted(sources, key=lambda s: (
        not rag_eligible(s),
        not s['concept_coverage']['complete'],
        -s['concept_coverage']['matched'],
        not s['explicit_food_table'],
        not s['opening_subject_match'],
        -s['opening_topic_coverage'],
        s['_selection_key']))


RERANK_DEPTH=30
RERANK_TIER=0.05  # ponytail: fixed similarity bands; calibrate on the held-out set


def semantic_rerank(ordered, question, search, request_budget=None):
    """Order eligible candidates by meaning, keeping lexical order within a band.

    Lexical concept coverage alone promoted passages sharing every word but
    another subject (interrupting a blessing vs. talking between tefillin).
    Similarity reorders retrieval only; it never establishes claim support.
    """
    dense=next((b for b in getattr(search,'backends',[]) if hasattr(b,'index')),None)
    head=ordered[:RERANK_DEPTH]
    if dense is None or len(head)<2:return ordered
    from .local_embeddings import EmbeddingUnavailable
    from .vector import cosine
    from .vector_index import embed_text
    model=dense.index.model
    try:
        if request_budget:request_budget.check('semantic rerank')
        qv=model.embed_query(str(getattr(question,'semantic_text',None) or question))
        vectors=[]
        for i in range(0,len(head),16):
            if request_budget:request_budget.check('semantic rerank batch')
            vectors+=model.embed_many([embed_text(s.get('text') or '')[:2000] or '-' for s in head[i:i+16]])
    except EmbeddingUnavailable:
        return ordered  # lexical order stays; never fail the answer for reranking
    for source,vector in zip(head,vectors):
        source['semantic_similarity']=source['relevance_score']=round(cosine(qv,vector),4)
    # Optional cross-encoder: it reads question and passage together ("does this
    # answer it?"); summed with similarity since neither alone was reliable.
    from . import reranker
    try:
        probs=reranker.scores(str(getattr(question,'semantic_text',None) or question),
                              [embed_text(s.get('text') or '') or '-' for s in head])
    except Exception:
        probs=None
    if probs:
        for source,p in zip(head,probs):
            if p==p:source['rerank_probability']=round(p,4);source['relevance_score']=round(source['semantic_similarity']+p,4)
    position={id(s):n for n,s in enumerate(head)}
    head=sorted(head,key=lambda s:(not rag_eligible(s),not s.get('explicit_food_table'),
                                   -int(s['relevance_score']/RERANK_TIER),position[id(s)]))
    return head+ordered[RERANK_DEPTH:]


class Agent:
    def __init__(self, sources=None, store_path=None, base_url=None, model=None, research_engine=None,
                 knowledge=None, search_engine=None, answer_model=None, source_verifier=None, source_graph=None):
        self.knowledge = knowledge if knowledge is not None else KnowledgeBase(sources, store_path, search_engine)
        self.answer_model = answer_model if answer_model is not None else ConfiguredAnswerModel(base_url, model)
        self.source_verifier = source_verifier if source_verifier is not None else ExtractiveSourceVerifier()
        self.research_engine = research_engine
        self.source_graph = source_graph
        self._cache_revision = None
        self._cache = {}
        from .retrieval_cache import RetrievalCache
        self.retrieval_cache=RetrievalCache()

    @property
    def base_url(self):
        return getattr(self.answer_model.identity, 'base_url', '')

    @property
    def model(self):
        return getattr(self.answer_model.identity, 'model', '')

    @property
    def search(self):
        return self.knowledge.search

    @search.setter
    def search(self, value):
        self.knowledge.search = value

    def ask(self, question, top_k=5, lat=None, lon=None, location=None, timeout=4.5, cache_ttl=300, retrieved_sources=None, answer_model=None):
        t0 = time.time()
        q = (question or "").strip()
        from .question_senses import clarification,classify,INSUFFICIENT
        ambiguous=clarification(q)
        if ambiguous:return ambiguous
        cacheable = answer_model is None and retrieved_sources is None and lat is None and lon is None and location is None
        if not q:
            return {"answer": "נא לשאול שאלה.", "sources": [], "verdict": "empty",
                    "mode": "refuse", "elapsed_s": 0.0}
        # Permission/index changes invalidate answers derived from older records.
        revision = (getattr(self.search,"revision",None), self.answer_model.identity,catalog_revision()) if cacheable else None
        if cacheable and revision != self._cache_revision:
            self._cache.clear()
            self._cache_revision = revision
        # cache
        now = time.time()
        if q in self._cache and cacheable:
            ts, res = self._cache[q]
            if now - ts < cache_ttl:
                pinned={s['source_id']:fingerprint(s) for s in res.get('sources',[])}
                unchanged=all((current:=self.knowledge.source_by_id(sid)) is not None
                              and fingerprint(current)==digest for sid,digest in pinned.items())
                if res.get('mode')=='fast' and res.get('details',{}).get('base_date')!=fastpath.today_israel().isoformat():unchanged=False
                if unchanged:
                    r = dict(res)
                    r["cached"] = True
                    return r
                self._cache.pop(q,None)
        # out of scope -> polite refusal (no retrieval needed, but include empty sources)
        if fastpath.is_out_of_scope(q):
            res = {"answer": "מצטער, אני עונה רק על הלכה, מנהגים, ברכות, זמנים, תפילות, צומות, שבת, חגים ולוח השנה העברי.",
                   "sources": [], "verdict": "out_of_scope", "mode": "refuse",
                   "elapsed_s": round(time.time() - t0, 3)}
            if cacheable:self._cache[q] = (now, res)
            return dict(res)
        # fast path (zmanim/calendar) — no LLM
        fp = fastpath.handle(q, lat=lat or fastpath.DEFAULT_LAT, lon=lon or fastpath.DEFAULT_LON,
                             location=location or fastpath.DEFAULT_LOCATION)
        if fp is not None:
            res = {"answer": fp["answer"], "sources": [], "verdict": fp["kind"],
                   "mode": "fast", "details": fp, "elapsed_s": round(time.time() - t0, 3)}
            if cacheable:self._cache[q] = (now, res)
            return dict(res)
        # retrieval first (in code)
        retrieved = retrieved_sources if retrieved_sources is not None else self.search_only(q,top_k=top_k)
        search_status=getattr(retrieved,'status',{'partial':False,'errors':[]})
        if search_status['partial']:
            return {'answer':'החיפוש הושלם באופן חלקי; אין בסיס לתשובה מאומתת.',
                    'sources':retrieved,'search_status':search_status,'verdict':'partial_search',
                    'mode':'sources-only','human_review':'required','halachic_verified':False}
        if not retrieved:
            res = {"answer": INSUFFICIENT if classify(q)['domain']=='fertility-treatment' else evidence.INSUFFICIENT if evidence.shared_oil_waiting(q) else "אין לי מקור לכך.", "sources": [],
                   "verdict": "no_source", "mode": "sources-only",
                   "elapsed_s": round(time.time() - t0, 3)}
            if cacheable:self._cache[q] = (now, res)
            return dict(res)
        searchable = retrieved
        if classify(q)['domain']=='fertility-treatment':
            from .question_senses import relevance_issue
            retrieved=[s for s in retrieved if not relevance_issue(q,s.get('text',''))]
            if not retrieved:
                return {'answer':INSUFFICIENT,'sources':[],'verdict':'insufficient_context','mode':'sources-only',
                    'halachic_verified':False,'verification':{'verdict':'insufficient_context','checks':{'source_relevance':'failed','halachic_conclusion':'not-established'}}}
        retrieved = [s for s in retrieved if rag_eligible(s)]
        if not retrieved:
            return {'answer':'מצב חיפוש: המקורות מותרים לחיפוש; היקף השימוש בהם להפקת תשובה עדיין בבירור.',
                    'sources':searchable, 'verdict':'rag-scope-pending', 'mode':'sources-only',
                    'elapsed_s':round(time.time()-t0,3)}
        eligible = self.source_verifier.eligible_sources(q, retrieved)
        if not eligible:
            return {"answer": evidence.INSUFFICIENT if evidence.shared_oil_waiting(q) else 'אין במקורות שנמצאו ראיה מספקת למקרה שנשאל. נדרשים מקור מתאים ובדיקת ההקשר.', "sources": retrieved,
                    "verdict": "insufficient_context", "mode": "sources-only",
                    "human_review": "required", "halachic_verified": False,
                    "elapsed_s": round(time.time() - t0, 3)}
        retrieved = eligible
        from .locator_search import reference_only,parse,matches
        if reference_only(q):
            hint=parse(q);located=[]
            for old in retrieved:
                current=self.knowledge.source_by_id(old['source_id'])
                if current and fingerprint(current)==fingerprint(old) and matches(current,hint):located.append(current)
            if not located:
                return {'answer':'מראה המקום לא אומת מול המקור והרשאותיו העדכניות.',
                        'sources':[],'verdict':'invalid_citation','mode':'reference-reader','halachic_verified':False,
                        'verification':{'verdict':'invalid_citation','support':'locator snapshot no longer current'}}
            return {'answer':'אותרו '+str(len(located))+' יחידות מקור למראה המקום שביקשת. פתח את המקור לקריאה; אין כאן פסיקה.',
                    'sources':located,'verdict':'source_lookup','mode':'reference-reader','halachic_verified':False,
                    'elapsed_s':round(time.time()-t0,3),'verification':{'verdict':'not-applied','support':'metadata locator lookup, not a ruling'}}
        # one LLM call
        try:
            generator=answer_model if answer_model is not None else self.answer_model
            if not hasattr(generator,'sent_sources'):
                from .request_budget import revalidate_sources
                retrieved=revalidate_sources(retrieved,self.knowledge.source_by_id)
            from .blessing_context import reading, context_issue
            from .request_budget import revalidate_sources
            table=reading([{'source_id':s['source_id'],'quote':s['text']} for s in retrieved],retrieved)
            scope=analyze(q)
            covered,total=concept_coverage(retrieved[0]['text'],q)
            direct=(len(retrieved)==1 and len(table)==1 and not table[0]['has_conditions']
                    and scope['intent']=='food-blessing' and total>0 and covered==total
                    and context_issue(q,[{'quote':retrieved[0]['text']}]) is None)
            if direct:
                # A finite table-column reading needs no language-model choice.
                # Use the SAME full-source protocol and independent verifier.
                budget=getattr(generator,'budget',None)
                if budget:budget.check('direct source reading')
                retrieved=revalidate_sources(retrieved,self.knowledge.source_by_id,budget)
                import json
                lr={'answer':json.dumps({'selected_sources':[retrieved[0]['source_id']]})}
                mode='direct-source-reading'
            else:
                lr = generator.generate(q, retrieved, timeout=timeout)
                if hasattr(generator,'sent_sources'):
                    retrieved=generator.sent_sources
                mode = "llm"
            answer = lr["answer"]
        except llm_client.LLMUnavailable as exc:
            from .request_budget import SourceChanged
            if isinstance(exc,SourceChanged):
                return {'answer':'המקור או ההרשאה השתנו; נדרשים אחזור ואימות מחדש.',
                        'sources':[],'verdict':'invalid_citation','mode':'llm-guarded',
                        'verification':{'verdict':'invalid_citation','support':'source changed before generation'},
                        'human_review':'required','halachic_verified':False}
            # Mac offline: sources only, clearly labeled
            stopped=getattr(getattr(generator,'budget',None),'reason',None)
            res = {"answer": evidence.INSUFFICIENT if evidence.shared_oil_waiting(q) else "מצב חיפוש (המודל אינו זמין): אלו המקורות הקרובים ביותר.",
                   "sources": retrieved, "verdict": "sources-only",
                   "mode": "sources-only", "elapsed_s": round(time.time() - t0, 3),
                   "technical_error":{"code":"local_model_busy" if isinstance(exc,llm_client.LocalModelBusy) else "local_model_unavailable","type":type(exc).__name__}}
            if isinstance(exc,llm_client.LocalModelBusy):
                res['answer']='המודל מטפל בבקשה אחרת ולא היה זמן להמתין. אפשר לנסות שוב.'
            if stopped:
                res.update(answer='מצב חיפוש: הבקשה הגיעה למגבלת הזמן, הקריאות או ההקשר; אין תשובה מאומתת.',
                           verdict='budget_exhausted')
            if cacheable:self._cache[q] = (now, res)
            return dict(res)
        # safety verification
        # Rehydrate after generation: a provider call can outlive a grant or
        # source update. Never verify a stale prompt snapshot as current proof.
        from .request_budget import BudgetExceeded
        budget=getattr(generator,'budget',None)
        current=[]
        verification_started=time.perf_counter()
        try:
            for source in retrieved:
                if budget:budget.check('post-generation source lookup')
                current.append(self.knowledge.source_by_id(source['source_id'],request_budget=budget))
                if budget:budget.check('post-generation source lookup return')
        except BudgetExceeded:
            return {'answer':'הבקשה הגיעה למגבלת הזמן; אין תשובה מאומתת.',
                    'sources':[],'verdict':'budget_exhausted','mode':'sources-only',
                    'human_review':'required','halachic_verified':False}
        stale=any(s is None or fingerprint(s)!=fingerprint(old) for s,old in zip(current,retrieved))
        v = ({'verdict':'invalid_citation','support':'source changed or unavailable after generation'} if stale else
             self.source_verifier.verify(q, answer, current))
        if budget and budget.remaining()<=0:
            budget.reason='source verification exceeded request deadline'
            return {'answer':'האימות חרג ממגבלת הזמן; אין תשובה מאומתת.',
                    'sources':[],'verdict':'budget_exhausted','mode':'sources-only',
                    'human_review':'required','halachic_verified':False}
        if stale:
            retrieved=[s for s in current if s is not None and rag_eligible(s)]
        if v['verdict'] in ('ok', 'no_source'):
            answer = v.get('rendered_answer', answer)
        if v['verdict'] == 'no_source' and evidence.shared_oil_waiting(q):
            answer = evidence.INSUFFICIENT
        verdict = v["verdict"]
        if verdict not in ("ok", "no_source"):
            # do not present as certain ruling
            answer = evidence.INSUFFICIENT if evidence.shared_oil_waiting(q) else (
                'נמצאו מקורות לעיון, אך לא אומתה תשובה למקרה. '
                'הציטוט אינו מספק את ההקשר הנדרש; יש לברר את תנאי המקור והאכילה.'
                if verdict=='insufficient_context' else
                'נמצאו מקורות לעיון, אך פלט המודל לא עבר אימות. אין להסתמך עליו להכרעה.')
            mode = "llm-guarded"
        supported = {e['source_id'] for e in v.get('evidence',[])}
        for source in retrieved:
            if source['source_id'] in supported:
                source['evidence_support']=v.get('support','exact-extract-only')
        res = {"answer": answer, "sources": retrieved, "verdict": verdict,
               "verification": v, "mode": mode,
               "timings":{"post_generation_and_verification_s":round(time.perf_counter()-verification_started,6)},
               "human_review": "required", "halachic_verified": False,
               "elapsed_s": round(time.time() - t0, 3)}
        if cacheable:self._cache[q] = (now, res)
        return dict(res)

    def search_only(self, query, top_k=5, request_budget=None, cache_namespace=None):
        if top_k<1:return []
        from .retrieval_budget import search_backend
        if request_budget:request_budget.check('retrieval cache inventory')
        try:
            scoped=isinstance(cache_namespace,str) and bool(cache_namespace) and len(cache_namespace)<=256
            revision=getattr(self.search,'revision',None) if scoped else None
            cacheable=scoped and revision is not None and all(getattr(b,'revision',None) is not None
                        for b in getattr(self.search,'backends',[]))
        except Exception:
            revision=None;cacheable=False
        key=self.retrieval_cache.key(query,top_k,revision,catalog_revision(),cache_namespace) if cacheable else None
        if key and self.retrieval_cache.ttl>0:
            from .request_budget import BudgetExceeded
            try:cached=self.retrieval_cache.get(key,self.knowledge.source_by_id,request_budget)
            except BudgetExceeded:raise
            except Exception:cached=None
            if cached is not None:
                hit=SearchResults(cached);hit.metrics={'cache_hit':True,'selected_count':len(hit)}
                return hit
        # Candidate selection precedes eligibility/ranking. Fifty fused rows
        # dropped explicit authorised units behind neighbouring-subject hits.
        # Bounded expansion uses the SAME indexes and request deadline.
        from .retrieval_plan import plan
        from .hybrid import rrf_fuse
        search_plan=plan(query)
        runs=[];route_trace=[]
        from .locator_search import parse,lookup,reference_only
        if parse(query):
            located=lookup(self.knowledge,query,request_budget)
            runs.append(located);route_trace.append({'kind':'explicit-locator','candidates':len(located),'reason':'literal book/siman/seif metadata'})
        for route in search_plan['routes']:
            if reference_only(query) and runs:break  # a locator lookup is not an invitation to substitute another passage
            if runs:
                preliminary=order_sources(rrf_fuse(runs,top_k=200),query)
                if any(rag_eligible(s) and s['concept_coverage']['complete'] for s in preliminary):break
            if request_budget:request_budget.check('planned retrieval route')
            found=search_backend(self.search,route['query'],100,request_budget)
            runs.append(found)
            route_trace.append({'kind':route['kind'],'candidates':len(found),'reason':route['reason']})
            if getattr(found,'errors',[]):break  # a fallback cannot erase partial search or identity failure
        results=rrf_fuse(runs,top_k=200)
        errors=[e for run in runs for e in getattr(run,'errors',[])]+getattr(results,'errors',[])
        results=SearchResults(results,errors)
        ordered=order_sources(results,query)
        if not parse(query):ordered=semantic_rerank(ordered,query,self.search,request_budget)
        # Pending locators must not be promoted by diversity over usable passages.
        usable=[s for s in ordered if rag_eligible(s)]
        pending=[s for s in ordered if not rag_eligible(s)]
        selected=diverse_sources(usable,top_k)
        selected=selected+diverse_sources(pending,top_k-len(selected)) if len(selected)<top_k else selected
        out=SearchResults(selected,getattr(results,'errors',[]))
        out.metrics={'cache_hit':False,'candidate_count':len(results),'selected_count':len(out),
                     'routes':route_trace,'max_routes':search_plan['max_routes']}
        if key and selected and not out.errors and self.retrieval_cache.ttl>0:
            self.retrieval_cache.put(key,selected)
        return out

    def converse(self, question, circumstances=None, research=False, **kwargs):
        from .orchestration import HalachicOrchestrator
        result=HalachicOrchestrator(self).answer(question,circumstances,research,**kwargs)
        from . import config
        if config.get('ANSWER_GATE','1')!='0' and isinstance(result,dict):
            from .answer_gate import gate
            result=gate(question,result)
        return result

    def conversation_turn(self, store, owner, conversation_id, question, circumstances=None, **kwargs):
        """Trusted local service caller only; memory never replaces retrieval."""
        return store.turn(self,owner,conversation_id,question,circumstances,**kwargs)

    def research(self, question, top_k=5, answer_model=None, local_sources=None, request_budget=None):
        from .torah_web import HybridHalachicResearch
        if fastpath.is_out_of_scope(question):
            return self.ask(question)
        if self.research_engine is None:
            import os, json
            from pathlib import Path
            grants_path = os.environ.get('WEB_PERMISSIONS_PATH')
            def permission_loader():
                from .ingest import load_licenses
                grants=json.loads(Path(grants_path).read_text(encoding='utf-8')) if grants_path else {}
                if not isinstance(grants,dict):raise ValueError('invalid web permission registry')
                return load_licenses(),grants
            self.research_engine = HybridHalachicResearch(grants={},licenses={},
                permission_loader=permission_loader,
                store_path=os.environ.get('WEB_STORE_PATH','data/store/torah-web/sources.jsonl'))
        engine = self.research_engine
        result = engine.answer(question, self.base_url, self.model, limit=top_k,
                             local_sources=[s for s in (self.search_only(question,top_k=top_k) if local_sources is None else local_sources) if rag_eligible(s)],
                             answer_model=answer_model if answer_model is not None else self.answer_model,
                             source_verifier=self.source_verifier,request_budget=request_budget,
                             source_resolver=self.knowledge.source_by_id)
        approved = [s for s in result.get('sources',[]) if s.get('source_project')=='verified-web'
                    and s.get('metadata',{}).get('persistence_allowed')]
        if approved and engine.store_path and getattr(engine,'allow_local_reuse',True) and (request_budget is None or request_budget.remaining()>0):
            self.knowledge.upsert_verified(approved)
            self._cache.clear()
        return result
