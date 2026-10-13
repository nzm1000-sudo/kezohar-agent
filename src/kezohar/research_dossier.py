"""Structured issue analysis built only after independent source verification."""
from .answer_composition import snapshot_valid
from .rule_inventory import inventory
from .relationship_extraction import proposals,mentions
from .tradition_policy import policy

def build(question,analysis,result,graph=None):
    v=result.get('verification',{});sources=result.get('sources',[])
    base={'question':question,'subissues':analysis.get('structure',{}).get('clauses',[]),
          'scope':'source analysis, not automatic personal ruling','halachic_verified':False,
          'human_review':'required','claims':[],'relationship_candidates':[],'reviewed_chains':[],
          'bibliographic_mentions':[]}
    if not snapshot_valid(v,sources):return dict(base,status='no-verified-evidence')
    index={s['source_id']:s for s in sources};used=[]
    for e in v.get('evidence',[]):
        s=index[e['source_id']];used.append(s)
        inv=inventory(s)
        base['claims'].append({'source_id':s['source_id'],'reference':s['reference'],'quote':e['quote'],
            'source_snapshot':v['source_snapshots'][s['source_id']],
            'claim_kind':'explicit-source-reading','conditions_and_exceptions':inv['clauses'],
            'conditions_complete':False,'support':'quotation-verified; case-entailment-unproved',
            'case_application_verified':False,'halachic_verified':False})
    for c in v.get('claims',[]):
        base['claims'].append({'source_id':c['source_id'],'reference':index[c['source_id']]['reference'],
            'text':c['text'],'claim_kind':'bounded-supported-reformulation','conditions':c['assessment'].get('conditions',[]),
            'support':c['assessment']['method'],'case_application_verified':False,'halachic_verified':False})
    base['tradition_policy']=policy(analysis['circumstances']['tradition']).inspect(used)
    base['relationship_candidates']=proposals(used)
    base['bibliographic_mentions']=[m for s in used for m in mentions(s)]
    if graph is not None:base['reviewed_chains']=graph.chains(used)
    base['uncovered_case_fields']=analysis['missing_fields']
    base['status']='verified-source-dossier; applicability-requires-review'
    return base
