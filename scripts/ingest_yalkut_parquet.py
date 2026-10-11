"""Import an explicitly authorized local attachment; never execute its content."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from kezohar.parquet_library import sync_parquet

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('input')
    p.add_argument('--output', default='data/store/user-library')
    p.add_argument('--permission', default='data/yalkut_parquet_permission.json')
    args = p.parse_args()
    grant = json.loads((ROOT/args.permission).read_text())
    report = sync_parquet(args.input, ROOT/args.output, grant)
    print(json.dumps({k:v for k,v in report.items() if k not in
                     ('header_rows','invalid_rows','locator_conflicts','opaque_locators')},
                     ensure_ascii=False, indent=2))
