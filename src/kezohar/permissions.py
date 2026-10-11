"""Explicit purpose-scoped permissions; declarations alone never authorize RAG."""
PURPOSES = ('local_storage', 'search_index', 'rag_answers')

def permission_for(license_id, licenses, grants=None, resource=''):
    entry = licenses.get(license_id, {})
    grant = (grants or {}).get(resource, {})
    if (grant.get('verified') is True and grant.get('evidence')
            and all(grant.get('scope', {}).get(p) is True for p in PURPOSES)):
        return True, grant
    if (entry.get('allows_full_text') is True and entry.get('app_enabled', True)
            and all(entry.get('scope', {}).get(p) is True for p in PURPOSES)):
        return True, entry
    return False, {'status': entry.get('status', 'unknown'),
                   'reason': 'היקף שמירה, אינדוקס ויצירת תשובות אינו מאומת'}
