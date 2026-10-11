"""Build evidence queue or record an explicit locator review; never infer numbering."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from kezohar.locator_resolution import build_queue, atomic_json, approve

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=('queue','approve'))
    p.add_argument('--db',default='data/store/user-library/library.sqlite3')
    p.add_argument('--output',default='data/store/user-library/locator-review-queue.json')
    p.add_argument('--source-id');p.add_argument('--catalog-id');p.add_argument('--anchor-id')
    p.add_argument('--reviewer');p.add_argument('--note')
    args=p.parse_args()
    if args.action=='queue':
        queue=build_queue(ROOT/args.db);atomic_json(ROOT/args.output,queue)
        print('Queued',len(queue['rows']),'rows; auto released:',queue['auto_released'])
    else:
        if not all((args.source_id,args.catalog_id,args.anchor_id,args.reviewer,args.note)):
            p.error('explicit evidence identity, reviewer and note are required')
        approve(ROOT/args.db,args.source_id,args.catalog_id,args.anchor_id,args.reviewer,args.note)
        print('Locator review recorded; retrieval revalidates evidence and permission.')
