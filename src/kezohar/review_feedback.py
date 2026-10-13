"""Anonymous issue tags only; no questions, answers, names or free-text memory."""
import json,os,threading,hashlib
from pathlib import Path
ISSUES={'source-mismatch','missing-condition','unclear-answer','unnecessary-clarification','citation-problem'}
LOCK=threading.Lock()

def record(path,issue,source_ids,answer_digest):
    if not isinstance(issue,str) or issue not in ISSUES or not isinstance(source_ids,list) or len(source_ids)>8:
        raise ValueError('known issue and bounded source IDs required')
    if any(not isinstance(s,str) or not s or len(s)>256 for s in source_ids):raise ValueError('invalid source IDs')
    if not isinstance(answer_digest,str) or len(answer_digest)!=64 or any(c not in '0123456789abcdef' for c in answer_digest):
        raise ValueError('SHA256 answer digest required; do not send personal text')
    row={'issue':issue,'source_ids':source_ids,'answer_sha256':answer_digest,
         'review_status':'reported-problem; not a halachic approval','halachic_verified':False}
    path=Path(path)
    with LOCK:
        path.parent.mkdir(parents=True,exist_ok=True);os.chmod(path.parent,0o700)
        if path.exists() and path.stat().st_size>=8*1024*1024:raise ValueError('local feedback storage limit reached')
        with path.open('a',encoding='utf-8') as f:
            os.chmod(path,0o600);f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
    return {'recorded':True,'stores_personal_text':False,'halachic_verified':False}
