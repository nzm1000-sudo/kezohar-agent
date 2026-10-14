"""Owner-declared site authorization is administrative, not proof of a claim."""
import json
from pathlib import Path
from urllib.parse import urlsplit

def registry():
    path=Path(__file__).resolve().parents[2]/'config/source_registry.json'
    return json.loads(path.read_text(encoding='utf-8'))

def owner_authorization(url):
    p=urlsplit(url)
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443):return None
    data=registry()
    if data.get('project_use')!='noncommercial':return None
    for name,row in data['sources'].items():
        if row.get('host')!=p.hostname or row.get('authorization')!='owner_confirmed':continue
        if row.get('library_only') and (p.path.startswith(('/sheets/','/api/sheets','/collections/','/topics/','/profile/'))):return None
        return {'status':'owner_confirmed','source_registry_id':name,
                'evidence':row['authorization_basis'],'document_reviewed':False,
                'scope':{'local_storage':True,'search_index':True,'rag_answers':True},
                'use':'noncommercial','attribution_required':True}
    return None
