"""Request-local limits. No global model settings or retry loops."""
import time
from .llm import LLMUnavailable, build_messages


class BudgetExceeded(LLMUnavailable):
    pass


class RequestBudget:
    def __init__(self, seconds=5.0, max_calls=1, max_context_bytes=48000):
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

    def remaining(self):
        return max(0.0, self.seconds - (time.monotonic() - self.started))

    def report(self):
        return {'elapsed_s': round(time.monotonic() - self.started, 3),
                'deadline_s': self.seconds, 'model_calls': self.calls,
                'max_model_calls': self.max_calls, 'context_bytes': self.context_bytes,
                'max_context_bytes': self.max_context_bytes,
                'dropped_source_ids': list(self.dropped_source_ids), 'stop_reason': self.reason,
                'context_measure': 'UTF-8 prompt bytes, not tokenizer tokens',
                'deadline_kind': 'cooperative; in-flight I/O is not forcibly cancelled'}

    def fit(self, question, sources):
        chosen = []
        seen = set()
        for source in sources:
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
    def __init__(self, model, budget):
        self.model = model
        self.budget = budget
        self.sent_sources = []

    @property
    def identity(self):
        return self.model.identity

    def generate(self, question, sources, timeout=4.5):
        budget = self.budget
        self.sent_sources = budget.fit(question, sources)
        if not self.sent_sources:
            budget.reason = 'no complete source fits context budget'
            raise BudgetExceeded(budget.reason)
        if budget.calls >= budget.max_calls or budget.remaining() <= 0:
            budget.reason = 'model-call or time budget exhausted'
            raise BudgetExceeded(budget.reason)
        budget.calls += 1
        result = self.model.generate(question, self.sent_sources, timeout=min(timeout, budget.remaining()))
        # A provider can return after its timeout; late output must not be used.
        if budget.remaining() <= 0:
            budget.reason = 'generation exceeded request deadline'
            raise BudgetExceeded(budget.reason)
        return result
