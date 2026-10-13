// Extends the existing local demonstration; history exists only in this tab.
let turnHistory=[],lastResponse=null,activeRequest=null;
const controls=document.createElement('div');controls.className='row';
controls.innerHTML='<label>מצב מענה<select id="studyMode"><option value="normal">מענה רגיל — מקור ציבורי לפי הצורך</option><option value="hybrid">חיפוש משולב — גם באינטרנט</option><option value="deep">עיון מעמיק — מקומי ואינטרנט</option></select></label><label><input type="checkbox" id="followup"> המשך המקרה הקודם</label><button type="button" id="newCase">מקרה חדש · נקה שיחה זמנית</button><button type="button" id="cancelRequest" disabled>בטל בקשה</button>';
$('form').append(controls);
const privacy=document.createElement('p');privacy.className='muted';privacy.textContent='כשנדרש מקור מהאינטרנט נשלחים רק שמות אישים ציבוריים ומונחי נושא רשומים. השאלה והיסטוריית השיחה אינן נשלחות. אתרים שהרשאותיהם טרם נבדקו אינם נקראים אוטומטית.';$('form').append(privacy);
const analysisBox=document.createElement('details');analysisBox.id='analysisBox';
analysisBox.append(document.createElement('summary'));analysisBox.firstChild.textContent='תיק עיון: הבנת המקרה, תנאים והפניות';
const analysisBody=document.createElement('div');analysisBox.append(analysisBody);$('result').append(analysisBox);
const review=document.createElement('div');review.className='row';
review.innerHTML='<label>סמן בעיה לבדיקה<select id="feedbackIssue"><option value="source-mismatch">מקור לא מתאים</option><option value="missing-condition">חסר תנאי</option><option value="unclear-answer">תשובה לא ברורה</option><option value="unnecessary-clarification">הבהרה מיותרת</option><option value="citation-problem">בעיה בציטוט</option></select></label><button type="button" id="sendFeedback">שמור משוב אנונימי מקומי</button><span id="feedbackStatus"></span>';
$('result').append(review);
document.querySelector('footer').textContent='אימות תוכנה אינו אישור הלכתי. היסטוריית השיחה זמנית בחלון זה בלבד; רענון מנקה אותה. המשוב שומר סוג בעיה, מזהי מקור וגיבוב תשובה בלבד. אין פרסום או שמירת שאלות ומשוב אישי.';
function clearConversation(){turnHistory=[];lastResponse=null;facts={};ruleAnswers={};currentQuestion='';$('followup').checked=false;$('result').hidden=true;$('question').value='';$('answer').textContent='';$('sources').replaceChildren();analysisBody.replaceChildren();$('sourceText').textContent='';if($('sourceDialog').open)$('sourceDialog').close()}
$('newCase').onclick=()=>{if(!busy)clearConversation()};
$('samples').addEventListener('click',()=>{$('followup').checked=false;turnHistory=[]});
for(const question of ['מי היה אבא של משה רבנו?','מי כתב את מסילת ישרים?','מהו ספר יצירה?']){
 const button=document.createElement('button');button.textContent=question;
 button.onclick=()=>{if(busy)return;$('question').value=question;facts={};ruleAnswers={};$('result').hidden=true};$('samples').prepend(button);
}
api('/demo/status').then(d=>{if(d.knowledge_catalog?.public_books){const info=document.createElement('p');info.className='muted';info.textContent=`קטלוג חיפוש: ${d.knowledge_catalog.public_books.toLocaleString('he-IL')} ספרים בספריא · לצד הספרייה המקומית · כל תשובה דורשת מקור מתאים`; $('status').after(info)}}).catch(()=>{});
const previousRender=render;
render=function(d){previousRender(d);lastResponse=d;analysisBody.replaceChildren();$('feedbackStatus').textContent='';
 if(d.verification?.verdict==='ok')$('verdict').textContent='ציטוט אומת בתוכנה · נדרשת בדיקה הלכתית';
 if(d.verdict==='source_lookup')$('verdict').textContent='טקסט מקור לפי מראה מקום · אינו פסק';
 if(d.question_intent?.engine==='jewish-knowledge'){
  $('verdict').textContent=d.fact_verified?'עובדה נתמכת במקור ישיר':d.verdict==='reported_fact'?'קשר מוצהר במקור משני':d.verdict==='partial_knowledge'?'מידע חלקי — השאלה טרם הושלמה':d.verdict==='knowledge_reading'?'קריאת מקור — ללא מסקנה חדשה':'לא נמצאה ראיה ישירה';
  $('verification').textContent=d.fact_verified?'הקשר נבדק במקור ובמהדורה. זו תשובת ידע, לא פסיקה הלכתית.':'התאמת המשמעות דורשת בדיקה; אין להשלים עובדות מזיכרון המודל.';
  const route=document.createElement('p');route.textContent='סוג השאלה: '+d.question_intent.kind+' · תחומים: '+d.question_intent.domains.join(', ')+' · אינטרנט: '+(d.internet_used?'כן':'לא');analysisBody.append(route);
  for(const edge of d.verification?.facts||[]){const p=document.createElement('p');p.textContent=edge.subject+' — '+edge.relation+' — '+edge.object+' ('+edge.reference+')';analysisBody.append(p)}
 }
 for(const box of $('sources').children){const text=box.textContent;const s=(d.sources||[]).find(s=>text.includes(s.reference));if(s?.source_project==='verified-web'||s?.source_project==='jewish-knowledge-web'){
  const meta=document.createElement('p');meta.className='muted';meta.textContent=['מקור אינטרנטי',s.metadata?.site_name,s.author?'ייחוס מוצהר בדף: '+s.author:'המחבר לא זוהה',s.metadata?.published_at,s.metadata?.rag_answers_allowed?'טקסט מורשה; התאמתו למקרה דורשת אימות':'קטע לגילוי בלבד; אינו ראיה לפסק'].filter(Boolean).join(' · ');box.prepend(meta);
  const button=box.querySelector('button');if(button)button.remove();try{const u=new URL(s.source_url);if(u.protocol==='https:'){const a=document.createElement('a');a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';a.textContent='פתח את העמוד המקורי';box.append(a)}}catch(e){}
 }}
 const findings=d.web_findings||[];if(findings.length){const h=document.createElement('h3');h.textContent='מקורות אינטרנטיים שנקראו — בנפרד מהספרייה';$('sources').append(h);
  for(const s of findings){const box=document.createElement('div');box.className='source';const title=document.createElement('strong');title.textContent=[s.metadata?.site_name,s.work_title].filter(Boolean).join(' · ');box.append(title);
   const p=document.createElement('p');p.className='muted';p.textContent=s.metadata?.rag_answers_allowed?'טקסט מורשה שנקרא; אינו בהכרח מקור שנבחר לתשובה':'מטא־דאטה והפניה בלבד; אין הרשאה מתועדת לשימוש בקטע כראיה לפסק';box.append(p);
   try{const u=new URL(s.source_url);if(u.protocol==='https:'){const a=document.createElement('a');a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';a.textContent='פתח מקור אינטרנטי';box.append(a)}}catch(e){}$('sources').append(box)
  }}
 if(d.web_policy){const p=document.createElement('p');p.textContent='מחקר אינטרנטי: '+(d.discovery_backend||'ממשקי אתרים')+' · '+(d.web_policy.requests||0)+' בקשות. קטע אינטרנטי אינו אישור הלכתי.';analysisBody.append(p)}
 const dossier=d.research_dossier||{};analysisBox.open=dossier.study_mode==='deep';
 const intro=document.createElement('p');intro.textContent='זהו תיק מקורות, לא הכרעה אישית. תנאים והפניות הם טקסטים שאותרו; אין הנחה שכל התנאים מזוהים או מתקיימים.';analysisBody.append(intro);
 for(const claim of dossier.claims||[]){const part=document.createElement('details');const title=document.createElement('summary');title.textContent=claim.reference||'מקור';part.append(title);
  const quote=document.createElement('p');quote.style.whiteSpace='pre-wrap';quote.textContent=claim.quote||claim.text||'';part.append(quote);
  const marked=(claim.conditions_and_exceptions||[]).filter(c=>c.condition_markers?.length);for(const c of marked){const p=document.createElement('p');p.textContent='תנאי או סייג בטקסט: '+c.quote;part.append(p)}analysisBody.append(part)}
 for(const mention of dossier.bibliographic_mentions||[]){const p=document.createElement('p');p.textContent='הפניה בטקסט, שעדיין לא נקשרה למקור ולמהדורה: '+mention.quote;analysisBody.append(p)}
 const chain=document.createElement('p');chain.textContent=dossier.reviewed_chains?.length?`שרשראות קשרים שעברו סקירה: ${dossier.reviewed_chains.length}. אינן ראיה אוטומטית לפסק.`:'לא נמצאה שרשרת קשרים שנבדקה בהקשר הזה.';analysisBody.append(chain);
 const parsed=document.createElement('details');const summary=document.createElement('summary');summary.textContent='כיצד הובנה השאלה';parsed.append(summary);
 const txt=document.createElement('p');txt.style.whiteSpace='pre-wrap';txt.textContent=(d.question_analysis?.structure?.clauses||[]).map(c=>c.text+'\n'+c.actions.map(a=>a.text+(a.negated?' — זוהתה שלילה':'')).join(' · ')).join('\n');parsed.append(txt);analysisBody.append(parsed);
};
ask=async function(){if(busy)return;const q=$('question').value.trim();if(!q)return;if(q!==currentQuestion){facts={};ruleAnswers={};currentQuestion=q}
 const token=Array.from(crypto.getRandomValues(new Uint8Array(24)),n=>n.toString(16).padStart(2,'0')).join('');const abort=new AbortController();activeRequest={token,abort};busy=true;$('submit').disabled=true;$('cancelRequest').disabled=false;$('newCase').disabled=true;$('result').hidden=true;$('error').textContent='';
 const deep=$('studyMode').value==='deep',start=performance.now();const timer=setInterval(()=>{$('progress').textContent=`מחפש ומאמת… ${((performance.now()-start)/1000).toFixed(1)} שניות`},200);
 try{const d=await api('/demo/ask',{method:'POST',headers:{'Content-Type':'application/json'},signal:abort.signal,body:JSON.stringify({question:q,circumstances:facts,rule_answers:ruleAnswers,top_k:5,research:$('studyMode').value!=='normal',web_consent:$('studyMode').value!=='normal',study_mode:deep?'deep':'normal',history:$('followup').checked?turnHistory:[],request_token:token})});render(d);
  if(!d.temporary_conversation?.followup)turnHistory=[];
  if(turnHistory.at(-1)!==q)turnHistory.push(q);while(turnHistory.length>8||turnHistory.reduce((n,q)=>n+q.length,0)>6000){if(turnHistory.length>1)turnHistory.splice(1,1);else break}$('followup').checked=true;
 }catch(e){$('error').textContent=e.name==='AbortError'?'הבקשה בוטלה בממשק. הפקה שכבר נשלחה למודל עשויה להסתיים ברקע.':e.message}
 finally{clearInterval(timer);activeRequest=null;busy=false;$('submit').disabled=false;$('cancelRequest').disabled=true;$('newCase').disabled=false;$('progress').textContent=deep?'עיון מקומי עד 90 שניות · אותן הגנות מקור':'עד 45 שניות לבקשה · לפי פסיקת הספרדים'}
};
$('cancelRequest').onclick=async()=>{if(!activeRequest)return;const current=activeRequest;try{await api('/demo/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_token:current.token})})}finally{current.abort.abort()}};
$('sendFeedback').onclick=async()=>{if(!lastResponse)return;try{const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(lastResponse.answer||''));const digest=Array.from(new Uint8Array(bytes),n=>n.toString(16).padStart(2,'0')).join('');await api('/demo/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({issue:$('feedbackIssue').value,source_ids:(lastResponse.structured_answer?.sources||[]).map(s=>s.source_id).slice(0,8),answer_digest:digest})});$('feedbackStatus').textContent='הבעיה נשמרה לבדיקה; אין בכך אישור הלכתי.'}catch(e){$('feedbackStatus').textContent=e.message}};
