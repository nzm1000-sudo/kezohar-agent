"""Replay immutable prompts against an already available local model, no retrieval.

Only the request model changes. Does not load models or change LM Studio settings.
Baseline prompts are intentionally the old quotation protocol, for fair comparison.
"""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'src'))
from kezohar import config, llm
from kezohar.verification import ExtractiveSourceVerifier
from scripts.e2e_halacha import write_json


def replay_request(dataset, row, model):
    if not row.get('frozen_messages'):
        return None
    return dict(dataset['request_parameters'], model=model, messages=row['frozen_messages'])


def local_endpoint(settings):
    host=urlsplit(settings.base_url).hostname or ''
    try:
        local=host=='localhost' or ipaddress.ip_address(host).is_private
    except ValueError:
        local=host.endswith('.local')
    return settings.provider=='openai-compatible' and local


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--model',required=True,help='already available local model ID')
    p.add_argument('--output',required=True,help='new JSON artifact inside project')
    p.add_argument('--timeout',type=float,default=90)
    args=p.parse_args()
    output=(ROOT/args.output).resolve()
    if ROOT not in output.parents or output.exists():
        raise ValueError('choose a new artifact inside project')
    settings=config.answer_settings()
    if not local_endpoint(settings):
        raise ValueError('only configured local OpenAI-compatible endpoint permitted')
    ok, models=llm.check_health(settings.base_url)
    if not ok or args.model not in models:
        raise ValueError('model unavailable; no model loading attempted')
    frozen=ROOT/'bench/frozen/halacha_2026-10-11.json'
    dataset=json.loads(frozen.read_text())
    run={'model':args.model,'dataset_sha256':hashlib.sha256(frozen.read_bytes()).hexdigest(),
         'protocol':'frozen baseline messages; model only changes; no new search',
         'human_review':'required','questions':[]}
    output.parent.mkdir(parents=True,exist_ok=True)
    for row in dataset['questions']:
        body=replay_request(dataset,row,args.model)
        result={'number':row['number'],'question':row['question'],
                'source_ids':row['qwen_source_ids'],'raw_answer':None,'human_review':'required'}
        if body is None:
            result.update(status='baseline generation gated; no replay request',elapsed_s=0)
        else:
            started=time.perf_counter()
            try:
                response=llm._post(settings.base_url,'/chat/completions',body,timeout=args.timeout)
                choice=response['choices'][0]
                raw=choice['message']['content'] or ''
                lookup={s['source_id']:s for s in row['selected_sources']}
                sources=[lookup[sid] for sid in row['qwen_source_ids']]
                result.update(raw_answer=raw,finish_reason=choice.get('finish_reason'),
                              usage=response.get('usage',{}),
                              verification=ExtractiveSourceVerifier().verify(row['question'],raw,sources))
            except Exception as exc:
                result['error']=type(exc).__name__
            result['elapsed_s']=round(time.perf_counter()-started,3)
        run['questions'].append(result)
        write_json(output,run)
        print(json.dumps({'number':row['number'],'elapsed_s':result['elapsed_s'],
                          'verdict':result.get('verification',{}).get('verdict')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
