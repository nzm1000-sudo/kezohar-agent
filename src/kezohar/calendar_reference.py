"""Optional external calculation comparison for the fixed public city Netivot.

No question, personal coordinates, or conversation is sent. This is numerical
comparison, never a halachic approval; incompatible methods are not compared.
"""
import datetime,urllib.parse,math
from .fastpath import DEFAULT_LAT,DEFAULT_LON,zmanim
from .torah_web import PublicApiTransport,ResearchError

DOC='https://www.hebcal.com/home/1663/zmanim-halachic-times-api'

def compare_netivot(date,transport=None,budget=None):
    if type(date) is not datetime.date:raise ValueError('date required')
    url='https://www.hebcal.com/zmanim?'+urllib.parse.urlencode({'cfg':'json','latitude':DEFAULT_LAT,
        'longitude':DEFAULT_LON,'tzid':'Asia/Jerusalem','date':date.isoformat()})
    data=(transport or PublicApiTransport(max_requests=1)).json(url,request_budget=budget)
    location=data.get('location',{})
    if data.get('date')!=date.isoformat() or location.get('tzid')!='Asia/Jerusalem':raise ResearchError('calendar identity mismatch')
    if any(type(location.get(k)) not in (int,float) or not math.isfinite(location[k]) or abs(location[k]-v)>0.001
           for k,v in [('latitude',DEFAULT_LAT),('longitude',DEFAULT_LON)]):raise ResearchError('calendar location mismatch')
    local=zmanim(date);rows=[]
    for a,b in [('sunrise','sunrise'),('sunset','sunset'),('sof_shma','sofZmanShma'),
                ('sof_tefila','sofZmanTfilla'),('tzeit','tzeit42min')]:
        raw=data.get('times',{}).get(b)
        if not isinstance(raw,str):raise ResearchError('calendar time missing')
        observed=datetime.datetime.fromisoformat(raw)
        if observed.date()!=date or observed.utcoffset()!=datetime.timedelta(hours=local['tz_offset']):raise ResearchError('calendar timestamp mismatch')
        hh,mm=map(int,local[a].split(':'));delta=(hh*60+mm)-(observed.hour*60+observed.minute)
        rows.append({'field':a,'local':local[a],'external':raw,'difference_minutes':delta})
    return {'date':date.isoformat(),'location':'Netivot','method_reference':DOC,'data_url':url,
        'comparison':rows,'halachic_verified':False,'automatic_method_selection':False,
        'not_compared':['alot_hashachar: local fixed 72 minutes versus API 16.1 degrees']}
