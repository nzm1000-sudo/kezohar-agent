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


def test_all_frozen_artifacts_match_manifest_and_new_calls_are_replayable():
    manifest=json.loads(Path('bench/frozen/manifest.json').read_text())
    for name,digest in manifest.items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest
    for version in ('v3','v4'):
        dataset=json.loads(Path('bench/frozen/halacha_2026-10-11-'+version+'.json').read_text())
        assert len(dataset['questions'])==20 and dataset['finished_at']
        for row in dataset['questions']:
            if row['qwen_called']:
                assert row['frozen_messages']==row['qwen_calls'][0]['messages']
                assert row['raw_qwen_answer']==row['qwen_calls'][0]['answer']
                a=replay_request(dataset,row,'model-a');b=replay_request(dataset,row,'model-b')
                a.pop('model');b.pop('model')
                assert a==b
            else:
                assert replay_request(dataset,row,'model-a') is None


def test_final_verifier_preserves_every_live_v4_verdict_and_review_requirement():
    from kezohar.verification import ExtractiveSourceVerifier
    dataset=json.loads(Path('bench/frozen/halacha_2026-10-11-v4.json').read_text())
    verifier=ExtractiveSourceVerifier()
    for row in dataset['questions']:
        if not row['qwen_called']:continue
        sources=[s for s in row['selected_sources'] if s['source_id'] in row['qwen_source_ids']]
        result=verifier.verify(row['question'],row['raw_qwen_answer'],sources)
        assert result['verdict']==row['verification']['verdict']
        if result['verdict']=='ok':
            assert result['human_review']=='required' and result['halachic_verified'] is False
