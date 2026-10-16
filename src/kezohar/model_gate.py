"""One active project-owned local model request, across threads/processes.

This limits submissions; it does not claim to cancel inference on a server after
an HTTP timeout. All waiting consumes the caller's original timeout.
"""
import contextlib
import fcntl
import os
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
class ModelBusy(TimeoutError):pass

def _cloud_first():
    # Calls go to the cloud models first (llm._post); they need no local queue. The local model keeps its single
    # slot inside llm._post's local fallback (owner, 2026-10-16: this lock had made every cloud call wait in line).
    from . import config
    return config.get('CLOUD_LLM','1')!='0' and any(config.get(k,'') for k in ('OPENAI_API_KEY','GEMINI_API_KEY','GROQ_API_KEY'))

@contextlib.contextmanager
def model_slot(timeout,path=None,cancel_event=None):
    if timeout<=0:raise ModelBusy('no time remains for a local model request')
    if path is None and _cloud_first():
        yield {'remaining_s':timeout,'queue_s':0.0}
        return
    with local_slot(timeout,path,cancel_event) as slot:
        yield slot

@contextlib.contextmanager
def local_slot(timeout,path=None,cancel_event=None):
    if timeout<=0:raise ModelBusy('no time remains for a local model request')
    deadline=time.monotonic()+timeout;started=time.monotonic()
    path=Path(path) if path is not None else ROOT/'data/store/local-model.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(str(path),os.O_CREAT|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():raise ModelBusy('local request cancelled in queue')
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ModelBusy('local generation slot deadline exceeded')
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:time.sleep(min(0.025,remaining))
        remaining=deadline-time.monotonic()
        if cancel_event is not None and cancel_event.is_set():raise ModelBusy('local request cancelled before submission')
        if remaining<=0:raise ModelBusy('local generation slot deadline exceeded')
        yield {'remaining_s':remaining,'queue_s':time.monotonic()-started}
    finally:
        fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
