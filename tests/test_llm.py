import sys
sys.path.insert(0, "src")
from kezohar import llm

def test_build_messages_contains_sources():
    q = "מה מברכים על אורז?"
    srcs = [{"reference": "שולחן ערוך, אורח חיים רח:ז", "text": "הכוסס את האורז מברך בורא פרי האדמה"}]
    msgs = llm.build_messages(q, srcs)
    assert msgs[0]["role"] == "system"
    assert "רח:ז" in msgs[1]["content"] and "אורז" in msgs[1]["content"]

def test_ask_no_config_raises():
    try:
        llm.ask("שאלה?", [], "", "m")
        assert False, "should raise"
    except llm.LLMUnavailable:
        pass

def test_ask_unreachable_raises():
    try:
        llm.ask("שאלה?", [], "http://127.0.0.1:9/v1", "m", timeout=2)
        assert False, "should raise"
    except llm.LLMUnavailable:
        pass

def test_check_health_bad():
    ok, info = llm.check_health("http://127.0.0.1:9/v1", timeout=2)
    assert ok is False

def test_check_health_not_configured():
    ok, info = llm.check_health("", timeout=2)
    assert ok is False
