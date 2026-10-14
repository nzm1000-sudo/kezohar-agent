"""Answer identification questions from validated, scope-aware graph evidence."""
from .entity_questions import name

def resolve_identity(engine,route,budget):
    request=route.get('identity_request')
    if not request:return None
    if request['identity_kind']=='children':
        # The current extractor proves the explicit plural "sons" grammar.
        # Parenthood alone does not prove sex or a complete list of daughters.
        if request.get('requested_children')=='daughters':return None
        children=engine.graph.find(request['parent'],'children',lambda sid:engine.resolve(sid,budget))
        children=[e for e in children if e['method']=='explicit-plural-genealogy-inverse']
        if not children:return None
        people=[{'name':e['object'],'father_qualifier':request['parent']} for e in children]
    else:people=request['subjects']
    evidence=[];individuals=[];options=[]
    for person in people:
        qualifier=person['father_qualifier'];subject=person['name']
        scoped=subject+(' בן '+qualifier if qualifier else '')
        found=engine.graph.find(scoped,'father',lambda sid:engine.resolve(sid,budget))
        found+=engine.graph.find(scoped,'parent',lambda sid:engine.resolve(sid,budget))
        options.append(found)
    shared=set.intersection(*[{name(e['object']) for e in edges} for edges in options]) if len(options)>1 else set()
    for person,edges in zip(people,options):
        subject=person['name'];qualifier=person['father_qualifier']
        if len(shared)==1:edges=[e for e in edges if name(e['object']) in shared]
        parents={name(e['object']) for e in edges}
        if len(parents)>1:
            result=engine.result('השם מתאים לכמה אנשים במקורות: '+', '.join(subject+' בן '+p for p in sorted(parents))+'. למי התכוונת?',[],route,budget)
            result.update(verdict='identity_ambiguous',identity_candidates=[{'name':subject,'father':p} for p in sorted(parents)])
            return result
        if not edges:return None
        edge=edges[0];evidence.append(edge);individuals.append((subject,edge['object']))
    # Joint names are not merged into one person. Every requested subject needs proof.
    grouped=len({name(parent) for _,parent in individuals})==1
    explicit_sons=all(e['method'] in ('explicit-plural-genealogy','explicit-ben-lineage') for e in evidence)
    if grouped:
        subjects=' ו'.join(p for p,_ in individuals);parent=individuals[0][1]
        relation=(' היו בני ' if len(individuals)>1 else ' נזכר כבן ') if explicit_sons else (' היו מילדיו של ' if len(individuals)>1 else ' נזכר כאחד מילדיו של ')
        answer=subjects+relation+parent+'.'
        if len(individuals)==1 and not people[0]['father_qualifier']:
            answer='במקור שנמצא מופיע '+subjects+(' בן ' if explicit_sons else ' בקשר הורות עם ')+parent+'. אין בכך הוכחה שאין אדם נוסף בשם זה.'
    else:answer=' '.join('במקור '+parent+' מופיע כאביו של '+subject+'.' for subject,parent in individuals)
    roles=[];places=[]
    for subject,parent in individuals:
        scoped=subject+' בן '+parent
        r=engine.graph.find(scoped,'role',lambda sid:engine.resolve(sid,budget))
        p=engine.graph.find(scoped,'served_at',lambda sid:engine.resolve(sid,budget))
        roles.append(r);places.append(p)
    if all(roles) and all({e['object'] for e in r}<= {'כהנים','כוהנים'} for r in roles):
        answer+=(' הם שירתו ככוהנים' if len(individuals)>1 else ' הוא שירת ככהן')
        evidence.extend(r[0] for r in roles)
        if all(places) and len({p[0]['object'] for p in places})==1:
            place=places[0][0]['object'];answer+=' ב'+('שילה' if place=='שלה' else place)
            evidence.extend(p[0] for p in places)
        answer+='.'
    sources=[]
    for edge in evidence:
        source=engine.resolve(edge['source_id'],budget)
        from .torah_facts import CrossSourceVerification
        if not source or not CrossSourceVerification.fact(edge,source):return None
        if not any(s['source_id']==source['source_id'] for s in sources):sources.append(source)
    answer+=' ('+'; '.join(s['reference'] for s in sources)+').'
    result=engine.result(answer,sources,route,budget,kind='verified-person-identification',facts=evidence)
    result['knowledge_context']={'people':[{'name':s,'parent':p} for s,p in individuals],
                                 'evidence_source_ids':[s['source_id'] for s in sources]}
    result['answer_complete']=True
    return result
