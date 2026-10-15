"""Run ONLY the synthetic phase-4 contract suite; never production data or I/O.

Use the existing .venv Python. No dependency installation or external service.
The safety guards precede pytest collection and application imports.
"""
import builtins
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.dont_write_bytecode = True
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
RUN = Path(tempfile.mkdtemp(prefix='phase4-', dir=ROOT/'data/store/test-runs'))
os.environ['TMPDIR'] = str(RUN)
tempfile.tempdir = str(RUN)
sys.path.insert(0, str(ROOT/'src'))
os.environ['PHASE4_ISOLATED_RUN'] = str(RUN)
os.environ['ANSWER_GATE'] = '0'  # the relevance gate calls the local model; its own tests inject the model
os.environ['JEWISH_KNOWLEDGE_ROOT']=str(RUN/'jewish-knowledge')
for key in ('STORE_PATH', 'APP_LIBRARY_STORE_PATH', 'WEB_STORE_PATH', 'APP_LIBRARY_DB_PATH',
            'USER_LIBRARY_DB_PATH', 'WEB_PERMISSIONS_PATH', 'CLAIM_CATALOG_PATH'):
    os.environ[key] = str(RUN/(key.lower()+'.json'))
os.environ.update(LLM_BASE_URL='', LLM_PROVIDER='isolated-fixed', LLM_MODEL='fixed-a',
                  EMBEDDINGS_PROVIDER='mock', EMBEDDINGS_MODEL='hash-trigram-v1',
                  EMBEDDINGS_DIMENSIONS='128', EMBEDDINGS_REVISION='1', SOURCE_GRAPH_ENABLED='false')

blocked = []
def deny(*args, **kwargs):
    blocked.append('external I/O blocked')
    raise AssertionError('external I/O forbidden in phase4 isolated tests')

# socketpair is needed by the in-process asyncio event loop; no network sockets
# may connect, bind, listen, send datagrams, resolve DNS or spawn a process.
for name in ('connect', 'connect_ex', 'bind', 'listen', 'sendto', 'sendmsg'):
    if hasattr(socket.socket, name): setattr(socket.socket, name, deny)
socket.getaddrinfo = socket.gethostbyname = socket.gethostbyname_ex = deny
socket.create_connection = deny
subprocess.Popen = os.system = deny
urllib.request.urlopen = urllib.request.OpenerDirector.open = deny

def checked_path(file, mode):
    if isinstance(file, int): return
    p = Path(file).resolve()
    if p.name == '.env':
        raise AssertionError('.env must not be read by tests')
    writing = any(c in str(mode) for c in 'wax+')
    if writing and RUN not in p.parents and p != RUN:
        raise AssertionError('write outside isolated run directory')
    if ROOT/'data' in p.parents and RUN not in p.parents:
        raise AssertionError('production data must not be read by tests')

original_open, original_io_open = builtins.open, io.open
def guarded_open(file, mode='r', *args, **kwargs):
    checked_path(file, mode)
    return original_open(file, mode, *args, **kwargs)
def guarded_io_open(file, mode='r', *args, **kwargs):
    checked_path(file, mode)
    return original_io_open(file, mode, *args, **kwargs)
builtins.open, io.open = guarded_open, guarded_io_open
original_exists = Path.exists
Path.exists = lambda p: False if p.name == '.env' else original_exists(p)
original_connect = sqlite3.connect
def guarded_connect(database, *args, **kwargs):
    if database != ':memory:':
        raw = str(database).removeprefix('file:').split('?')[0]
        checked_path(raw, 'w')
    return original_connect(database, *args, **kwargs)
sqlite3.connect = guarded_connect

import httpx
httpx.HTTPTransport.handle_request = deny
httpx.AsyncHTTPTransport.handle_async_request = deny
from kezohar import llm
llm.ask = llm.check_health = deny

import pytest
class Results:
    def __init__(self): self.rows = []
    def pytest_runtest_logreport(self, report):
        if report.when == 'call' or (report.when == 'setup' and report.outcome != 'passed'):
            self.rows.append({'test': report.nodeid, 'outcome': report.outcome,
                              'duration_s': report.duration,
                              'details': str(report.longrepr) if report.longrepr else ''})

results = Results()
exit_code = pytest.main(['tests/phase4_isolated/test_contracts.py', 'tests/phase4_isolated/test_regressions.py',
                        'tests/phase4_isolated/test_followup_regressions.py',
                        'tests/phase4_isolated/test_dense_index.py',
                        'tests/phase4_isolated/test_answer_gate.py', '-q', '--tb=short',
                        '--log-file='+str(RUN/'pytest.log'),
                        '--basetemp='+str(RUN/'pytest-temp'),
                        '-o', 'cache_dir='+str(RUN/'pytest-cache'),
                        '--junitxml='+str(RUN/'junit.xml')], plugins=[results])
(RUN/'results.json').write_text(json.dumps({'base_commit':'3663235', 'exit_code':exit_code,
    'blocked_external_attempts':len(blocked), 'tests':results.rows}, ensure_ascii=False, indent=2))
print('ISOLATED_REPORT_DIRECTORY='+str(RUN))
sys.exit(exit_code)
