"""Public failure reasons with no rejected model prose or private source text."""

MESSAGES={
    'no_relevant_source':'לא נמצא מקור רלוונטי במקורות שנשלפו.',
    'insufficient_evidence':'נמצאו מקורות, אך לא הוכחה בהם המסקנה המבוקשת.',
    'rule_needs_details':'הכלל במקור מוצג, אך חסר פרט להחלתו על המקרה.',
    'unsupported_claim':'המודל יצר ניסוח שלא הוכחה תמיכתו במקור.',
    'quotation_mismatch':'הציטוט שונה מהמקור או הושמט חלק מהיחידה הנדרשת.',
    'source_identity_or_permission':'זהות המקור, מהדורתו או הרשאתו דורשות בירור.',
    'technical_error':'התרחשה תקלה טכנית; לא ניתנה תשובה מאומתת.',
    'source_rule':'הוצג הסבר תחום למקור; אין בכך אישור הלכתי למקרה.',
    'source_reading':'אומתה קריאת מקור; התאמתו למקרה דורשת בדיקה.',
}

def describe(result):
    v=result.get('verification',{})
    verdict=result.get('verdict',v.get('verdict',''))
    reason=v.get('support','')
    code=verdict;stage='verification'
    if verdict=='rule_needs_clarification':category='rule_needs_details';stage='case-intake'
    elif verdict in ('technical_error','sources-only','budget_exhausted','partial_search'):
        category='technical_error';stage='retrieval' if verdict=='partial_search' else 'generation'
        code=result.get('technical_error',{}).get('code',verdict)
    elif verdict=='no_source':category='insufficient_evidence' if result.get('sources') else 'no_relevant_source'
    elif verdict in ('rag-scope-pending','invalid_citation'):
        category='source_identity_or_permission'
    elif verdict=='irrelevant':category='no_relevant_source'
    elif verdict in ('insufficient_context','review_required'):
        category='unsupported_claim' if verdict=='review_required' else 'insufficient_evidence'
    elif verdict=='unsupported' and reason in ('quote-text-mismatch','incomplete-quote-unit','quote not present in cited excerpt'):
        category='quotation_mismatch';code=reason
    elif verdict=='format_error' or reason=='invalid quotation JSON':category='technical_error';code='model_response_format'
    elif verdict in ('unsupported','contradicted'):category='unsupported_claim';code=reason or verdict
    elif result.get('known_rule_context',{}).get('rules'):category='source_rule'
    elif verdict=='ok':category='source_reading'
    else:return {'category':verdict or 'not-approved','code':code,'stage':'routing',
                 'message':result.get('answer',''),'halachic_verified':False}
    return {'category':category,'code':code,'stage':stage,'message':MESSAGES[category],
            'diagnostic_reason':reason,'halachic_verified':False}
