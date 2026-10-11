import copy
import hashlib
import json
from pathlib import Path
from scripts.replay_halacha import replay_request


def test_only_model_changes_between_comparison_requests():
    dataset=json.loads(Path('bench/frozen/halacha_2026-10-11.json').read_text())
    before=copy.deepcopy(dataset)
    for row in dataset['questions']:
        a=replay_request(dataset,row,'mock-qwen')
        b=replay_request(dataset,row,'mock-hebatron')
        if a is None:
            assert b is None and not row['qwen_called']
            continue
        assert a.pop('model')=='mock-qwen' and b.pop('model')=='mock-hebatron'
        assert a==b
        assert a['messages']==row['frozen_messages']
    assert dataset==before


def test_original_report_hash_is_unchanged():
    dataset=json.loads(Path('bench/frozen/halacha_2026-10-11.json').read_text())
    report=Path('docs/E2E_HALACHA_2026-10-11.md')
    assert hashlib.sha256(report.read_bytes()).hexdigest()==dataset['original_artifacts_sha256'][str(report)]


def test_all_original_rejected_answers_remain_rejected_by_stricter_verifier():
    from kezohar.verification import ExtractiveSourceVerifier
    dataset=json.loads(Path('bench/frozen/halacha_2026-10-11.json').read_text())
    verifier=ExtractiveSourceVerifier()
    for row in dataset['questions']:
        if not row['qwen_called']:
            assert not verifier.eligible_sources(row['question'],row['selected_sources'])
            continue
        ids=set(row['qwen_source_ids'])
        sources=[s for s in row['selected_sources'] if s['source_id'] in ids]
        v=verifier.verify(row['question'],row['raw_qwen_answer'],sources)
        assert v['verdict']!='ok'
        if row['verification']['verdict']=='no_source':
            assert v['verdict']=='no_source'


def test_source_id_success_is_only_software_success_in_live_v2():
    from kezohar.verification import ExtractiveSourceVerifier
    dataset=json.loads(Path('bench/frozen/halacha_2026-10-11-v2.json').read_text())
    verifier=ExtractiveSourceVerifier()
    passed=0
    for row in dataset['questions']:
        if not row['qwen_called']:
            continue
        ids=set(row['qwen_source_ids'])
        sources=[s for s in row['selected_sources'] if s['source_id'] in ids]
        v=verifier.verify(row['question'],row['raw_qwen_answer'],sources)
        assert v['verdict']==row['verification']['verdict']
        if v['verdict']=='ok':
            passed+=1
            assert not v['halachic_verified'] and v['human_review']=='required'
    assert passed==4 and dataset['summary']['human_halachic_verified']==0
