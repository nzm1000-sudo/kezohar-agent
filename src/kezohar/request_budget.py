"""Request-local limits. No global model settings or retry loops."""
import time
from .llm import LLMUnavailable, build_messages
from .source_snapshot import fingerprint, admissible


class BudgetExceeded(LLMUnavailable):
    pass

class SourceChanged(LLMUnavailable):
    pass

def revalidate_sources(sources,resolver,request_budget=None):
    from .retrieval_budget import accepts_budget
    current=[]
    for source in sources:
        if request_budget:request_budget.check('source revalidation lookup')
        opts={'request_budget':request_budget} if request_budget and accepts_budget(resolver) else {}
        current.append(resolver(source['source_id'],**opts))
        if request_budget:request_budget.check('source revalidation return')
    if any(s is None or not admissible(s) or fingerprint(s)!=fingerprint(old)
           for s,old in zip(current,sources)):
        raise SourceChanged('source identity or permission changed before generation')
    return sources  # retain retrieval annotations only after security identity matches


class RequestBudget:
    def __init__(self, seconds=5.0, max_calls=1, max_context_bytes=48000,cancel_event=None):
        if seconds <= 0 or max_calls not in (0, 1) or max_context_bytes < 4096:
            raise ValueError('invalid request budget')
        self.started = time.monotonic()
        self.seconds = seconds
        self.max_calls = max_calls
        self.max_context_bytes = max_context_bytes
        self.calls = 0
        self.context_bytes = 0
        self.dropped_source_ids = []
        self.reason = None
        self.cancel_event=cancel_event
        self.web_requests=0
        import threading
        self._web_lock=threading.Lock()

    def remaining(self):
        return max(0.0, self.seconds - (time.monotonic() - self.started))

    def check(self, stage):
        if self.cancel_event is not None and self.cancel_event.is_set():
            self.reason='request cancelled before '+stage
            raise BudgetExceeded(self.reason)
        if self.remaining()<=0:
            self.reason='request deadline exhausted before '+stage
            raise BudgetExceeded(self.reason)

    def report(self):
        return {'elapsed_s': round(time.monotonic() - self.started, 3),
                'deadline_s': self.seconds, 'model_calls': self.calls,
                'max_model_calls': self.max_calls, 'context_bytes': self.context_bytes,
                'max_context_bytes': self.max_context_bytes,
                'dropped_source_ids': list(self.dropped_source_ids), 'stop_reason': self.reason,
                'context_measure': 'UTF-8 prompt bytes, not tokenizer tokens',
                'deadline_kind': 'cooperative; in-flight I/O is not forcibly cancelled',
                'web_requests':self.web_requests,'max_web_requests':18}

    def consume_web_request(self):
        self.check('public web request')
        with self._web_lock:
            if self.web_requests>=18:return False
            self.web_requests+=1
            return True

    def fit(self, question, sources):
        chosen = []
        seen = set()
        for source in sources:
            self.check('context preparation')
            sid = source['source_id']
            if sid in seen: continue
            seen.add(sid)
            candidate = chosen + [source]
            size = sum(len(m['content'].encode('utf-8')) for m in build_messages(question, candidate))
            if size > self.max_context_bytes:
                self.dropped_source_ids.append(sid)
            else:
                chosen = candidate
                self.context_bytes = size
        # Never truncate a seif or drop a condition inside a quotation.
        return chosen


class BudgetedAnswerModel:
    def __init__(self, model, budget, source_resolver=None):
        self.model = model
        self.budget = budget
        self.sent_sources = []
        self.timings={}
        self.source_resolver=source_resolver

    @property
    def identity(self):
        return self.model.identity

    def generate(self, question, sources, timeout=4.5):
        started=time.perf_counter()
        budget = self.budget
        budget.check('generation preparation')
        self.sent_sources = budget.fit(question, sources)
        if not self.sent_sources:
            budget.reason = 'no complete source fits context budget'
            raise BudgetExceeded(budget.reason)
        if budget.calls >= budget.max_calls or budget.remaining() <= 0:
            budget.reason = 'model-call or time budget exhausted'
            raise BudgetExceeded(budget.reason)
        if self.source_resolver:
            budget.check('source permission revalidation')
            self.sent_sources=revalidate_sources(self.sent_sources,self.source_resolver,budget)
        budget.check('model call')
        budget.calls += 1
        self.timings['context_and_source_revalidation_s']=round(time.perf_counter()-started,6)
        called=time.perf_counter()
        try:
            import inspect
            opts={'timeout':min(timeout,budget.remaining())}
            if budget.cancel_event is not None and 'cancel_event' in inspect.signature(self.model.generate).parameters:
                opts['cancel_event']=budget.cancel_event
            result = self.model.generate(question, self.sent_sources, **opts)
        finally:
            self.timings['model_call_s']=round(time.perf_counter()-called,6)
        # A provider can return after its timeout; late output must not be used.
        if budget.remaining() <= 0:
            budget.reason = 'generation exceeded request deadline'
            raise BudgetExceeded(budget.reason)
        budget.check('generation result')
        return result
