"""Preserve completed actual runs in Git without a second library/index."""
import gzip, hashlib, json
from pathlib import Path

def main():
    root=Path('data/store/quality-100-2026-10-13')
    out=Path('docs/quality-100-artifacts');out.mkdir(exist_ok=True)
    manifest={'scope':'private local evaluation traces only; not a replicated corpus or index',
              'halachic_verified':False,'human_review':'required','runs':{}}
    for name in ('baseline','improved','refinement'):
        raw=(root/(name+'.jsonl')).read_bytes()
        rows=[json.loads(line) for line in raw.splitlines()]
        if len(rows)!=100 or {r['id'] for r in rows}!=set(range(1,101)):
            raise ValueError('all 100 records required before archiving '+name)
        target=out/(name+'.jsonl.gz')
        target.write_bytes(gzip.compress(raw,mtime=0))
        if gzip.decompress(target.read_bytes())!=raw:raise ValueError('archive changed the original trace')
        manifest['runs'][name]={'records':100,'commits':sorted({r['commit'] for r in rows}),
            'questions_sha256':rows[0]['questions_sha256'],
            'uncompressed_sha256':hashlib.sha256(raw).hexdigest(),
            'archive_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
            'uncompressed_bytes':len(raw),'archive_bytes':target.stat().st_size}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print(json.dumps(manifest,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
