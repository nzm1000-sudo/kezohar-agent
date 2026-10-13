"""Derived graph/mention candidates from captured public eval sources, no AI."""
import gzip,json,os
from pathlib import Path
from diagnose_answer import get_agent
from kezohar.source_snapshot import admissible,fingerprint
from kezohar.relationship_extraction import persist,mentions
from kezohar.source_graph import HalachicSourceGraph

def main():
    a=get_agent();a.source_graph=None
    raw=gzip.decompress(Path('docs/quality-100-artifacts/refinement.jsonl.gz').read_bytes())
    old={s['source_id']:s for row in map(json.loads,raw.splitlines()) for s in row['result'].get('sources',[]) if admissible(s)}
    sources=[]
    for sid,record in list(old.items())[:500]:
        current=a.knowledge.source_by_id(sid)
        if current and admissible(current) and fingerprint(current)==fingerprint(record):sources.append(current)
    root=Path('data/store/advanced-research');root.mkdir(exist_ok=True);os.chmod(root,0o700)
    graph=HalachicSourceGraph(root/'graph.sqlite3')
    proposals=persist(graph,sources)
    rows=[m for s in sources for m in mentions(s)]
    path=root/'bibliographic-candidates.json'
    path.write_text(json.dumps({'sources_revalidated':len(sources),'graph_proposals':proposals,
                                'unresolved_mentions':rows,'halachic_verified':False},ensure_ascii=False,indent=2))
    os.chmod(path,0o600)
    print(json.dumps({'sources_revalidated':len(sources),'graph_candidates':len(proposals),
                      'unresolved_mentions':len(rows),'human_approved':0},ensure_ascii=False))
if __name__=='__main__':main()
