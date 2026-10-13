"""Security identity shared by retrieval, verification, cache and display."""
import hashlib
import json
from .permissions import rag_eligible
from .models import Source

FIELDS = tuple(key for key in Source.__dataclass_fields__ if key != 'metadata')

def fingerprint(source):
    # Scores/backend annotations are not identity; all permission and locator
    # metadata is. Conflicting snapshots cannot be resolved by retrieval rank.
    record = {key: source.get(key, '') for key in FIELDS}
    record['metadata'] = source.get('metadata', {})
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def structurally_valid(source):
    return (isinstance(source,dict)
            and all(isinstance(source.get(k,''),str) for k in ('source_id','work_title','reference','text'))
            and isinstance(source.get('metadata',{}),dict))


def admissible(source):
    if isinstance(source,dict) and source.get('source_project')=='verified-web':
        meta=source.get('metadata',{})
        if isinstance(meta,dict) and 'verified_until_epoch' in meta:
            import time
            expires=meta['verified_until_epoch']
            if type(expires) not in (int,float) or not 0<expires-time.time()<=3600:return False
    return (structurally_valid(source) and rag_eligible(source) and bool(source.get('source_id'))
            and bool(source.get('reference')) and not source.get('identity_conflict')
            and source.get('metadata', {}).get('locator_status') != 'ambiguous-file-fields')

def unique_sources(sources):
    index = {}
    for source in sources:
        sid = source.get('source_id')
        if not sid or (sid in index and fingerprint(index[sid]) != fingerprint(source)):
            raise ValueError('conflicting or missing source identity')
        index[sid] = source
    return index

def snapshots(sources):
    return {sid: fingerprint(source) for sid, source in unique_sources(sources).items()}

def complete_quote(quote, source):
    # A substring is allowed only after independent contextual review pinned to
    # the full current snapshot. Literal overlap never establishes completeness.
    from .quotation_units import reviewed_complete_quote
    return bool(quote.strip()) and (quote == source.get('text', '').strip()
                                   or reviewed_complete_quote(quote, source))

def public_sources(sources):
    result=[]
    for source in sources:
        if admissible(source):result.append(dict(source))
        else:
            # Search permissions never imply permission to expose full text.
            result.append({k:source.get(k,'') for k in ('source_id','work_title','reference')})
            result[-1].update(permission_status='blocked-or-review-required',text='')
            if isinstance(source,dict) and source.get('source_project')=='verified-web':
                from .torah_web import canonical_url
                try:url=canonical_url(source.get('source_url',''))
                except ValueError:url=''
                except Exception:url=''
                result[-1].update(source_project='verified-web',source_url=url,
                    metadata={'site_name':source.get('metadata',{}).get('site_name',''),
                              'rag_answers_allowed':False,'rights_mode':'scope-review-required'})
    return result
