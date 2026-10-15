"""Bounded complementary search routes using existing indexes, no new corpus."""
from .ranking import retrieval_query,topic_tokens,RetrievalQuery
from .understanding import understand

ACTION_TERMS={
    'bless':['מברך','ברכתו'], 'eat':['אכילה','אוכל'],
    'wear-tefillin':['הנחת תפילין','מניח תפילין'],
    'remove-tefillin':['חליצת תפילין','חולץ'],
    'speak':['דיבור','להפסיק','שואל','משיב'],
    'heat':['בישול','חזרה'], 'immerse':['טבילת','להטביל'],
    'light':['הדלקת','נר'], 'pray':['תפלת','תפילה'],
}

def plan(question,deep=False):
    core=question.split('\n')[0];structure=understand(core)
    actions=list(dict.fromkeys(a['kind'] for c in structure['clauses'] for a in c['actions']))
    terms=list(dict.fromkeys(w for action in actions for w in ACTION_TERMS[action]))[:10]
    routes=[{'kind':'concept-lexical','query':retrieval_query(question),'reason':'original subject plus curated vocabulary'}]
    if terms:
        # A complementary OR-oriented query avoids an inflected incidental
        # word excluding an explicit ruling; eligibility remains ORIGINAL-case.
        routes.append({'kind':'action-probe','query':' '.join(topic_tokens(core)+terms),
                       'reason':'requested action, not a neighbouring action'})
    from .discovery import interpret
    hints=interpret(core)
    if hints['reference_hints'] or hints['work_hints']:
        routes.append({'kind':'locator-probe','query':core,'reason':'literal locator/work hints; no inferred numbering'})
    for route in routes:
        # Lexical routes carry expanded vocabulary; dense retrieval embeds the
        # user's own question instead (a word bag drifts, e.g. tefillin->tefilla).
        query=route['query'] if isinstance(route['query'],RetrievalQuery) else RetrievalQuery(route['query'],[])
        query.semantic_text=core;route['query']=query
    return {'routes':routes[:3],'max_routes':3,'deep':deep,'run_fallback_if':'no complete eligible topic match',
            'semantic':'not-activated-without-quality-evidence','original_case':core}
