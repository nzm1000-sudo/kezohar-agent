"""File-order diagnostics, not a mechanism for guessing canonical locators."""
from collections import defaultdict
import re
from .parquet_library import numeral


def hierarchy_diagnostics(sources):
    occurrences=[]
    locator_ids=defaultdict(set)
    for source in sources:
        m=source.get('metadata',{})
        file_id=m.get('file_sha256','')
        key=(file_id,m.get('topic'),m.get('siman'),m.get('seif'))
        locator_ids[key].add(source['source_id'])
        for row in m.get('original_rows',[]):
            occurrences.append((file_id,row,source))
    occurrences.sort(key=lambda item:(item[0],item[1]))
    result=defaultdict(list)
    blocks=defaultdict(list)
    block_id=0
    previous=None
    for i,(file_id,row,source) in enumerate(occurrences):
        m=source['metadata']
        hierarchy=(file_id,m.get('topic',''),m.get('heading',''),m.get('siman',''))
        if previous is None or previous[0]!=hierarchy:
            block_id+=1
            blocks[(file_id,m.get('topic',''),m.get('siman',''))].append(block_id)
        prev=occurrences[i-1][2] if i and occurrences[i-1][0]==file_id else None
        nxt=occurrences[i+1][2] if i+1<len(occurrences) and occurrences[i+1][0]==file_id else None
        prev_num=prev['metadata'].get('seif_number') if prev else None
        current_num=m.get('seif_number')
        same_parent=prev and (prev['metadata'].get('topic'),prev['metadata'].get('heading'),prev['metadata'].get('siman'))==hierarchy[1:]
        ranges=[]
        for label in (m.get('siman',''),m.get('heading','')):
            for match in re.finditer(r'([א-ת\"״׳\']+)\s*[-–—]\s*([א-ת\"״׳\']+)',label):
                a,b=numeral(match.group(1)),numeral(match.group(2))
                ranges.append({'literal':match.group(0),'start_as_written':match.group(1),
                               'end_as_written':match.group(2),'numerals_valid':a is not None and b is not None,
                               'assigns_individual_siman':False})
        def neighbor(s):
            if not s:return None
            return {'source_id':s['source_id'],'reference_as_supplied':s['reference'],
                    'heading':s['metadata'].get('heading',''),
                    'seif_number':s['metadata'].get('seif_number')}
        result[source['source_id']].append({
            'row':row,'heading_path_as_supplied':[m.get('topic',''),m.get('heading','')],
            'block_id_in_file':block_id,'siman_as_supplied':m.get('siman',''),
            'same_locator_source_ids':sorted(locator_ids[(file_id,m.get('topic'),m.get('siman'),m.get('seif'))]),
            'previous':neighbor(prev),'next':neighbor(nxt),
            'seif_reset_or_repeat':bool(same_parent and isinstance(prev_num,int) and isinstance(current_num,int) and current_num<=prev_num),
            'seif_gap':bool(same_parent and isinstance(prev_num,int) and isinstance(current_num,int) and current_num>prev_num+1),
            'range_labels':ranges,'status':'file-structure-hint-only; not verified locator evidence'})
        previous=(hierarchy,row)
    for source in sources:
        m=source.get('metadata',{})
        block_list=blocks[(m.get('file_sha256',''),m.get('topic',''),m.get('siman',''))]
        for item in result[source['source_id']]:
            item['siman_block_count']=len(block_list)
            item['repeated_siman_blocks']=len(block_list)>1
    return dict(result)
