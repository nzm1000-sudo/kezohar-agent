import sys
sys.path.insert(0, "src")
from kezohar import citations

RETRIEVED = [
    {"source_id": "a1", "work_title": "שולחן ערוך", "reference": "שולחן ערוך, אורח חיים רח:ז",
     "reference_en": "Shulchan Arukh, Orach Chayim.208.7",
     "text": "הכוסס את האורז מברך עליו בורא פרי האדמה", "license": "PD", "tradition": "sephardi"},
    {"source_id": "b2", "work_title": "שולחן ערוך", "reference": "שולחן ערוך, יורה דעה פט:א",
     "reference_en": "Shulchan Arukh, Yoreh De'ah.89.1",
     "text": "אכל בשר לא יאכל גבינה עד שישהה שש שעות", "license": "PD", "tradition": "sephardi"},
]

def test_valid_citation_ok():
    q = "מה מברכים על אורז?"
    a = "מברכים בורא פרי האדמה (שולחן ערוך, אורח חיים רח:ז)."
    v = citations.verify_answer(q, a, RETRIEVED)
    assert v["verdict"] == "ok", v

def test_invented_citation_invalid():
    q = "מה מברכים על אורז?"
    a = "מברכים שהכל (שולחן ערוך, אורח חיים תקפז:ג)."
    v = citations.verify_answer(q, a, RETRIEVED)
    assert v["verdict"] == "invalid_citation", v

def test_no_source_admission():
    q = "מה דעת הרב קוק על מיקרוגל בשבת?"
    a = "אין לי מקור לכך."
    v = citations.verify_answer(q, a, RETRIEVED)
    assert v["verdict"] == "no_source", v

def test_unsupported_without_citation():
    q = "כמה זמן מחכים בין בשר לחלב?"
    a = "מחכים שש שעות."
    v = citations.verify_answer(q, a, RETRIEVED)
    assert v["verdict"] == "unsupported", v

def test_irrelevant_source():
    q = "מה מברכים על אורז?"
    a = "מחכים שש שעות (שולחן ערוך, יורה דעה פט:א)."
    v = citations.verify_answer(q, a, RETRIEVED)
    assert v["verdict"] == "irrelevant", v

def test_out_of_scope():
    v = citations.verify_answer("מה מזג האוויר מחר?", "מצטער, איני עונה על כך.", RETRIEVED)
    assert v["verdict"] == "out_of_scope", v

def test_cross_book_not_mixed():
    # citing a ref that was not retrieved at all must fail even if digits look similar
    q = "סדר הדלקת נרות חנוכה?"
    a = "ראה (משנה ברורה תרעו:א)."
    v = citations.verify_answer(q, a, RETRIEVED)
    assert v["verdict"] == "invalid_citation", v
