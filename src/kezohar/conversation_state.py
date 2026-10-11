"""Local bounded conversation state. It is user input, never source evidence.

This is a service-layer interface, not a public authentication scheme. A trusted
caller supplies its authenticated owner key on every read/write/delete. HTTP
exposure is deliberately deferred until that caller identity exists.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
from .hebrew import normalize
from .question_understanding import analyze
from . import fastpath

ROOT=Path(__file__).resolve().parents[2]
CASE_QUESTIONS={
    'shared-oil': 'האם צריך להמתין אחרי צ׳יפס שטוגן בשמן בעקבות טיגון שניצלים?',
    'rice': 'מה מברכים על אורז?',
    'yaaleh-shachrit': 'שכחתי יעלה ויבוא בשחרית של ראש חודש, מה הדין?',
    'travel': 'מתי אומרים תפילת הדרך?',
    'phone-shabbat': 'האם מותר לטלטל טלפון בשבת?',
    'water-urn': 'האם מותר להוסיף מים למיחם בשבת?',
}


class ConversationConflict(ValueError):
    pass


class ConversationStore:
    def __init__(self, path=None, max_turns=12, max_chars=12000):
        self.path=Path(path or ROOT/'data/store/conversations/state.sqlite3').resolve()
        if ROOT not in self.path.parents: raise ValueError('conversation data must remain in project')
        if not 1<=max_turns<=50 or not 2000<=max_chars<=50000:raise ValueError('invalid memory limits')
        self.max_turns=max_turns; self.max_chars=max_chars
        self.path.parent.mkdir(parents=True,exist_ok=True)
        os.chmod(self.path.parent,0o700)
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, owner TEXT NOT NULL, revision INTEGER NOT NULL, state TEXT NOT NULL)')
        os.chmod(self.path,0o600)

    def _db(self):
        return sqlite3.connect(str(self.path),timeout=5)

    @staticmethod
    def _owner(owner):
        if not isinstance(owner,str) or not owner.strip() or len(owner)>256:raise ValueError('trusted owner key required')
        return hashlib.sha256(owner.encode()).hexdigest()

    def create(self, owner):
        cid=secrets.token_hex(24)
        state={'root_question':None,'intent':None,'user_facts':{},'system_hypotheses':[], 'turns':[]}
        with self._db() as db:
            db.execute('INSERT INTO conversations VALUES (?,?,0,?)',(cid,self._owner(owner),json.dumps(state,ensure_ascii=False)))
        return cid

    def load(self, owner, conversation_id):
        with self._db() as db:
            row=db.execute('SELECT revision,state FROM conversations WHERE id=? AND owner=?',
                           (conversation_id,self._owner(owner))).fetchone()
        if not row:raise KeyError('conversation unavailable')
        return row[0],json.loads(row[1])

    def save(self, owner, conversation_id, revision, state):
        state=dict(state)
        turns=list(state['turns'])[-self.max_turns:]
        state['turns']=turns
        # Prune whole turns. Never truncate the case or a stored user fact.
        while len(json.dumps(state,ensure_ascii=False))>self.max_chars and turns:
            turns.pop(0)
        if len(json.dumps(state,ensure_ascii=False))>self.max_chars:
            raise ValueError('case exceeds conversation context limit')
        with self._db() as db:
            changed=db.execute('UPDATE conversations SET state=?,revision=revision+1 WHERE id=? AND owner=? AND revision=?',
                (json.dumps(state,ensure_ascii=False),conversation_id,self._owner(owner),revision)).rowcount
            if changed!=1:raise ConversationConflict('conversation changed; do not overwrite concurrent turn')

    def delete(self, owner, conversation_id):
        with self._db() as db:
            return db.execute('DELETE FROM conversations WHERE id=? AND owner=?',
                              (conversation_id,self._owner(owner))).rowcount==1

    def turn(self, agent, owner, conversation_id, question, circumstances=None, **kwargs):
        if not isinstance(question,str) or not question.strip() or len(question)>2000:
            raise ValueError('question must contain 1 to 2000 characters')
        revision,state=self.load(owner,conversation_id)
        incoming=analyze(question,circumstances)
        q=normalize(question)
        followup=bool(state['root_question']) and (q.startswith(('ואמ','ומה','אז','בעצמ','תיקונ','לא ','והאמ'))
                                                  or incoming['intent']=='general-halacha')
        if fastpath.is_out_of_scope(question):
            return agent.converse(question,**kwargs)
        if followup:
            facts=dict(state['user_facts'])
            # Only a tightly scoped explicit phrase changes this circumstance;
            # residues never turn the case into an automatic waiting obligation.
            if state['intent']=='shared-oil' and 'פירור' in q and 'שמנ' in q:
                if 'לא נשארו' in q or 'בלי פירור' in q:facts['oil_residue']='absent'
                elif 'נשארו' in q or 'יש פירור' in q:facts['oil_residue']='present'
            if circumstances:
                facts.update(circumstances)
            effective=CASE_QUESTIONS.get(state['intent'])
            # Free-form follow-ups cannot silently add a condition outside the
            # bounded slot vocabulary. Preserve the input and ask for a full case.
            recognized=(circumstances or (state['intent']=='shared-oil' and 'oil_residue' in facts
                         and 'פירור' in q and 'שמנ' in q))
            if not effective or not recognized:
                result={'answer':'נא לנסח את המקרה המלא או לבחור נסיבה להמשך; אין להסיק פרט מהזיכרון בלבד.',
                        'mode':'clarification','verdict':'needs_clarification','sources':[],
                        'human_review':'required','halachic_verified':False}
            else:
                # Neutral case text avoids retaining a contradicted older fact
                # inside the model prompt. The original wording remains in audit.
                result=agent.converse(effective,circumstances=facts,**kwargs)
                state['user_facts']=facts
        else:
            result=agent.converse(question,circumstances=circumstances,**kwargs)
            state['root_question']=question
            state['intent']=incoming['intent']
            # Default tradition is a system preference, not a fact the user gave.
            state['user_facts']={k:v for k,v in incoming['circumstances'].items() if k!='tradition'}
            if circumstances and 'tradition' in circumstances:
                state['user_facts']['tradition']=circumstances['tradition']
            elif 'אשכנז' in q or 'ספרד' in q or 'השוואת מסורות' in q:
                state['user_facts']['tradition']=incoming['circumstances']['tradition']
            state['system_hypotheses']=incoming.get('query_hypotheses',[])
        state['turns'].append({'question':question,'explicit_updates':circumstances or {},
                              'user_facts_snapshot':dict(state['user_facts']),
                              'verdict':result.get('verdict')})
        self.save(owner,conversation_id,revision,state)
        result=dict(result)
        result['conversation']={'id':conversation_id,'revision':revision+1,'followup':followup,
                                'memory_is_evidence':False,'original_turn':question}
        return result
