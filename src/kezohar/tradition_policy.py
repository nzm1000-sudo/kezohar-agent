"""Explicit selection preferences, never an algorithm deciding disputes."""
from dataclasses import dataclass
from .halachic_authority import profile

@dataclass(frozen=True)
class TraditionPolicy:
    name:str
    preferred_authorities:tuple
    def inspect(self,sources):
        rows=[]
        for s in sources:
            p=profile(s)
            rows.append({'source_id':s['source_id'],'reference':s['reference'],
                'tradition':p['tradition'],'role':p['role'],'authority':p['authority'],
                'preferred_for_selection':p['authority'] in self.preferred_authorities,
                'other_views_embedded':p['embedded_other_views'],
                'passage_agrees_with_case':False,'edition':p['edition']})
        return {'name':self.name,'sources':rows,'dispute_resolution':'not-automated',
                'authority_does_not_prove_claim':True,'halachic_verified':False}

POLICIES={'sephardi':TraditionPolicy('sephardi',('maran','rav-ovadia-yosef','yalkut-yosef')),
          'ashkenazi':TraditionPolicy('ashkenazi',('ashkenazi-posek',)),
          'both':TraditionPolicy('both',())}

def policy(name):
    if name not in POLICIES:raise ValueError('unknown tradition policy')
    return POLICIES[name]
