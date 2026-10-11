"""Evidence desk for ambiguous rows: proposals are never authorization.

Only an approved same-work catalog, a reviewed edition binding, exact full text,
a unique explicit locator and an explicit human review can open a row for RAG.
The original SQLite records remain untouched; resolutions are a checked overlay.
"""
import hashlib
import fcntl
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from .models import utcnow_iso
from .parquet_library import BOOK_ID, TITLE, numeral, visible_text
from .permissions import permission_for

ROOT=Path(__file__).resolve().parents[2]
REGISTRY=ROOT/'data/locator_resolution_registry.json'
RESOLUTIONS=ROOT/'data/store/user-library/approved_resolutions.json'


def read_json(path, default):
    try:
        result=json.loads(Path(path).read_text()) if Path(path).exists() else default
        return result if isinstance(result,dict) else default
    except (OSError,ValueError):return default


def atomic_json(path, value):
    path=Path(path).resolve()
    if ROOT not in path.parents:raise ValueError('artifact must remain inside project')
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    tmp.replace(path)


def full_text_key(text):
    # Visible HTML/whitespace only. Never drop words, punctuation or vowels.
    return re.sub(r'\s+',' ',visible_text(text)).strip()


def trusted_catalogs():
    registry=read_json(REGISTRY,{'resources':[],'edition_bindings':[]})
    catalogs=[]
    entries=registry.get('resources',[])
    if not isinstance(entries,list):return registry,[]
    for entry in entries:
        if not isinstance(entry,dict) or not isinstance(entry.get('path'),str):continue
        path=(ROOT/entry.get('path','')).resolve()
        if (ROOT not in path.parents or not path.is_file() or entry.get('work_id')!=BOOK_ID
                or not entry.get('reviewed_by') or entry.get('approved') is not True
                or not isinstance(entry.get('id'),str)
                or not isinstance(entry.get('approved_hosts'),list)
                or not entry.get('permission_evidence')
                or not all(entry.get('scope',{}).get(p) is True for p in ('local_storage','search_index','rag_answers'))):continue
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry.get('sha256'):continue
        try:catalog=json.loads(raw)
        except ValueError:continue
        if not isinstance(catalog,dict) or not isinstance(catalog.get('anchors'),list):continue
        if catalog.get('work_id')!=BOOK_ID or not catalog.get('edition_id'):continue
        catalogs.append((entry,catalog))
    return registry,catalogs


def candidate_matches(source, registry, catalogs):
    m=source['metadata'];candidates=[]
    for entry,catalog in catalogs:
        bindings=registry.get('edition_bindings',[])
        if not isinstance(bindings,list):bindings=[]
        binding=next((b for b in bindings if isinstance(b,dict)
                      and b.get('file_sha256')==m['file_sha256']
                      and b.get('catalog_sha256')==entry['sha256']
                      and b.get('edition_id')==catalog['edition_id']
                      and b.get('verified') is True and b.get('reviewed_by') and b.get('evidence')),None)
        anchors=[a for a in catalog.get('anchors',[]) if isinstance(a,dict)
                 and all(isinstance(a.get(k,''),str) for k in ('topic','chapter_title','siman','seif','anchor_id','text','source_url'))]
        locator_counts={}
        id_counts={}
        for anchor in anchors:
            loc=tuple(anchor.get(k,'') for k in ('topic','chapter_title','siman','seif'))
            locator_counts[loc]=locator_counts.get(loc,0)+1
            aid=anchor.get('anchor_id','');id_counts[aid]=id_counts.get(aid,0)+1
        for anchor in anchors:
            if not isinstance(anchor.get('text'),str) or full_text_key(anchor['text'])!=full_text_key(source['text']):continue
            loc=tuple(anchor.get(k,'') for k in ('topic','chapter_title','siman','seif'))
            url=anchor.get('source_url','')
            valid=(binding is not None and all(isinstance(anchor.get(k),str) and anchor[k].strip()
                      for k in ('anchor_id','topic','siman','seif','source_url'))
                   and numeral(anchor['siman']) is not None and numeral(anchor['seif']) is not None
                   and urlsplit(url).scheme=='https'
                   and urlsplit(url).path not in ('','/')
                   and urlsplit(url).hostname in entry.get('approved_hosts',[])
                   and locator_counts[loc]==1 and id_counts.get(anchor.get('anchor_id'))==1)
            ref='{}, {}'.format(TITLE,anchor.get('topic',''))
            if anchor.get('chapter_title'):ref+=', '+anchor['chapter_title']
            ref+=', סימן {}, סעיף {}'.format(anchor.get('siman',''),anchor.get('seif',''))
            candidates.append({'catalog_sha256':entry['sha256'], 'catalog_id':entry['id'],
                'edition_id':catalog['edition_id'],'anchor_id':anchor.get('anchor_id'),
                'resolved_locator':{k:anchor.get(k,'') for k in ('topic','chapter_title','siman','seif')},
                'reference':ref,'source_url':url,
                'anchor_sha256':hashlib.sha256(json.dumps(anchor,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
                'heading_agrees':m.get('heading','')==anchor.get('chapter_title',''),
                'eligible_for_review':bool(valid),
                'match':'exact full visible text; heading agreement is only a retrieval hint',
                'text_sha256':m['text_sha256'], 'file_sha256':m['file_sha256']})
    return candidates


def build_queue(db_path):
    path=Path(db_path).resolve()
    registry,catalogs=trusted_catalogs()
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        sources=[json.loads(r[0]) for r in db.execute('SELECT payload FROM records')]
    from .locator_hierarchy import hierarchy_diagnostics
    hierarchy=hierarchy_diagnostics([s for s in sources if s.get('book_id')==BOOK_ID])
    rows=[]
    for s in sources:
        if s.get('book_id')!=BOOK_ID or s['metadata'].get('locator_status')!='ambiguous-file-fields':continue
        m=s['metadata']
        candidates=candidate_matches(s,registry,catalogs)
        rows.append({'source_id':s['source_id'],'reference_as_supplied':s['reference'],
                     'file_sha256':m['file_sha256'],'text_sha256':m['text_sha256'],
                     'original_rows':m['original_rows'],'heading':m.get('heading',''),
                     'original_locator_fields':m.get('original_locator_fields',[]),
                     'hierarchy_diagnostics':hierarchy.get(s['source_id'],[]),
                     'proposed_locator':None,
                     'admission_rule':'file order and headings cannot authorize a locator; trusted same-edition evidence and review required',
                     'reasons':{'conflict':m['locator_conflict'],'opaque_numbering':m['opaque_numbering']},
                     'candidates':candidates,'status':'needs-human-review' if candidates else 'needs-trusted-same-work-evidence'})
    return {'created_at':utcnow_iso(),'work_id':BOOK_ID,'rows':rows,
            'trusted_catalog_count':len(catalogs),'auto_released':0}


def approve(db_path, source_id, catalog_id, anchor_id, reviewer, note):
    if not reviewer.strip() or not note.strip():raise ValueError('reviewer and review rationale required')
    queue=build_queue(db_path)
    row=next((r for r in queue['rows'] if r['source_id']==source_id),None)
    if not row:raise ValueError('source is not in ambiguous-row queue')
    matches=[c for c in row['candidates'] if c['eligible_for_review']]
    # More than one identity is not resolved by selecting a convenient match.
    identities={(c['edition_id'],c['reference']) for c in matches}
    if len(identities)!=1:raise ValueError('no unique verified same-edition locator')
    chosen=next((c for c in matches if c['catalog_id']==catalog_id and c['anchor_id']==anchor_id),None)
    if not chosen:raise ValueError('selected evidence has not met admission requirements')
    grant=read_json(ROOT/'data/yalkut_parquet_permission.json',{})
    allowed,_=permission_for('user-provided-local-use',{}, {'file':grant},'file')
    if not allowed or grant.get('file_sha256')!=row['file_sha256']:raise ValueError('file permission not current')
    RESOLUTIONS.parent.mkdir(parents=True,exist_ok=True)
    with RESOLUTIONS.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        resolutions=read_json(RESOLUTIONS,{'version':1,'records':{}})
        resolutions['records'][source_id]=dict(chosen,reviewed_by=reviewer,review_note=note,
                                             reviewed_at=utcnow_iso(),status='human-reviewed-locator')
        atomic_json(RESOLUTIONS,resolutions)
    return resolutions['records'][source_id]


def resolved_source(source):
    """Revalidate evidence and permission at retrieval; stale proof stays blocked."""
    if source.get('book_id')!=BOOK_ID:return source
    m=source['metadata']
    grant=read_json(ROOT/'data/yalkut_parquet_permission.json',{})
    allowed,_=permission_for('user-provided-local-use',{}, {'file':grant},'file')
    if not allowed or grant.get('file_sha256')!=m.get('file_sha256'):
        blocked=dict(source);blocked['metadata']=dict(m,rag_answers_allowed=False,
                                                    permission_status='current-permission-review-required')
        return blocked
    records=read_json(RESOLUTIONS,{'records':{}}).get('records',{})
    if not isinstance(records,dict):return source
    stored=records.get(source['source_id'])
    if not isinstance(stored,dict):return source
    if not stored or not all(stored.get(k) for k in ('reviewed_by','review_note','reviewed_at')) or stored.get('status')!='human-reviewed-locator':return source
    if stored.get('file_sha256')!=m.get('file_sha256') or stored.get('text_sha256')!=hashlib.sha256(source['text'].encode()).hexdigest():return source
    registry,catalogs=trusted_catalogs()
    candidates=candidate_matches(source,registry,catalogs)
    valid=[c for c in candidates if c['eligible_for_review']]
    if len({(c['edition_id'],c['reference']) for c in valid})!=1:return source
    if not any(all(c.get(k)==stored.get(k) for k in ('catalog_sha256','anchor_sha256','reference','source_url','anchor_id','edition_id','resolved_locator')) for c in valid):return source
    result=dict(source);result['metadata']=dict(m)
    result.update(reference=stored['reference'],source_url=stored['source_url'],version=stored['edition_id'],
                  verification_status='human-reviewed-locator; content-not-halachically-certified')
    result['metadata'].update(original_reference=source['reference'],locator_status='human-reviewed-catalog-match',
                              rag_answers_allowed=True, locator_resolution=stored,
                              original_locator_conflict=m.get('locator_conflict'),
                              original_opaque_numbering=m.get('opaque_numbering'),
                              locator_conflict=False,opaque_numbering=False,
                              resolved_locator=stored['resolved_locator'],locator_collated_with_catalog=True)
    return result
