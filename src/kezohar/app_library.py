"""Read-only app pack ingestion. Transactional per-file sync, atomic JSONL export."""
import argparse
import gzip
import fcntl
from dataclasses import replace
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from .hebrew import normalize
from .ingest import chunk_text, load_licenses
from .models import Source, stable_id, utcnow_iso
from .permissions import permission_for

SCHEMA_VERSION = 4
MAX_RAW_BYTES = 128 * 1024 * 1024

def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)

def digest(value):
    return hashlib.sha256(value).hexdigest()

def checksum(raw):
    """App FNV-1a over JavaScript UTF-16 code units (not compressed bytes)."""
    value = 0x811c9dc5
    for char in raw.decode('utf-8'):
        point = ord(char)
        units = [point] if point <= 0xffff else [0xd800 + ((point-0x10000)>>10), 0xdc00 + ((point-0x10000)&1023)]
        for unit in units:
            value = ((value ^ unit) * 0x01000193) & 0xffffffff
    return format(value, '08x')

def safe_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if root not in path.parents:
        raise ValueError('path outside input root')
    return path

def catalog(app_root):
    """Decode generated literal JSON exports only; never execute app JavaScript."""
    result = {}
    base = Path(app_root) / 'src/data/library'
    for path in sorted(base.rglob('*.mjs')):
        text = path.read_text(encoding='utf-8')
        marker = 'export default '
        if marker not in text:
            continue
        try:
            value, _ = json.JSONDecoder().raw_decode(text.split(marker, 1)[1])
        except ValueError:
            continue
        packs = value if isinstance(value, list) else value.get('packs', []) if isinstance(value, dict) else []
        for pack in packs:
            if not isinstance(pack, dict) or 'packId' not in pack:
                continue
            if not isinstance(pack.get('works', []), list):
                continue
            for work in pack.get('works', []):
                result[(pack['packId'], work['workId'])] = work
    return result

def records(data, manifest, work, filename, provenance, anchors=None):
    provenance_hash = digest(encode(provenance).encode())
    wid = data['workId']
    edition = data.get('editionId') or manifest['packId'] + ':' + wid
    title = work.get('heTitle') or work.get('title') or wid
    authors = work.get('authors') or []
    if isinstance(authors, str):
        authors = [authors]
    tradition = work.get('tradition', '')
    # Curated works only; embedded Rema remains identified in the original passage.
    if wid.startswith('Shulchan_Arukh__') or wid in ('Beit_Yosef', 'Ben_Ish_Hai', 'Kaf_HaChayim'):
        tradition = 'sephardi'
    node_titles = work.get('nodeTitles') or []
    node_refs = work.get('nodeRefs') or []
    seen = set()
    for node in data['nodes']:
        n = node['n']
        node_title = node.get('title') or (node_titles[n-1] if isinstance(n, int) and 0 < n <= len(node_titles) else '')
        for unit in node.get('units', []):
            uid = unit['id']
            if uid != '{}.{}.{}'.format(wid, n, unit['n']) or uid in seen:
                raise ValueError('invalid or duplicate unit id: ' + uid)
            seen.add(uid)
            text = unit.get('text', '')
            if not isinstance(text, str):
                raise ValueError('non-string unit text')
            anchor = (anchors or {}).get(uid, {})
            ref_en = anchor.get('canonicalRef') or unit.get('ref') or (node_refs[n-1] + ':' + str(unit['n']) if isinstance(n, int) and 0 < n <= len(node_refs) else '')
            ref = '{} · {} {} · {} {}'.format(title, work.get('nodeLabel') or manifest.get('nodeLabel', 'פרק'),
                    node_title or n, work.get('unitLabel') or manifest.get('unitLabel', 'פסקה'), unit.get('label') or unit['n'])
            if unit.get('reference'):
                ref = unit['reference']
            metadata = {k:work[k] for k in ('title','heTitle','authors','editionTitle','editionHeTitle','provider','providerUrl','versionSource','license','recordedLicense','sourceLine','status') if k in work}
            metadata.update({'pack_id':manifest['packId'], 'edition_id':edition, 'unit_id':uid,
                             'node':{k:v for k,v in node.items() if k!='units'},
                             'unit':{k:v for k,v in unit.items() if k not in ('text','targum')}, 'anchor':anchor,
                             'edition':manifest.get('edition', {}), 'provenance_sha256':provenance_hash,
                             'manifest_license':manifest.get('license'), 'modifications':'חלוקה למקטעים; טקסט המקור נשמר'})
            for i, part in enumerate(chunk_text(text.strip()) or ([''] if unit.get('targum') else []), 1):
                source = Source(source_id=stable_id(edition, uid + '#' + str(i), ''), work_title=title,
                    author='; '.join(authors), reference=ref, reference_en=ref_en, section='part'+str(i),
                    text=part, normalized_text=normalize(part), tradition=tradition,
                    license=work.get('license') or manifest.get('license', ''),
                    source_url=unit.get('url') or work.get('providerUrl') or manifest.get('sourceUrl') or '',
                    version=work.get('editionTitle') or manifest.get('contentVersion', ''),
                    book_id=wid, book_title=title, category=manifest.get('category') or manifest.get('family', ''),
                    source_project='app-library', source_file=filename, authority_level=work.get('authority_level', ''),
                    verification_status='imported-not-claim-verified', provenance=manifest.get('provenance', ''),
                    ingested_at=utcnow_iso(), metadata=metadata,
                    license_url=manifest.get('licenseUrl') or work.get('licenseUrl') or '',
                    attribution=work.get('sourceLine') or provenance.get('attribution') or provenance.get('credit') or
                                '{} · {} · {}'.format(title, '; '.join(authors), manifest.get('source', '')))
                if part:
                    yield source
            if unit.get('targum'):
                for j, targum in enumerate(chunk_text(unit['targum']),1):
                    yield replace(source, source_id=stable_id(edition+':targum',uid+'#'+str(j),''),
                                  work_title=title+' · תרגום אונקלוס', reference=ref+' · תרגום אונקלוס',
                                  reference_en='Onkelos '+wid+' '+str(n)+':'+str(unit['n']),
                                  book_id='Onkelos_'+wid, version=manifest.get('targum',{}).get('versionTitle',source.version),
                                  text=targum, normalized_text=normalize(targum), language='arc', section='part'+str(j))

def _sync_library(app_root, output_dir, licenses=None, grants=None, pack_ids=None):
    app_root, out = Path(app_root).resolve(), Path(output_dir).resolve()
    project = Path(__file__).resolve().parents[2]
    if project not in out.parents or app_root == out or app_root in out.parents:
        raise ValueError('output must be inside agent project, outside app')
    if not (app_root / 'public/library/packs').is_dir():
        raise ValueError('app packs directory missing')
    out.mkdir(parents=True, exist_ok=True)
    licenses = load_licenses() if licenses is None else licenses
    grants = grants or {}
    works = catalog(app_root)
    db = sqlite3.connect(str(out / 'library.sqlite3'))
    db.execute('CREATE TABLE IF NOT EXISTS files (key TEXT PRIMARY KEY, digest TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, file TEXT, payload TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS record_file ON records(file)')
    evidence_path = out / 'provenance.json'
    evidence = json.loads(evidence_path.read_text(encoding='utf-8')) if evidence_path.exists() else {}
    report = {'packs':0, 'updated_files':0, 'unchanged_files':0, 'blocked':[], 'errors':[], 'sources':0}
    active = set()
    scanned = set()
    packs_root = app_root / 'public/library/packs'
    for mp in sorted(packs_root.glob('*/manifest.json')):
        if pack_ids and mp.parent.name not in pack_ids:
            continue
        report['packs'] += 1
        scanned.add(mp.parent.name)
        try:
            manifest = json.loads(mp.read_text(encoding='utf-8'))
            if 'mikra' in manifest and 'targum' in manifest:
                if manifest['mikra'].get('license') == manifest['targum'].get('license'):
                    manifest['license'] = manifest['mikra'].get('license', '')
                    manifest['edition'] = {'mikra':manifest['mikra'], 'targum':manifest['targum']}
                    manifest['family'] = 'tanakh'
                    manifest['layer_schema_version'] = 1
                    manifest['nodeLabel'],manifest['unitLabel'] = 'פרק','פסוק'
            if manifest['packId'] != mp.parent.name:
                raise ValueError('pack id mismatch')
            prov_path = manifest.get('provenance')
            provenance = json.loads(safe_path(app_root, prov_path).read_text(encoding='utf-8')) if prov_path else {}
            evidence[manifest['packId']] = {'manifest':manifest, 'provenance':provenance, 'works':{wid:w for (pid,wid),w in works.items() if pid==manifest['packId']}}
            anchor_maps = {}
            for entry in manifest['files']:
                if entry.get('role') not in ('anchors', 'remote-seif-maps'):
                    continue
                path = safe_path(mp.parent, entry['file'])
                with gzip.open(path, 'rb') as fh:
                    raw_side = fh.read(MAX_RAW_BYTES+1)
                if len(raw_side) > MAX_RAW_BYTES or (entry.get('checksum') and checksum(raw_side) != entry['checksum']):
                    raise ValueError('sidecar integrity failure')
                side = json.loads(raw_side)
                evidence[manifest['packId']].setdefault('sidecars', {})[entry['file']] = side
                if entry.get('role') == 'anchors':
                    anchor_maps.setdefault(entry.get('workId') or side['workId'], {}).update({a['unitId']:a for a in side.get('anchors', [])})
            for entry in manifest['files']:
                if entry.get('role') in ('anchors', 'remote-seif-maps'):
                    continue
                key = mp.parent.name + '/' + entry['file']
                active.add(key)
                try:
                    path = safe_path(mp.parent, entry['file'])
                    wid = entry.get('workId') or entry.get('book') or path.name.split('.json')[0]
                    work = works.get((mp.parent.name, wid), {})
                    license_id = work.get('license') or manifest.get('license', '')
                    allowed, permission = permission_for(license_id, licenses, grants, key)
                    if not allowed:
                        with db:
                            db.execute('DELETE FROM records WHERE file=?', (key,))
                            db.execute('DELETE FROM files WHERE key=?', (key,))
                        report['blocked'].append({'file':key, 'license':license_id, 'permission':permission})
                        continue
                    packed = path.read_bytes()
                    stamp = digest(packed + encode([manifest,work,provenance,permission,SCHEMA_VERSION,anchor_maps.get(wid,{})]).encode())
                    with gzip.open(path, 'rb') as fh:
                        raw = fh.read(MAX_RAW_BYTES+1)
                    if len(raw) > MAX_RAW_BYTES:
                        raise ValueError('decompressed file exceeds limit')
                    if entry.get('bytes') is not None and entry['bytes'] != len(packed):
                        raise ValueError('compressed size mismatch')
                    if entry.get('rawBytes') is not None and entry['rawBytes'] != len(raw):
                        raise ValueError('raw size mismatch')
                    if entry.get('checksum') and checksum(raw) != entry['checksum']:
                        raise ValueError('app checksum mismatch')
                    if entry.get('sha256') and digest(raw) != entry['sha256']:
                        raise ValueError('SHA256 mismatch')
                    old = db.execute('SELECT digest FROM files WHERE key=?', (key,)).fetchone()
                    if old and old[0] == stamp:
                        report['unchanged_files'] += 1
                        continue
                    data = json.loads(raw)
                    if data.get('packId') != manifest['packId'] or data.get('workId') != wid:
                        raise ValueError('file identity mismatch')
                    with db:
                        db.execute('DELETE FROM records WHERE file=?', (key,))
                        for source in records(data, manifest, work, key, provenance, anchor_maps.get(wid)):
                            source.metadata['permission'] = permission
                            source.license_url = source.license_url or licenses.get(license_id, {}).get('url', '')
                            db.execute('INSERT INTO records VALUES (?,?,?)', (source.source_id,key,encode(source.to_dict())))
                        db.execute('INSERT OR REPLACE INTO files VALUES (?,?)', (key,stamp))
                    report['updated_files'] += 1
                except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
                    # Remove stale text from search when integrity cannot be established.
                    with db:
                        db.execute('DELETE FROM records WHERE file=?', (key,))
                        db.execute('DELETE FROM files WHERE key=?', (key,))
                    report['errors'].append({'file':key, 'error':str(exc)})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            report['errors'].append({'file':str(mp.relative_to(app_root)), 'error':str(exc)})
    with db:
        for (key,) in db.execute('SELECT key FROM files').fetchall():
            if key not in active and (not pack_ids or key.split('/')[0] in scanned):
                db.execute('DELETE FROM records WHERE file=?', (key,))
                db.execute('DELETE FROM files WHERE key=?', (key,))
    temporary = out / 'sources.jsonl.tmp'
    with temporary.open('w', encoding='utf-8') as fh:
        for (payload,) in db.execute('SELECT payload FROM records ORDER BY id'):
            fh.write(payload+'\n')
            report['sources'] += 1
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(str(temporary), str(out / 'sources.jsonl'))
    from .library_search import rebuild_fts
    rebuild_fts(db)
    db.close()
    evidence_tmp = out / 'provenance.json.tmp'
    evidence_tmp.write_text(encode(evidence), encoding='utf-8')
    os.replace(str(evidence_tmp), str(out / 'provenance.json'))
    (out / 'report.json').write_text(encode(report), encoding='utf-8')
    return report

def sync_library(app_root, output_dir, licenses=None, grants=None, pack_ids=None):
    out = Path(output_dir).resolve()
    project = Path(__file__).resolve().parents[2]
    if project not in out.parents:
        raise ValueError('output must be inside agent project')
    out.mkdir(parents=True, exist_ok=True)
    with (out / '.sync.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _sync_library(app_root, out, licenses, grants, pack_ids)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--app-root', required=True)
    parser.add_argument('--output-dir', default='data/store/app-library')
    parser.add_argument('--grants')
    parser.add_argument('--pack', action='append')
    args = parser.parse_args()
    grants = json.loads(Path(args.grants).read_text()) if args.grants else {}
    print(encode(sync_library(args.app_root, args.output_dir, grants=grants, pack_ids=args.pack)))
