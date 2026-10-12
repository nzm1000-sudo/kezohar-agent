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
        from .source_rules import validate_answers
        rule_answers=validate_answers(kwargs.pop('rule_answers',None))
        budget = kwargs.pop('request_budget', None)
        if budget is None:
            budget = RequestBudget(seconds=45.0 if research else 5.0)
        trace = ['question-understanding']
        analysis = analyze(question, circumstances)
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
        effective = effective_question(question, analysis)
        try:
            budget.check('source discovery')
            discovery = self.discovery.discover(effective, kwargs.get('top_k',5), kwargs.pop('retrieved_sources',None),budget)
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
        result = self.composer.compose(result, reasoning, question=question, rule_answers=source_answers, conditional_first=True)
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
        result['answer_policy']={'name':'verified-rules-first','personal_ruling_verified':False,
            'missing_case_fields':analysis['missing_fields'],'conflicting_fields':analysis['conflicting_fields'],
            'clarification_count':len(result.get('clarifications',[])),
            'search_before_clarification':True,'conditional_source_reading':True,
            'conflict_confirmation':{'id':confirmation['condition_id'],'reported_answer':confirmation_value} if confirmation else None}
        if result.get('verification',{}).get('verdict')!='ok':
            reasoning=dict(reasoning,supported_statement_units=[],distinction_candidates=[],difference_candidates=[])
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
        result['explanation'] = result['structured_answer']['explanation']
        result.setdefault('search_status',discovery['search_status'])
        result['orchestration'] = {'stages':trace, 'budget':budget.report(),
                                   'retrieval_reused':discovery['reused_retrieval'],
                                   'complexity':'multi-source-review' if reasoning['difference_candidates'] or research else 'focused-case',
                                   'model_changed':False}
        return result
