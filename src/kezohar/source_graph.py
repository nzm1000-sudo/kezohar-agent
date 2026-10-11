"""SQLite relationship proposals with fingerprints and explicit human review.

Graph nodes are metadata, not a substitute for retrieving authorized source text.
Even a reviewed edge is not an automated halachic ruling or claim-support proof.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
from .models import utcnow_iso
from .permissions import rag_eligible

ROOT=Path(__file__).resolve().parents[2]
RELATIONS={'interprets','cites','same-issue','distinguishes-cases','disagrees','follows','refers-to'}


def fingerprint(source):
    fields={k:source.get(k,'') for k in ('source_id','work_title','author','reference','version','text','source_url')}
    return hashlib.sha256(json.dumps(fields,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def admissible(source):
    return (rag_eligible(source) and source.get('source_id') and source.get('reference')
            and source.get('metadata',{}).get('locator_status')!='ambiguous-file-fields')


class HalachicSourceGraph:
    def __init__(self, path=None):
        self.path=Path(path or ROOT/'data/store/source-graph/graph.sqlite3').resolve()
        if ROOT not in self.path.parents:raise ValueError('graph must remain inside project')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, metadata TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS edges (id TEXT PRIMARY KEY, subject TEXT NOT NULL, object TEXT NOT NULL, relation TEXT NOT NULL, status TEXT NOT NULL, evidence TEXT NOT NULL, review TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS edges_subject ON edges(subject)')
            db.execute('CREATE INDEX IF NOT EXISTS edges_object ON edges(object)')

    def _db(self):
        return sqlite3.connect(str(self.path),timeout=5)

    def propose(self, subject, object_source, relation, method, quote=None, witness=None):
        if relation not in RELATIONS or not isinstance(method,str) or not method.strip():
            raise ValueError('known relationship and proposal rationale required')
        if not admissible(subject) or not admissible(object_source):
            raise ValueError('both source identities must be retrieved and admissible')
        if subject['source_id']==object_source['source_id']:raise ValueError('distinct source identities required')
        evidence={'method':method,'subject_fingerprint':fingerprint(subject),
                  'object_fingerprint':fingerprint(object_source),'created_at':utcnow_iso()}
        if quote is not None:
            if (not witness or witness.get('source_id') not in (subject['source_id'],object_source['source_id'])
                    or not isinstance(quote,str) or not quote.strip() or quote not in witness.get('text','')):
                raise ValueError('relationship witness must be an exact quote from an endpoint')
            evidence.update(witness_id=witness['source_id'],quote=quote)
        identity=[subject['source_id'],object_source['source_id'],relation,
                  evidence['subject_fingerprint'],evidence['object_fingerprint'],quote]
        eid=hashlib.sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest()
        with self._db() as db:
            for source in (subject,object_source):
                metadata={k:source.get(k,'') for k in ('source_id','work_title','author','reference','version','source_url','tradition')}
                db.execute('INSERT OR REPLACE INTO nodes VALUES (?,?,?)',
                           (source['source_id'],fingerprint(source),json.dumps(metadata,ensure_ascii=False)))
            # Repeated discovery must not erase or upgrade an existing review.
            db.execute('INSERT OR IGNORE INTO edges VALUES (?,?,?,?,?,?,?)',
                       (eid,subject['source_id'],object_source['source_id'],relation,'proposed',
                        json.dumps(evidence,ensure_ascii=False),'{}'))
        return eid

    def review(self, edge_id, current_sources, reviewer, rationale, accepted=True):
        if not reviewer.strip() or not rationale.strip():raise ValueError('explicit reviewer and rationale required')
        with self._db() as db:
            row=db.execute('SELECT subject,object,evidence FROM edges WHERE id=?',(edge_id,)).fetchone()
            if not row:raise KeyError('edge unavailable')
            subject,object_id,raw=row
            evidence=json.loads(raw)
            sources={s['source_id']:s for s in current_sources}
            a,b=sources.get(subject),sources.get(object_id)
            if (not a or not b or not admissible(a) or not admissible(b)
                    or fingerprint(a)!=evidence['subject_fingerprint'] or fingerprint(b)!=evidence['object_fingerprint']):
                raise ValueError('current retrieved source snapshots do not match proposal')
            witness=sources.get(evidence.get('witness_id'))
            if accepted and (not witness or not evidence.get('quote')
                             or evidence['quote'] not in witness.get('text','')):
                raise ValueError('similarity alone cannot be promoted to a reviewed halachic relationship')
            review={'reviewer':reviewer,'rationale':rationale,'reviewed_at':utcnow_iso(),
                    'scope':'human-reviewed relationship only; not ruling or general entailment'}
            db.execute('UPDATE edges SET status=?,review=? WHERE id=?',
                       ('human-reviewed' if accepted else 'rejected',json.dumps(review,ensure_ascii=False),edge_id))

    def relationships(self, current_sources):
        sources={s['source_id']:s for s in current_sources if admissible(s)}
        if not sources:return []
        ids=list(sources)
        placeholders=','.join('?' for _ in ids)
        with self._db() as db:
            rows=db.execute('SELECT id,subject,object,relation,status,evidence,review FROM edges WHERE subject IN ('+placeholders+') AND object IN ('+placeholders+')',ids+ids).fetchall()
        result=[]
        for eid,subject,obj,relation,status,raw,review in rows:
            evidence=json.loads(raw)
            if (fingerprint(sources[subject])!=evidence['subject_fingerprint']
                    or fingerprint(sources[obj])!=evidence['object_fingerprint']):
                status='stale-evidence'
            result.append({'edge_id':eid,'subject':subject,'object':obj,'relation':relation,
                           'status':status,'evidence':evidence,'review':json.loads(review),
                           'usable_as_claim_support':False,'halachic_verified':False})
        return result
