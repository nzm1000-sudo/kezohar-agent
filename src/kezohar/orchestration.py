"""Deterministic specialists share retrieved evidence and one generation budget."""
from . import fastpath
from .question_understanding import analyze, contextual_question
from .discovery import SourceDiscoveryAgent
from .halachic_reasoning import HalachicReasoningAgent
from .answer_composition import VerifiedAnswerComposer
from .request_budget import RequestBudget, BudgetedAnswerModel


class HalachicOrchestrator:
    def __init__(self, agent):
        self.agent = agent
        self.discovery = SourceDiscoveryAgent(agent)
        self.reasoning = HalachicReasoningAgent()
        self.composer = VerifiedAnswerComposer()

    def answer(self, question, circumstances=None, research=False, **kwargs):
        budget = kwargs.pop('request_budget', None)
        if budget is None:
            budget = RequestBudget(seconds=45.0 if research else 5.0)
        trace = ['question-understanding']
        analysis = analyze(question, circumstances)
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
            return result
        if analysis['requires_clarification']:
            result = {'answer': 'כדי להתאים את המקורות למקרה: ' + ' '.join(
                        c['question'] for c in analysis['clarifications']),
                      'mode':'clarification', 'verdict':'needs_clarification', 'sources':[],
                      'question_analysis':analysis, 'clarifications':analysis['clarifications'],
                      'explanation':'טרם ניתנה הכרעה הלכתית; חסרות נסיבות או שיש סתירה.',
                      'original_question':question,
                      'orchestration':{'stages':trace+['clarification'], 'budget':budget.report(),
                                       'complexity':'incomplete-case'}}
            return self.composer.compose(result)
        effective = contextual_question(question, analysis)
        if analysis['circumstances']['tradition'] == 'ashkenazi':
            effective += '\nלפי פסיקת האשכנזים'
        elif analysis['circumstances']['tradition'] == 'both':
            effective += '\nהשוואת מסורות'
        discovery = self.discovery.discover(effective, kwargs.get('top_k',5), kwargs.pop('retrieved_sources',None))
        sources = discovery['sources']
        trace += ['source-discovery', 'contextual-source-selection']
        # Reasoning inventories only admissible evidence. Pending sources can
        # remain visible as search results, but not as context or reasoning proof.
        eligible = self.agent.source_verifier.eligible_sources(effective, sources)
        reasoning = self.reasoning.analyze(effective, analysis, eligible)
        trace.append('source-backed-case-inventory')
        generator = BudgetedAnswerModel(self.agent.answer_model, budget)
        if research:
            result = self.agent.research(effective, top_k=kwargs.get('top_k',5),
                                         answer_model=generator, local_sources=sources)
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
        result = self.composer.compose(result, reasoning)
        graph=getattr(self.agent,'source_graph',None)
        if graph is not None and (research or reasoning['difference_candidates']):
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
        result['orchestration'] = {'stages':trace, 'budget':budget.report(),
                                   'retrieval_reused':discovery['reused_retrieval'],
                                   'complexity':'multi-source-review' if reasoning['difference_candidates'] or research else 'focused-case',
                                   'model_changed':False}
        return result
