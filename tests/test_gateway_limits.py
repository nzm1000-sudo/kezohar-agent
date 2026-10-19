"""The public gateway's allowance: per device behind a shared address, a wider address ceiling, the service's day."""
import importlib.util
from pathlib import Path


class Req:
    def __init__(self, ip, device=''):
        self.headers, self.client = {'cf-connecting-ip': ip, 'x-kezohar-device': device}, None


def gateway():
    spec = importlib.util.spec_from_file_location('gw', Path(__file__).resolve().parents[1] / 'scripts/public_gateway.py')
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    return g


def test_devices_behind_one_address_each_have_their_allowance():
    g = gateway()
    g.PER_MINUTE, g.PER_DAY = 100, 3
    assert [g.over(Req('1.1.1.1', 'a' * 32)) for _ in range(4)] == [None, None, None, 'day']
    assert [g.over(Req('1.1.1.1', 'b' * 32)) for _ in range(4)] == [None, None, None, 'day']
    g.ADDRESS_PER_DAY = 6  # six counted from this address already
    assert g.over(Req('1.1.1.1', 'c' * 32)) == 'day'  # the shared address's ceiling
    g.PER_DAY = 2
    assert [g.over(Req('2.2.2.2')) for _ in range(3)] == [None, None, 'day']  # no device id: the address
    g.PER_MINUTE, g.PER_DAY = 1, 100
    assert [g.over(Req('3.3.3.3', 'd' * 32)) for _ in range(2)] == [None, 'minute']
    g.GLOBAL_PER_DAY['ask'] = len(g.served['ask'])
    assert g.over(Req('9.9.9.9', 'e' * 32)) == 'day'  # the whole service's day


def test_repeated_questions_are_answered_from_memory_but_never_timely_or_follow_ups():
    g = gateway()
    calls = []
    g.forward = lambda q, h=None, spoken=False, tradition=None: (calls.append(q), {'mode': 'llm', 'answer': 'x'})[1]
    g.cached_forward('מה מברכים על בננה?'); g.cached_forward('מה מברכים על בננה')
    assert len(calls) == 1
    g.cached_forward('מתי שקיעה היום?'); g.cached_forward('מתי שקיעה היום?')
    assert len(calls) == 3
    g.cached_forward('ולמה?', [{'q': 'a', 'a': 'b'}]); g.cached_forward('ולמה?', [{'q': 'a', 'a': 'b'}])
    assert len(calls) == 5


def test_an_ashkenazi_reader_never_gets_the_sephardi_answer_from_memory():
    g = gateway()
    calls = []
    g.forward = lambda q, h=None, spoken=False, tradition=None: (calls.append(tradition), {'mode': 'llm', 'answer': 'x'})[1]
    g.cached_forward('מה מברכים על אורז?'); g.cached_forward('מה מברכים על אורז?', None, False, 'ashkenazi')
    assert calls == [None, 'ashkenazi']
