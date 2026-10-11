import gzip
import json
import tempfile
from pathlib import Path
import pytest
from kezohar.app_library import sync_library, safe_path
from kezohar.ingest import load_store
from kezohar.hybrid import HybridSearch

LICENSES = {'pd':{'allows_full_text':True, 'scope':dict(local_storage=True,search_index=True,rag_answers=True)}}

@pytest.fixture
def library(tmp_path):
    app=tmp_path/'app'; pack=app/'public/library/packs/p';pack.mkdir(parents=True)
    manifest={'packId':'p','license':'pd','files':[{'workId':'Book','file':'b.json.gz'}]}
    (pack/'manifest.json').write_text(json.dumps(manifest))
    def write(text='שַׁבָּת '*400):
        data={'packId':'p','workId':'Book','editionId':'p:Book','nodes':[{'id':'Book.1','n':1,'units':[{'id':'Book.1.1','n':1,'text':text}]}]}
        with gzip.open(pack/'b.json.gz','wt') as f: json.dump(data,f)
    write()
    cat=app/'src/data/library';cat.mkdir(parents=True)
    (cat/'packIndex.mjs').write_text('export default '+json.dumps([{'packId':'p','works':[{'workId':'Book','heTitle':'ספר בדיקה','authors':['מחבר'],'editionTitle':'מהדורה א','sourceLine':'ייחוס','nodeTitles':['הלכות שבת']}]}])+';')
    with tempfile.TemporaryDirectory(dir=Path.cwd()/'data/store') as out:
        yield app,Path(out),write

def test_sync_chunk_metadata_search_and_noop(library):
    app,out,write=library
    r=sync_library(app,out,LICENSES);assert r['updated_files']==1 and not r['errors']
    sources=load_store(out/'sources.jsonl'); assert len(sources)>1
    assert len({s.source_id for s in sources})==len(sources)
    assert sources[0].author=='מחבר' and sources[0].version=='מהדורה א'
    assert 'הלכות שבת' in sources[0].reference and 'ַ' in sources[0].text
    assert sources[0].attribution=='ייחוס'
    assert HybridSearch(sources).search('שבת')[0]['attribution']=='ייחוס'
    before=(out/'sources.jsonl').read_bytes()
    assert sync_library(app,out,LICENSES)['unchanged_files']==1
    assert (out/'sources.jsonl').read_bytes()==before
    first_id=next(s.source_id for s in sources if s.section=="part1")
    write('טקסט חדש')
    sync_library(app,out,LICENSES)
    updated=load_store(out/'sources.jsonl');assert len(updated)==1 and updated[0].source_id==first_id

def test_revoked_permission_removes_searchable_text(library):
    app,out,_=library;sync_library(app,out,LICENSES)
    report=sync_library(app,out,{})
    assert report['blocked'] and report['sources']==0

def test_verified_scope_grant_and_scope_missing(library):
    app,out,_=library
    grant={'verified':True,'evidence':'owner-record-1','scope':dict(local_storage=True,search_index=True)}
    first = sync_library(app,out,{}, {'p/b.json.gz':grant})
    assert first['sources']>0 and first['pending_scope_review']
    assert load_store(out/'sources.jsonl')[0].metadata['rag_answers_allowed'] is False
    grant['scope']['rag_answers']=True
    assert sync_library(app,out,{}, {'p/b.json.gz':grant})['sources']>0

def test_corrupt_file_removes_stale_text_and_can_resume(library):
    app,out,write=library;sync_library(app,out,LICENSES)
    (app/'public/library/packs/p/b.json.gz').write_bytes(b'broken')
    r=sync_library(app,out,LICENSES);assert r['errors'] and r['sources']==0
    write();assert sync_library(app,out,LICENSES)['sources']>0

def test_removed_file_pruned(library):
    app,out,_=library;sync_library(app,out,LICENSES)
    p=app/'public/library/packs/p/manifest.json';d=json.loads(p.read_text());d['files']=[];p.write_text(json.dumps(d))
    assert sync_library(app,out,LICENSES)['sources']==0

def test_path_escape(tmp_path):
    with pytest.raises(ValueError):safe_path(tmp_path,'../outside')

def test_metadata_only_catalog_summary_ignored(library):
    app,out,_=library
    (app/'src/data/library/summary.mjs').write_text('export default [{"packId":"p","works":1}];')
    assert sync_library(app,out,LICENSES)['sources']>0

def test_explicit_chunk_ids_do_not_collapse(library):
    app,out,_=library;sync_library(app,out,LICENSES)
    sources=load_store(out/'sources.jsonl')
    assert all(len(s.text)<=1500 for s in sources)
    assert len(sources)==len({s.source_id for s in sources})

def test_manifest_checksum_mismatch_blocks_file(library):
    app,out,_=library
    p=app/'public/library/packs/p/manifest.json';d=json.loads(p.read_text());d['files'][0]['checksum']='00000000';p.write_text(json.dumps(d))
    r=sync_library(app,out,LICENSES)
    assert r['sources']==0 and 'checksum' in r['errors'][0]['error']

def test_checksum_utf16():
    from kezohar.app_library import checksum
    assert checksum(b'hello')=='4f9f2cab'
    assert checksum('😀'.encode())=='cb31c4b8'

def test_anchor_sidecar_canonical_reference(library):
    app,out,_=library
    pack=app/'public/library/packs/p';p=pack/'manifest.json';d=json.loads(p.read_text())
    d['files'].append({'workId':'Book','file':'b.anchors.json.gz','role':'anchors'})
    p.write_text(json.dumps(d))
    with gzip.open(pack/'b.anchors.json.gz','wt') as f:
        json.dump({'workId':'Book','anchors':[{'unitId':'Book.1.1','canonicalRef':'Commentary 2:3:1','anchorRef':'Base.2.3'}]},f)
    assert not sync_library(app,out,LICENSES)['errors']
    assert load_store(out/'sources.jsonl')[0].reference_en=='Commentary 2:3:1'
    assert load_store(out/'sources.jsonl')[0].metadata['anchor']['anchorRef']=='Base.2.3'

def test_nullable_node_titles(library):
    app,out,_=library
    cat=app/'src/data/library/packIndex.mjs';cat.write_text('export default [{"packId":"p","works":[{"workId":"Book","nodeTitles":null}]}];')
    assert not sync_library(app,out,LICENSES)['errors']

def test_disk_search_and_federation(library):
    from kezohar.library_search import SQLiteLibrarySearch
    from kezohar.hybrid import FederatedSearch
    app,out,_=library;sync_library(app,out,LICENSES)
    disk=SQLiteLibrarySearch(out/'library.sqlite3')
    found=disk.search('שבת');assert found and found[0]['attribution']=='ייחוס'
    assert not disk.search('" OR *')
    fused=FederatedSearch(HybridSearch([]),[disk]).search('שבת')
    assert fused and fused[0]['reference']==found[0]['reference']

def test_mikra_targum_layers_separate(library):
    app,out,_=library
    pack=app/'public/library/packs/p';p=pack/'manifest.json';m=json.loads(p.read_text());m.pop('license');m.update(mikra={'license':'pd'},targum={'license':'pd'});p.write_text(json.dumps(m))
    with gzip.open(pack/'b.json.gz','rt') as f:d=json.load(f)
    d['nodes'][0]['units'][0]['text']='בראשית';d['nodes'][0]['units'][0]['targum']='בקדמין'
    with gzip.open(pack/'b.json.gz','wt') as f:json.dump(d,f)
    r=sync_library(app,out,LICENSES);assert not r['errors'] and r['sources']==2
    sources=load_store(out/'sources.jsonl');assert {s.language for s in sources}=={'he','arc'}
    assert len({s.source_id for s in sources})==2


def test_incremental_fts_updates_and_revocation(library):
    from kezohar.library_search import SQLiteLibrarySearch
    app,out,write=library;sync_library(app,out,LICENSES);s=SQLiteLibrarySearch(out/'library.sqlite3');assert s.search('שבת')
    write('חנוכה');sync_library(app,out,LICENSES);assert not s.search('שבת') and s.search('חנוכה')
    sync_library(app,out,{});assert not s.search('חנוכה')

def test_api_uses_disk_index_without_loading_library_jsonl(library,monkeypatch):
    from kezohar import api
    app,out,_=library;sync_library(app,out,LICENSES)
    (out/'sources.jsonl').write_text('intentionally not JSON; API must query SQLite')
    monkeypatch.setattr(api,'_agent',None)
    monkeypatch.setenv('STORE_PATH',str(out/'empty-base.jsonl'))
    monkeypatch.setenv('WEB_STORE_PATH',str(out/'empty-web.jsonl'))
    monkeypatch.setenv('APP_LIBRARY_STORE_PATH',str(out/'sources.jsonl'))
    monkeypatch.setenv('APP_LIBRARY_DB_PATH',str(out/'library.sqlite3'))
    assert api.get_agent().search_only('שבת')
    assert api.get_agent().search.bm25.docs==[]

def test_copyright_grant_overrides_license_default(library):
    app,out,_=library
    mp=app/'public/library/packs/p/manifest.json';m=json.loads(mp.read_text());m['license']='RESTRICTED';mp.write_text(json.dumps(m))
    grant={'verified':True,'evidence':'documented-owner-permission','scope':dict(local_storage=True,search_index=True,rag_answers=True)}
    report=sync_library(app,out,{'RESTRICTED':{'allows_full_text':False}}, {'p/b.json.gz':grant})
    assert report['sources']>0 and not report['blocked'] and not report['errors']


def test_declared_app_permission_is_reported_without_inventing_rag_scope(library,monkeypatch):
    app,out,_=library
    report=sync_library(app,out,{})
    assert report['pending_scope_review'][0]['status']=='pending-scope-review'
    assert 'זכויות יוצרים כשלעצמן אינן עילת חסימה' in report['blocked'][0]['permission']['reason']
    assert report['owner_declaration']=='app-owner-existing-library-2026-10-11'
