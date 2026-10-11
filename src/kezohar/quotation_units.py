"""Short exact units reviewed outside the model, never inferred from overlap.

The local catalog is trusted configuration. A human must review surrounding
conditions against the FULL source; a model/source metadata cannot approve a unit.
No production approvals are created by this module.
"""
import json
import os
from pathlib import Path


def catalog_data():
    path = Path(os.environ.get('CLAIM_CATALOG_PATH', 'data/claim_reformulations.json'))
    def unique_pairs(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError('duplicate catalog key')
            obj[key] = value
        return obj
    try:
        data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_pairs)
        if not isinstance(data, dict):
            return {}
        if not all(isinstance(data.get(key, []), list) for key in ('rules', 'quotation_units')):
            return {}
        return data
    except (OSError, ValueError, TypeError):
        return {}  # Never reuse an older catalog after an invalid update.


def reviewed_complete_quote(quote, source):
    from .source_snapshot import admissible, fingerprint
    if not admissible(source) or not source.get('version'):
        return False
    units = catalog_data().get('quotation_units', [])
    ids = [u.get('unit_id') for u in units if isinstance(u, dict)]
    for unit in units:
        if not isinstance(unit, dict):
            continue
        review = unit.get('review')
        if (not isinstance(review, dict) or review.get('status') != 'complete-context-reviewed'
                or not all(isinstance(review.get(k), str) and review[k].strip()
                           for k in ('reviewer', 'rationale'))
                or not isinstance(review.get('essential_conditions'), list)
                or not all(isinstance(c, str) and c.strip() for c in review['essential_conditions'])):
            continue
        start, end = unit.get('start'), unit.get('end')
        if (not isinstance(unit.get('unit_id'), str) or not unit['unit_id'].strip()
                or ids.count(unit['unit_id']) != 1
                or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(source.get('text', ''))):
            continue
        if (unit.get('source_id') == source.get('source_id')
                and unit.get('source_snapshot') == fingerprint(source)
                and unit.get('version') == source['version']
                and unit.get('reference') == source.get('reference')
                and unit.get('quote') == quote == source['text'][start:end]):
            return True
    return False
