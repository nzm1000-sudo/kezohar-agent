"""The food camera's corrections queue: list readers' corrections not yet decided; approve or reject them.

Usage: review_corrections.py                       — the pending pairs, most frequent first
       review_corrections.py approve "X" "Y"        — "X" was in fact "Y": the camera is taught it
       review_corrections.py reject "X" "Y"
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from kezohar.food_vision import pending_corrections

STORE = ROOT / 'data/store/food-corrections.json'
data = json.loads(STORE.read_text()) if STORE.exists() else {'approved': [], 'rejected': []}
decided = {tuple(p) for p in data['approved'] + data['rejected']}
if len(sys.argv) == 4 and sys.argv[1] in ('approve', 'reject'):
    pair = [sys.argv[2], sys.argv[3]]
    data['approved' if sys.argv[1] == 'approve' else 'rejected'].append(pair)
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(sys.argv[1] + 'd:', pair)
else:
    for (named, chosen), n in pending_corrections().most_common():
        if (named, chosen) not in decided:
            print(f'{n}× זוהה «{named}» — נכון «{chosen}»')
