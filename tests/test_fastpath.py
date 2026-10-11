import sys, datetime
sys.path.insert(0, "src")
from kezohar import fastpath

D = datetime.date(2026, 10, 11)

def test_sunset_no_llm():
    r = fastpath.handle("מתי שקיעה היום בנתיבות?", today=D)
    assert r and r["no_llm"] and "שקיעה" in r["answer"] and r["location"] == "נתיבות"

def test_shma_method_stated():
    r = fastpath.handle("מתי סוף זמן קריאת שמע מחר?", today=D)
    assert r and ("גר" in r["answer"] or "שיטה" in r["answer"] or "method" in str(r).lower() or "שעה זמנית" in r["answer"])

def test_parasha():
    r = fastpath.handle("איזו פרשה השבוע?", today=D)
    assert r and "פרשת" in r["answer"]

def test_hebrew_date():
    r = fastpath.handle("מה התאריך העברי היום?", today=D)
    assert r and r["hebrew"]

def test_refuse():
    r = fastpath.handle("מה מזג האוויר מחר?")
    assert r and r["kind"] == "refuse"

def test_nonfast_returns_none():
    assert fastpath.handle("מה מברכים על אורז?", today=D) is None

def test_location_param():
    r = fastpath.handle("מתי שקיעה היום?", lat=31.78, lon=35.22, location="ירושלים", today=D)
    assert r and r["location"] == "ירושלים"

def test_sunset_sane_range():
    z = fastpath.zmanim(D)
    # Netivot Oct: sunrise ~06:xx-07:xx, sunset ~17:xx-18:xx local
    sr_h = int(z["sunrise"].split(":")[0]); ss_h = int(z["sunset"].split(":")[0])
    assert 5 <= sr_h <= 8 and 16 <= ss_h <= 20
    assert z["method_halacha"] and z["method_astronomy"]
