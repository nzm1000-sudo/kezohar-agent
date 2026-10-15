"""Build/resume the dense index for one existing SQLite library.

Usage: build_vector_index.py LIBRARY_DB [--limit N]
Embeddings come from EMBEDDINGS_* settings (local endpoint only). Safe to stop
and rerun: it resumes after the last committed batch.
"""
import argparse
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kezohar import config
from kezohar.embeddings import create_embedding_model
from kezohar.vector_index import build


def main():
    p = argparse.ArgumentParser()
    p.add_argument('library')
    p.add_argument('--limit', type=int)
    p.add_argument('--works-file', help='UTF-8 file, one work_title per line: priority pass')
    a = p.parse_args()
    settings = config.embedding_settings()
    if settings.provider != 'openai-compatible-local':
        raise SystemExit('set EMBEDDINGS_PROVIDER=openai-compatible-local and EMBEDDINGS_* first')
    start = time.perf_counter()
    progress = build(a.library, create_embedding_model(settings), root=config.get('VECTOR_INDEX_DIR', 'data/store/vectors'),
                     limit=a.limit, log=lambda m: print(m, flush=True),
                     works=[l.strip() for l in open(a.works_file, encoding='utf-8') if l.strip()] if a.works_file else None)
    print('done', progress, 'elapsed_s', round(time.perf_counter() - start, 1), flush=True)


if __name__ == '__main__':
    main()
