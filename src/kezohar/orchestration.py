"""Deterministic specialists share retrieved evidence and one generation budget."""
from . import fastpath
from .question_understanding import analyze, effective_question, conflict_confirmation
from .discovery import SourceDiscoveryAgent
from .halachic_reasoning import HalachicReasoningAgent
from .answer_composition import VerifiedAnswerComposer
from .request_budget import RequestBudget, BudgetedAnswerModel, BudgetExceeded


class HalachicOrchestrator:
    def __init__(self, agent):
        self.agent = agent
        self.discovery = SourceDiscoveryAgent(agent)
        self.reasoning = HalachicReasoningAgent()
        self.composer = VerifiedAnswerComposer()

    def answer(self, question, circumstances=None, research=False, **kwargs):
        from .concept_questions import focused_followup
        focused=focused_followup(question,kwargs.get('conversation_history'))
        if focused:question=focused
        from .question_intent import QuestionIntentRouter
        route=QuestionIntentRouter().route(question)
        if route['engine']=='jewish-knowledge':
            if research:route=dict(route,explicit_web_requested=True)
            from .torah_facts import JewishResearchOrchestrator
            return JewishResearchOrchestrator(self.agent).answer(question,route,**kwargs)
        kwargs.pop('conversation_history',None)
        import time
        started=time.perf_counter()
        from .source_rules import validate_answers
        rule_answers=validate_answers(kwargs.pop('rule_answers',None))
        cache_namespace=kwargs.pop('cache_namespace',None)
        study_mode=kwargs.pop('study_mode','normal')
        if study_mode not in ('normal','deep'):raise ValueError('unknown study mode')
        budget = kwargs.pop('request_budget', None)
        if budget is None:
            budget = RequestBudget(seconds=90.0 if study_mode=='deep' else 45.0 if research else 5.0,
                                   max_context_bytes=96000 if study_mode=='deep' else 48000)
        if study_mode=='deep':kwargs['top_k']=max(kwargs.get('top_k',5),8)
        trace = ['question-understanding']
        analysis = analyze(question, circumstances)
        from .question_senses import clarification,classify,INSUFFICIENT
        clarification_result=clarification(question,(circumstances or {}).get('fertility_procedure'))
        if clarification_result:
            clarification_result['orchestration']={'stages':trace+['meaning-ambiguity-stop'],'budget':budget.report()}
            return clarification_result
        confirmation=conflict_confirmation(question,analysis)
        confirmation_value=rule_answers.get(confirmation['condition_id']) if confirmation else None
        source_answers={k:v for k,v in rule_answers.items() if not confirmation or k!=confirmation['condition_id']}
        quick = (fastpath.is_out_of_scope(question) or fastpath.handle(question,
                 lat=kwargs.get('lat') or fastpath.DEFAULT_LAT,
                 lon=kwargs.get('lon') or fastpath.DEFAULT_LON,
                 location=kwargs.get('location') or fastpath.DEFAULT_LOCATION) is not None)
        if quick:
            result = self.agent.ask(question, **{k:v for k,v in kwargs.items()
                                                if k in ('top_k','lat','lon','location','timeout','cache_ttl')})
            result = dict(result)
            result['orchestration'] = {'stages': trace + ['fast-path'], 'budget': budget.report(),
                                       'complexity': 'deterministic-fast-path'}
            return self.composer.compose(result)
        # Missing case facts restrict personal applicability, not retrieval.
        # Search and the independent verifier still run before any clarification.
        # No default circumstance is created to manufacture a case ruling.
        analysis_s=time.perf_counter()-started
        effective = effective_question(question, analysis)
        # A selected procedure disambiguates the root retrieval query too; an
        # appended circumstance alone must not leave the lexical root ambiguous.
        if classify(question)['domain']=='fertility-treatment' and classify(question)['ambiguous']:
            from .question_understanding import SLOTS
            effective=question+' — '+SLOTS['fertility_procedure'][1][analysis['circumstances']['fertility_procedure']]+effective[len(question):]
        try:
            budget.check('source discovery')
            discovery = self.discovery.discover(effective, kwargs.get('top_k',5), kwargs.pop('retrieved_sources',None),budget,cache_namespace=cache_namespace)
            budget.check('source inventory')
        except BudgetExceeded:
            result=self.composer.compose({'answer':'הבקשה הגיעה למגבלת הזמן; אין תשובה מאומתת.',
                'verdict':'budget_exhausted','mode':'sources-only','sources':[],
                'search_status':{'partial':True,'errors':[{'stage':'retrieval','error':'deadline-exhausted'}]}})
            result['orchestration']={'stages':trace+['budget-stop'],'budget':budget.report()}
            return result
        sources = discovery['sources']
        if discovery['search_status']['partial']:
            result=self.composer.compose({'answer':'החיפוש הושלם באופן חלקי; אין תשובה מאומתת.',
                'verdict':'partial_search','mode':'sources-only','sources':sources,
                'search_status':discovery['search_status']})
            result['orchestration']={'stages':trace+['partial-search-stop'],'budget':budget.report()}
            return result
        trace += ['source-discovery', 'contextual-source-selection']
        # Reasoning inventories only admissible evidence. Pending sources can
        # remain visible as search results, but not as context or reasoning proof.
        eligible = self.agent.source_verifier.eligible_sources(effective, sources)
        reasoning = self.reasoning.analyze(effective, analysis, eligible)
        trace.append('source-backed-case-inventory')
        generator = BudgetedAnswerModel(self.agent.answer_model, budget,
            source_resolver=None if research else self.agent.knowledge.source_by_id)
        if research:
            result = self.agent.research(effective, top_k=kwargs.get('top_k',5),
                                         answer_model=generator, local_sources=sources,request_budget=budget)
            trace.append('explicit-web-research')
            reasoning = self.reasoning.analyze(effective, analysis,
                         self.agent.source_verifier.eligible_sources(effective,result.get('sources',[])))
        else:
            result = self.agent.ask(effective, retrieved_sources=sources, answer_model=generator, **kwargs)
        if budget.reason:
            result=dict(result)
            result.update(answer='מצב חיפוש: הבקשה הגיעה למגבלת הזמן, הקריאות או ההקשר; אין תשובה מאומתת.',
                          verdict='budget_exhausted',mode='sources-only')
        trace += ['independent-source-verifier', 'verified-answer-composer']
        composing=time.perf_counter()
        result = self.composer.compose(result, reasoning, question=question, rule_answers=source_answers, conditional_first=True,relevance_question=effective)
        compose_s=time.perf_counter()-composing
        if budget.remaining()<=0:
            budget.reason=budget.reason or result.get('technical_error',{}).get('code') or 'answer composition exceeded request deadline'
            result=self.composer.compose({'answer':'הבקשה הגיעה למגבלת הזמן; אין תשובה מאומתת.',
                'sources':[],'verdict':'budget_exhausted','mode':'sources-only',
                'search_status':result.get('search_status',discovery['search_status']),
                'technical_error':result.get('technical_error',{}),
                'verification':{'verdict':'budget_exhausted','support':budget.reason}})
        # Contradictory supplied facts cannot be covered by an assumed branch.
        # Ask only one, AFTER displaying any source-backed rule we could verify.
        if confirmation and confirmation_value is None and result.get('verdict') in ('ok','no_source','insufficient_context'):
            candidates=[confirmation]
            if candidates:
                result['clarifications']=candidates[:1]
                result['answer']+='\nיש סתירה בפרטים שנמסרו; אין הכרעה אישית. '+candidates[0]['question']
                result['mode']='rule-with-clarification' if result.get('verification',{}).get('verdict')=='ok' else 'clarification'
                result['verdict']='rule_needs_clarification' if result.get('verification',{}).get('verdict')=='ok' else 'needs_clarification'
                result['structured_answer']['short_answer']=result['answer']
                from .answer_status import describe
                result['answer_status']=describe(result)
        if (analysis['intent']=='immersion-time' and 'immersion_purpose' in analysis['missing_fields']
                and not analysis['unable_to_clarify'] and not result.get('clarifications')
                and result.get('verdict') in ('ok','no_source','insufficient_context')):
            # The type of action is unknown, not merely a detail inside a
            # known rule. Search was attempted; no unrelated bathing rule is
            # substituted for personal ritual immersion.
            c=next(c for c in analysis['clarifications'] if c['field']=='immersion_purpose')
            result['clarifications']=[c]
            result['answer']='לא ברור אם שאלת על טבילת אישה, כלים או טבילה כמנהג. '+c['question']
            result['verdict']='rule_needs_clarification' if result.get('verification',{}).get('verdict')=='ok' else 'needs_clarification'
            result['mode']='clarification'
            result['structured_answer']['short_answer']=result['answer']
            from .answer_status import describe
            result['answer_status']=describe(result)
        result['answer_policy']={'name':'verified-rules-first','personal_ruling_verified':False,
            'missing_case_fields':analysis['missing_fields'],'conflicting_fields':analysis['conflicting_fields'],
            'clarification_count':len(result.get('clarifications',[])),
            'search_before_clarification':True,'conditional_source_reading':True,
            'conflict_confirmation':{'id':confirmation['condition_id'],'reported_answer':confirmation_value} if confirmation else None}
        if result.get('verification',{}).get('verdict')!='ok':
            reasoning=dict(reasoning,supported_statement_units=[],distinction_candidates=[],difference_candidates=[],rule_inventories=[])
        graph=getattr(self.agent,'source_graph',None)
        if graph is not None and not budget.reason and budget.remaining()>0 and (research or reasoning['difference_candidates']):
            admissible=self.agent.source_verifier.eligible_sources(effective,result.get('sources',[]))
            # Co-retrieval is only a proposal. It never creates a cites/follows/
            # disagrees edge or sends graph metadata to the answer model.
            for a,b in zip(admissible[:3],admissible[1:4]):
                if a['source_id']!=b['source_id']:
                    graph.propose(a,b,'same-issue','co-retrieval candidate; relationship not established')
            result['source_relationships']=graph.relationships(admissible)
            trace.append('proposed-source-relationships')
        result.update(question_analysis=analysis, original_question=question,
                      discovery_analysis=discovery['query_analysis'], reasoning=reasoning,
                      differences=reasoning['difference_candidates'])
        from .research_dossier import build
        result['research_dossier']=build(question,analysis,result,graph=graph)
        if budget.remaining()<=0 or (budget.cancel_event is not None and budget.cancel_event.is_set()):
            return self.composer.compose({'verdict':'budget_exhausted','sources':[],
                'search_status':result.get('search_status',discovery['search_status']),
                'answer':'העיון הופסק או הגיע למגבלת הזמן; לא מוצגת תשובה מאומתת.',
                'verification':{'verdict':'budget_exhausted','support':'analysis deadline or cancellation'},
                'research_dossier':{'status':'cancelled-or-expired','claims':[],'halachic_verified':False}})
        result['research_dossier']['study_mode']=study_mode
        result['explanation'] = result['structured_answer']['explanation']
        result.setdefault('search_status',discovery['search_status'])
        result['timings']=dict(result.get('timings',{}),**generator.timings,
            question_analysis_s=round(analysis_s,6),retrieval_s=discovery['timing_s'],
            composition_s=round(compose_s,6),total_s=round(time.perf_counter()-started,6),
            model_loading_s=None,model_time_scope='transport, queue and generation; loading not separately measurable')
        result['retrieval_metrics']=discovery['retrieval_metrics']
        result['orchestration'] = {'stages':trace, 'budget':budget.report(),
                                   'retrieval_reused':discovery['reused_retrieval'],
                                   'complexity':'multi-source-review' if reasoning['difference_candidates'] or research else 'focused-case',
                                   'model_changed':False}
        return result
