"""Propagate deadlines without retrying legacy backends after TypeError."""
import inspect

def accepts_budget(call):
    parameters=inspect.signature(call).parameters
    return 'request_budget' in parameters or any(p.kind==p.VAR_KEYWORD for p in parameters.values())

def search_backend(backend, query, top_k, request_budget=None):
    if request_budget:request_budget.check('search backend')
    kwargs={'top_k':top_k}
    if request_budget and accepts_budget(backend.search):kwargs['request_budget']=request_budget
    result=backend.search(query,**kwargs)
    if request_budget:request_budget.check('search backend return')
    return result
