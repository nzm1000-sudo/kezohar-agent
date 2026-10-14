"""Deterministic evidence spans; model wording never constructs a quotation."""
import hashlib,re
from .hebrew import strip_niqqud
from .source_snapshot import fingerprint

CONDITION=re.compile(r'\s*(?:ובלבד|אבל|אך|אלא|בתנאי|אם)(?=\s)')

def units(source):
    text=source['text'];spans=[]
    for line in re.finditer(r'[^\n]+',text):
        start,end=line.span()
        while start<end and text[start].isspace():start+=1
        while end>start and text[end-1].isspace():end-=1
        if end-start<=1800:
            if end-start>=8:spans.append([start,end])
        else:
            # Complete sentences only; no arbitrary character slicing.
            for sentence in re.finditer(r'[^.!?]+[.!?](?=\s|$)',text[start:end]):
                a,b=sentence.span();a+=start;b+=start
                while a<b and text[a].isspace():a+=1
                if 8<=b-a<=1800:spans.append([a,b])
    merged=[]
    for start,end in spans:
        if merged and CONDITION.match(strip_niqqud(text[start:end])) and text[merged[-1][1]:start].strip()=='':
            merged[-1][1]=end
        else:merged.append([start,end])
    pin=fingerprint(source);result=[]
    for start,end in merged:
        if not 8<=end-start<=1800:continue
        quote=text[start:end]
        uid='u-'+hashlib.sha256((pin+':'+str(start)+':'+str(end)).encode()).hexdigest()[:16]
        result.append({'unit_id':uid,'text':quote,'start':start,'end':end})
    return result[:48]
