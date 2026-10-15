"""Compare lexical FTS vs dense retrieval on paraphrased questions with known gold.

Retrieval only: a gold hit proves the right unit was found, not answer quality.
Gold IDs come from the earlier embedding probe (data/store/autonomous-evaluation).
"""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kezohar import config
from kezohar.library_search import SQLiteLibrarySearch
from kezohar.vector_index import configured_index, DenseLibrarySearch

GOLD = [
    ('549a142c342ec7c1', ['מה מברכים על פקאן?', 'איזו ברכה לפני אכילת אגוז פקאן?']),
    ('0eae057b287626f7', ['שכחתי לברך ברכת המזון, האם מאוחר מדי?', 'מתי אפשר עדיין לברך אחרי שאכלתי לחם?']),
    ('32ac824faedcec19', ['מותר לדבר בין תפילין של יד לתפילין של ראש?', 'האם אפשר לשוחח באמצע הנחת תפילין?']),
]


def rank(results, gold):
    ids = [r['source_id'] for r in results]
    return ids.index(gold) + 1 if gold in ids else None


def main(db=config.get('USER_LIBRARY_DB_PATH', 'data/store/user-library/library.sqlite3'), k=20):
    library = SQLiteLibrarySearch(db)
    index = configured_index(db)
    if index is None:
        raise SystemExit('no dense index for ' + db)
    dense = DenseLibrarySearch(library, index)
    rows = []
    for gold, queries in GOLD:
        if library.source_by_id(gold) is None:
            rows.append({'gold': gold, 'error': 'gold not in this library'}); continue
        for q in queries:
            t = time.perf_counter(); lex = library.search(q, top_k=k); tl = time.perf_counter() - t
            t = time.perf_counter(); sem = dense.search(q, top_k=k); ts = time.perf_counter() - t
            rows.append({'query': q, 'gold': gold, 'fts_rank': rank(lex, gold), 'dense_rank': rank(sem, gold),
                         'fts_s': round(tl, 3), 'dense_s': round(ts, 3)})
    print(json.dumps({'indexed_units': len(index), 'top_k': k, 'rows': rows}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main(*sys.argv[1:2])
