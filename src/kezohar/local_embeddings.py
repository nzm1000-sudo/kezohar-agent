"""Opt-in real embedding client, restricted to an explicit local endpoint.

No downloading or answer-model settings changes. Prefix preprocessing is part
of the index identity; the default production provider remains unchanged.
"""
import ipaddress
import json
import math
import urllib.request
from urllib.parse import urlsplit
from . import config
from .embeddings import VectorIndexSpec,VectorIndexMismatch
from .model_gate import model_slot

class EmbeddingUnavailable(RuntimeError):pass
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def request_embeddings(url,body,timeout):
    request=urllib.request.Request(url,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=timeout) as response:
        raw=response.read(4_000_001)
        if len(raw)>4_000_000:raise EmbeddingUnavailable('embedding response too large')
        return json.loads(raw)

class LocalEmbeddingModel:
    def __init__(self,settings,base_url=None):
        self.settings=settings
        self.base_url=base_url if base_url is not None else config.get('EMBEDDINGS_BASE_URL','')
        parsed=urlsplit(self.base_url)
        try:
            address=ipaddress.ip_address(parsed.hostname) if parsed.hostname!='localhost' else None
            ranges=('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','fc00::/7')
            local=parsed.hostname=='localhost' or address.is_loopback or any(address in ipaddress.ip_network(n) for n in ranges)
        except (ValueError,TypeError):local=False
        if not local or parsed.scheme not in ('http','https') or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('explicit local embedding endpoint required; no remote service')
        self.nomic='nomic-embed-text-v1.5' in settings.model
        expected='raw-text+nomic-prefix-v1' if self.nomic else 'raw-text-v1'
        if settings.normalization!=expected:raise VectorIndexMismatch('embedding preprocessing identity does not match provider')
        if type(settings.dimensions) is not int or settings.dimensions<=0:raise ValueError('positive embedding dimension required')
        self.spec=VectorIndexSpec.from_settings(settings)
    def embed_many(self,texts,task='document',timeout=30):
        if task not in ('document','query'):raise ValueError('unknown embedding task')
        if (not isinstance(texts,list) or not 1<=len(texts)<=16 or any(not isinstance(t,str) or not t.strip() or len(t)>12000 for t in texts)
                or sum(len(t.encode()) for t in texts)>60000):raise ValueError('bounded nonempty text batch required')
        prefix=('search_document: ' if task=='document' else 'search_query: ') if self.nomic else ''
        try:
            with model_slot(timeout) as slot:
                response=request_embeddings(self.base_url.rstrip('/')+'/embeddings',
                    {'model':self.settings.model,'input':[prefix+t for t in texts]},slot['remaining_s'])
        except VectorIndexMismatch:raise
        except Exception as exc:raise EmbeddingUnavailable('local embedding request failed: '+type(exc).__name__) from None
        if not isinstance(response,dict) or response.get('model')!=self.settings.model:
            raise VectorIndexMismatch('embedding response model identity mismatch')
        rows=response.get('data')
        if not isinstance(rows,list) or len(rows)!=len(texts):raise VectorIndexMismatch('embedding batch size mismatch')
        result=[None]*len(texts)
        for row in rows:
            if not isinstance(row,dict):raise VectorIndexMismatch('embedding row malformed')
            index=row.get('index');vector=row.get('embedding')
            if type(index) is not int or not 0<=index<len(texts) or result[index] is not None:
                raise VectorIndexMismatch('embedding row identity ambiguous')
            if (not isinstance(vector,list) or len(vector)!=self.spec.dimensions
                    or any(type(v) not in (int,float) or not math.isfinite(v) for v in vector)):
                raise VectorIndexMismatch('embedding dimension or values mismatch')
            norm=math.hypot(*vector)
            if not math.isfinite(norm) or norm<=0:raise VectorIndexMismatch('invalid embedding norm')
            result[index]=[v/norm for v in vector]
        return result
    def embed(self,text):return self.embed_many([text])[0]
    def embed_query(self,text):return self.embed_many([text],task='query')[0]
