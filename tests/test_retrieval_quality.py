from kezohar.agent import order_sources
from kezohar.ranking import retrieval_query
from kezohar.source_quality import classify
from kezohar.web_research import FreeSearch


def test_meat_milk_distraction_cannot_answer_meal_blessing_time():
    distractor={'source_id':'wrong','work_title':'שולחן ערוך','text':'אכל בשר ימתין שש שעות אף אם בירך ברכת המזון','score':100}
    direct={'source_id':'right','work_title':'שולחן ערוך','text':'ברכת המזון כל זמן שאינו רעב מחמת אותה אכילה','score':1}
    assert [s['source_id'] for s in order_sources([distractor,direct],'עד מתי אפשר לברך ברכת המזון?')]==['right']


def test_travel_obligation_alone_is_not_timing_evidence():
    obligation={'source_id':'wrong','work_title':'ערוך השולחן','text':'תפילת הדרך מחויב לומר בכל סוג נסיעה'}
    timing={'source_id':'right','work_title':'שולחן ערוך','text':'תפילת הדרך אומר אחר שהחזיק בדרך בפרסה ראשונה'}
    assert [s['source_id'] for s in order_sources([obligation,timing],'מתי אומרים תפילת הדרך בנסיעה?')]==['right']
    assert 'פרסה' in retrieval_query('מתי אומרים תפילת הדרך?')


def test_yomtov_and_meal_yaaleh_are_not_shachrit_case():
    q='שכחתי יעלה ויבוא בשחרית של ראש חודש'
    wrong=[{'work_title':'שולחן ערוך','text':'בשחרית ביום טוב אומר יעלה ויבוא בתפילה'},
           {'work_title':'שולחן ערוך','text':'בברכת המזון של ראש חודש אומר יעלה ויבוא'}]
    assert not order_sources(wrong,q)


def test_talmud_page_is_torah_text_not_assigned_psak_authority():
    c=classify({'work_title':'ברכות לז א – ויקיטקסט'})
    assert c['domain']=='torah-study' and c['halachic_authority']=='unclassified'


def test_search_failure_trace_separates_missing_searx_and_challenge(monkeypatch):
    import json
    import kezohar.web_research as web
    monkeypatch.setattr(web.PublicFetcher,'_read',lambda *a:('<html>captcha challenge</html>','https://html.duckduckgo.com/'))
    monkeypatch.setattr(web,'public_url',lambda url,*a:url)
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,*a):return json.dumps({'query':{'search':[{'title':'שולחן ערוך'}]}}).encode()
    class Opener:
        def open(self,*a,**k):return Response()
    monkeypatch.setattr(web.urllib.request,'build_opener',lambda *a:Opener())
    s=FreeSearch();assert s.search('ברכת אורז')
    assert s.last_attempts==[{'backend':'searxng','status':'not-configured'},
                            {'backend':'duckduckgo-html','status':'challenge-page'},
                            {'backend':'wikisource-api-fallback','status':'results','count':1}]
