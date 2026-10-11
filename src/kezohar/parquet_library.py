"""Read-only, audited import of the user-supplied Yalkut Yosef table.

No model is involved in parsing or repairing locators. Conflicting/opaque
locators remain searchable but cannot be supplied to answer generation.
PyArrow is an optional ingestion dependency, not an API runtime dependency.
"""
from collections import Counter, defaultdict
import fcntl
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3

from .hebrew import normalize
from .library_search import rebuild_fts
from .models import Source, stable_id, utcnow_iso
from .permissions import permission_for

TITLE = 'קיצור שולחן ערוך – ילקוט יוסף'
BOOK_ID = 'Kitzur_Shulchan_Arukh_Yalkut_Yosef'
AUTHOR_IDENTITY_URL = 'https://yalkutyosef.co.il/אודות/'
COLUMNS = ('bookname', 'topic', 'siman', 'sek', 'text')
IMPORT_VERSION = 2
MAX_FILE_BYTES = 128 * 1024 * 1024


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('br', 'p', 'div', 'li') and not self.hidden:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1
        if tag in ('p', 'div', 'li') and not self.hidden:
            self.parts.append('\n')

    def handle_data(self, text):
        if not self.hidden:
            self.parts.append(text)


def visible_text(raw):
    parser = VisibleText()
    parser.feed(raw)
    parser.close()
    # Preserve vowels, punctuation and every visible word, including small notes.
    return ''.join(parser.parts).strip()


def numeral(value):
    """Accept canonical Hebrew numerals only; never turn a range into one siman."""
    letters = re.sub(r"[\s'\"׳״]", '', value)
    alphabet = 'אבגדהוזחטיכלמנסעפצקרשת'
    values = list(range(1, 10)) + list(range(10, 100, 10)) + [100, 200, 300, 400]
    lookup = dict(zip(alphabet, values))
    if not letters or any(c not in lookup for c in letters):
        return None
    number = sum(lookup[c] for c in letters)
    if not 1 <= number <= 1000:
        return None
    left = number
    encoded = ''
    for v, c in ((400, 'ת'), (300, 'ש'), (200, 'ר'), (100, 'ק')):
        while left >= v:
            encoded += c
            left -= v
    if left in (15, 16):
        encoded += 'טו' if left == 15 else 'טז'
    else:
        for v in range(90, 0, -10):
            if left >= v:
                encoded += alphabet[values.index(v)]
                left -= v
        if left:
            encoded += alphabet[values.index(left)]
    return number if letters == encoded else None


def read_rows(path):
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError('install project requirements-parquet.txt for ingestion') from exc
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('Parquet input exceeds limit')
    parquet = pq.ParquetFile(path)
    if not set(COLUMNS).issubset(parquet.schema_arrow.names):
        raise ValueError('required Parquet columns missing')
    if len(set(parquet.schema_arrow.names)) != len(parquet.schema_arrow.names):
        raise ValueError('duplicate Parquet column names')
    if parquet.metadata.num_rows > 100000:
        raise ValueError('Parquet row limit exceeded')
    rows = []
    for batch in parquet.iter_batches(batch_size=1024):
        rows.extend(batch.to_pylist())
    # Treat all embedded metadata and text as data, never as instructions/license.
    return rows, {'columns': parquet.schema_arrow.names,
                  'row_groups': parquet.metadata.num_row_groups,
                  'embedded_metadata_keys': [k.decode('utf-8', errors='replace')
                                             for k in (parquet.schema_arrow.metadata or {})]}


def prepare_rows(rows, file_digest, grant):
    groups = defaultdict(list)
    headers, invalid = [], []
    current_heading = ''
    for i, raw in enumerate(rows, 1):
        if any(not isinstance(raw.get(k), str) or not raw[k].strip() for k in COLUMNS):
            invalid.append({'row': i, 'reason': 'missing or non-string field'})
            continue
        if normalize(raw['bookname']) != normalize("קיצור ש''ע ילקוט יוסף"):
            invalid.append({'row': i, 'reason': 'unexpected book identity'})
            continue
        fields = {k: raw[k].strip() for k in COLUMNS}
        text = visible_text(fields['text'])
        if not text or '\ufffd' in text or any(ord(c) < 32 and c not in '\n\r\t' for c in text):
            invalid.append({'row': i, 'reason': 'empty or damaged visible text'})
            continue
        if text.startswith('@'):
            current_heading = text[1:].strip()
            headers.append({'row': i, 'title': current_heading,
                            'siman': fields['siman'], 'seif': fields['sek']})
            continue
        # Geresh/spacing variants must not hide a collision of the same locator.
        labels = [re.sub(r"[\s'\"׳״]", '', fields[k]) if numeral(fields[k]) is not None
                  else fields[k] for k in ('siman', 'sek')]
        key = (fields['topic'], *labels)
        groups[key].append({'row': i, 'fields': fields, 'raw': raw,
                            'text': text, 'heading': current_heading})

    sources = []
    conflicts, opaque = [], []
    duplicates = 0
    text_locations = defaultdict(set)
    for key, entries in groups.items():
        by_text = defaultdict(list)
        for entry in entries:
            by_text[entry['text']].append(entry)
        conflict = len(by_text) > 1
        if conflict:
            conflicts.append({'topic': key[0], 'siman': key[1], 'seif': key[2],
                              'rows': [e['row'] for e in entries],
                              'different_texts': len(by_text)})
        numbers = (numeral(key[1]), numeral(key[2]))
        if None in numbers:
            opaque.append({'topic': key[0], 'siman': key[1], 'seif': key[2],
                           'rows': [e['row'] for e in entries]})
        eligible = not conflict and None not in numbers
        reference = '{}, {}, סימן {}, סעיף {}'.format(TITLE, *key)
        if not eligible:
            reference += ' [המספור כפי שנמסר בקובץ; שיוך דורש בירור]'
        for text, occurrences in by_text.items():
            duplicates += len(occurrences) - 1
            e = occurrences[0]
            text_locations[hashlib.sha256(text.encode()).hexdigest()].add(key)
            # IDs survive row reorder. Different text/locator never overwrites another.
            sid = stable_id(BOOK_ID, json.dumps(key, ensure_ascii=False), text)
            metadata = {'topic': key[0], 'siman': key[1], 'seif': key[2],
                        'siman_number': numbers[0], 'seif_number': numbers[1],
                        'original_rows': [o['row'] for o in occurrences],
                        'original_row_ids': [o['raw'].get('Unnamed: 0') for o in occurrences],
                        'original_locator_fields': [{k:o['raw'][k] for k in ('topic','siman','sek')}
                                                    for o in occurrences],
                        'original_bookname': e['raw']['bookname'],
                        'original_html': [o['raw']['text'] for o in occurrences],
                        'heading': e['heading'], 'file_sha256': file_digest,
                        'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                        'locator_status': 'unique-file-fields' if eligible else 'ambiguous-file-fields',
                        'locator_conflict': conflict, 'opaque_numbering': None in numbers,
                        'locator_independently_collated': False,
                        'rag_answers_allowed': eligible,
                        'permission_evidence': grant['evidence'],
                        'permission_evidence_type': grant.get('evidence_type', ''),
                        'edition_status': 'not supplied in file',
                        'author_identity_url': AUTHOR_IDENTITY_URL,
                        'source_reliability': 'user-file-provenance; no printed-edition collation'}
            sources.append(Source(source_id=sid, work_title=TITLE,
                author='הרב יצחק יוסף', reference=reference, text=text,
                normalized_text=normalize(text), tradition='sephardi',
                license='user-provided-local-use', version='מהדורת הקובץ לא צוינה',
                book_id=BOOK_ID, book_title=TITLE, category='halacha',
                authority_level='sephardi-posek', source_project='user-parquet-library',
                source_file='0000.parquet', ingested_at=utcnow_iso(),
                verification_status='file-fields-validated' if eligible else 'locator-review-required',
                provenance='user-supplied Parquet; sha256:' + file_digest,
                attribution=TITLE + ' — הרב יצחק יוסף; קובץ שסופק בידי המשתמש',
                metadata=metadata).to_dict())
    report = {'input_rows': len(rows), 'header_rows': headers, 'invalid_rows': invalid,
              'exact_duplicate_rows': duplicates, 'locator_conflicts': conflicts,
              'opaque_locators': opaque, 'sources': len(sources),
              'rag_eligible_sources': sum(s['metadata']['rag_answers_allowed'] for s in sources),
              'locator_review_sources': sum(not s['metadata']['rag_answers_allowed'] for s in sources),
              'identical_text_multiple_locators': sum(len(keys) > 1 for keys in text_locations.values()),
              'topics': dict(Counter(s['metadata']['topic'] for s in sources)),
              'whole_seif_preserved': True, 'human_halachic_verified': False}
    return sources, report


def sync_parquet(input_path, output_dir, grant):
    project = Path(__file__).resolve().parents[2]
    out = Path(output_dir).resolve()
    if project not in out.parents:
        raise ValueError('output must remain inside agent project')
    input_path = Path(input_path).resolve()
    raw = input_path.read_bytes() if input_path.stat().st_size <= MAX_FILE_BYTES else None
    if raw is None:
        raise ValueError('Parquet input exceeds limit')
    digest = hashlib.sha256(raw).hexdigest()
    if grant.get('file_sha256') != digest:
        raise ValueError('permission declaration does not identify this file')
    allowed, permission = permission_for('user-provided-local-use', {},
                                         {'parquet-yalkut-yosef': grant}, 'parquet-yalkut-yosef')
    if not allowed:
        raise ValueError('documented permission scope missing')
    rows, schema = read_rows(input_path)
    # Protect against a changed input between fingerprinting and decoding.
    if hashlib.sha256(input_path.read_bytes()).hexdigest() != digest:
        raise ValueError('input changed during audit')
    sources, report = prepare_rows(rows, digest, permission)
    if not sources or any(e['reason'] == 'unexpected book identity' for e in report['invalid_rows']):
        raise ValueError('no valid corpus or unexpected book identity')
    report.update(file_sha256=digest, schema=schema, import_version=IMPORT_VERSION,
                  permission_basis=grant.get('evidence_type', ''),
                  input_modified=False, audited_at=utcnow_iso())
    out.mkdir(parents=True, exist_ok=True)
    stamp = hashlib.sha256(json.dumps([digest, IMPORT_VERSION, grant], sort_keys=True,
                                      ensure_ascii=False).encode()).hexdigest()
    with (out/'import.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with sqlite3.connect(str(out/'library.sqlite3')) as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, file TEXT, payload TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS files (key TEXT PRIMARY KEY, digest TEXT)')
            rebuild_fts(db)
            old = db.execute('SELECT digest FROM files WHERE key=?', (BOOK_ID,)).fetchone()
            report['unchanged'] = bool(old and old[0] == stamp)
            if not report['unchanged']:
                with db:
                    # Replace only this corpus, never app or other books.
                    db.execute('DELETE FROM records WHERE file=?', (BOOK_ID,))
                    db.executemany('INSERT INTO records VALUES (?,?,?)',
                        [(s['source_id'], BOOK_ID, json.dumps(s, ensure_ascii=False)) for s in sources])
                    db.execute('INSERT OR REPLACE INTO files VALUES (?,?)', (BOOK_ID, stamp))
            assert db.execute('SELECT count(*) FROM records WHERE file=?', (BOOK_ID,)).fetchone()[0] == len(sources)
            report['sqlite_integrity'] = db.execute('PRAGMA integrity_check').fetchone()[0]
            if report['sqlite_integrity'] != 'ok':
                raise ValueError('SQLite integrity check failed')
            db.execute("INSERT INTO library_fts(library_fts) VALUES('integrity-check')")
            report['fts_integrity'] = 'passed'
        # Preserve input exactly inside the project; never edit the attachment.
        inputs = out/'input'
        inputs.mkdir(exist_ok=True)
        saved = inputs/(digest+'.parquet')
        if not saved.exists():
            saved.write_bytes(raw)
        elif hashlib.sha256(saved.read_bytes()).hexdigest() != digest:
            raise ValueError('saved input fingerprint mismatch')
        temp = out/'audit.tmp'
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        temp.replace(out/'audit.json')
    return report
