"""Bounded real Hebrew retrieval probe; no index/model downloads or psak gold."""
import sys,json,time,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kezohar import config
from kezohar.api import get_agent
from kezohar.local_embeddings import LocalEmbeddingModel
from kezohar.source_snapshot import admissible,fingerprint
from kezohar.vector import cosine
SAMPLES=[
 ('549a142c342ec7c1',['מה מברכים על פקאן?','איזו ברכה לפני אכילת אגוז פקאן?']),
 ('0eae057b287626f7',['שכחתי לברך ברכת המזון, האם מאוחר מדי?','מתי אפשר עדיין לברך אחרי שאכלתי לחם?']),
 ('32ac824faedcec19',['מותר לדבר בין תפילין של יד לתפילין של ראש?','האם אפשר לשוחח באמצע הנחת תפילין?']),
]
def main():
 root=Path('data/store/autonomous-evaluation');p=root/'existing-embeddings-probe.json'
 if p.exists():raise FileExistsError('existing real probe must be preserved; no repeated model calls')
 a=get_agent();rows=[];sources=[]
 for sid,queries in SAMPLES:
  source=a.knowledge.source_by_id(sid)
  if source is None or not admissible(source):raise ValueError('probe source unavailable or not permitted')
  sources.append(source)
 model='text-embedding-nomic-embed-text-v1.5'
 settings=config.EmbeddingSettings('openai-compatible-local',model,768,'installed-v1.5','raw-text+nomic-prefix-v1')
 client=LocalEmbeddingModel(settings,base_url=config.llm_base_url())
 start=time.perf_counter();documents=client.embed_many([s['text'] for s in sources])
 queries=[q for sid,qs in SAMPLES for q in qs]
 query_vectors=client.embed_many(queries,task='query')
 for i,(q,vector) in enumerate(zip(queries,query_vectors)):
  scores=[cosine(vector,d) for d in documents];winner=max(range(len(scores)),key=scores.__getitem__)
  ordered=sorted(scores,reverse=True)
  rows.append({'query':q,'expected_retrieval_source_id':SAMPLES[i//2][0],
    'ranked_sources':[{'source_id':sources[j]['source_id'],'similarity':scores[j]} for j in sorted(range(len(scores)),key=scores.__getitem__,reverse=True)],
    'retrieval_match':sources[winner]['source_id']==SAMPLES[i//2][0],'margin':ordered[0]-ordered[1]})
 result={'spec':client.spec.manifest(),'elapsed_s':round(time.perf_counter()-start,3),'rows':rows,
    'sources':[{'source_id':s['source_id'],'snapshot':fingerprint(s),'reference':s['reference']} for s in sources],
    'vectors':{'documents':documents,'queries':query_vectors},
    'activation':'not-activated; this small retrieval-only probe cannot establish halachic accuracy',
    'human_halachic_review':'required','halachic_verified':False}
 root=Path('data/store/autonomous-evaluation');root.mkdir(parents=True,exist_ok=True)
 p=root/'existing-embeddings-probe.json'
 if p.exists():raise FileExistsError('existing real probe must be preserved')
 p.write_text(json.dumps(result,ensure_ascii=False,indent=2));os.chmod(p,0o600)
 print(json.dumps({'elapsed_s':result['elapsed_s'],'retrieval_matches':sum(r['retrieval_match'] for r in rows),
    'total':len(rows),'mean_margin':sum(r['margin'] for r in rows)/len(rows),
    'activation':result['activation'],'path':str(p)},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
