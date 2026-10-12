"""Purpose-specific permissions; copyright alone is never a denial reason."""
PURPOSES = ('local_storage', 'search_index', 'rag_answers')
INDEX_PURPOSES = ('local_storage', 'search_index')

def permission_for(license_id, licenses, grants=None, resource='', purposes=PURPOSES):
    entry = licenses.get(license_id, {})
    grant = (grants or {}).get(resource, {})
    if (grant.get('verified') is True and grant.get('evidence')
            and all(grant.get('scope', {}).get(p) is True for p in purposes)):
        return True, grant
    if (entry.get('allows_full_text') is True and entry.get('app_enabled', True)
            and all(entry.get('scope', {}).get(p) is True for p in purposes)):
        return True, entry
    return False, {'status': 'scope-review-required',
                   'license_status': entry.get('status', 'unknown'),
                   'required_purposes': list(purposes),
                   'reason': 'היקף ההרשאה לשימושים הנדרשים טרם תועד; זכויות יוצרים כשלעצמן אינן עילת חסימה'}


def rag_eligible(source):
    metadata=source.get('metadata',{})
    return isinstance(metadata,dict) and metadata.get('rag_answers_allowed',True) is True
