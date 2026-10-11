import json
from scripts.compare_halacha_runs import quality_summary, individual_claim_audit


def test_technical_success_is_not_semantic_or_halachic_success():
    rows=[]
    for verdict,support in [('unsupported','not-proved'),('ok','exact-extract-only'),('ok','source-pinned-reformulations')]:
        rows.append({'question':'שאלה','qwen_called':True,'qwen_completed':True,'total_s':3,
                     'verification':{'verdict':verdict,'support':support,'checks':{
                         'format':'passed','source_exists':'passed','reference_identity':'passed'}}})
    s=quality_summary({'questions':rows})
    assert s['technical_identity_and_format_passed']==3
    assert s['bounded_claim_support_passed']==s['quotation_only_passed']==1
    assert s['model_outputs_blocked']==1
    assert s['human_halachic_verified']==0 and s['human_review_required']==3


def test_post_run_audit_inspects_every_claim_without_changing_recorded_verdict():
    row={'question':'מה מברכים על אורז?', 'qwen_source_ids':[], 'selected_sources':[],
         'verification':{'verdict':'review_required'},
         'raw_qwen_answer':json.dumps({'claims':[
             {'source_id':'missing-one','evidence_id':'rice-raw','text':'טענה ראשונה'},
             {'source_id':'missing-two','evidence_id':'rice-cooked','text':'טענה שנייה'}]})}
    audit=individual_claim_audit(row)
    assert len(audit)==2
    assert all(a['post_run_verification']['verdict']=='invalid_citation' for a in audit)
    assert row['verification']=={'verdict':'review_required'}


def test_no_claim_diagnostics_invented_for_quotes_or_invalid_json():
    for raw in ('not JSON','{"quotes":[]}','{"claims":null}'):
        assert individual_claim_audit({'raw_qwen_answer':raw})==[]
