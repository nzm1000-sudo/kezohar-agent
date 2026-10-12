"""Bounded cache of source ids/annotations, never answers or user memory.

Every hit resolves each source again and checks its complete fingerprint. Backend
revision and evidence policy bind the candidate set; errors are never cached.
"""
import copy
import hashlib
import threading
import time
from collections import OrderedDict
from .source_snapshot import fingerprint

class RetrievalCache:
    def __init__(self,capacity=64,ttl=30):
        self.capacity=capacity;self.ttl=ttl;self.entries=OrderedDict();self.lock=threading.RLock()
    def key(self,query,top_k,revision,policy,namespace):
        return hashlib.sha256((namespace+'|'+str(query)+'|'+str(top_k)+'|'+repr(revision)+'|'+policy).encode()).hexdigest()
    def get(self,key,resolver,budget=None):
        with self.lock:
            entry=self.entries.get(key)
            if entry is None:return None
            stamp,records=entry
            if time.monotonic()-stamp>=self.ttl:
                self.entries.pop(key,None);return None
            records=copy.deepcopy(records)
        result=[]
        for sid,digest,annotations in records:
            if budget:budget.check('retrieval cache source revalidation')
            from .retrieval_budget import accepts_budget
            options={'request_budget':budget} if budget and accepts_budget(resolver) else {}
            current=resolver(sid,**options)
            if not current or fingerprint(current)!=digest:
                with self.lock:self.entries.pop(key,None)
                return None
            # Identity/text/permission fields come exclusively from fresh I/O.
            current=dict(current);current.update(annotations);result.append(current)
        with self.lock:
            if key in self.entries:self.entries.move_to_end(key)
        return result
    def put(self,key,sources):
        from .models import Source
        identity=set(Source.__dataclass_fields__)
        records=[(s['source_id'],fingerprint(s),{k:copy.deepcopy(v) for k,v in s.items()
                   if k not in identity and k not in ('identity_conflict','verification_status')}) for s in sources]
        with self.lock:
            self.entries[key]=(time.monotonic(),records);self.entries.move_to_end(key)
            while len(self.entries)>self.capacity:self.entries.popitem(last=False)
