import sys
sys.path.insert(0, "src")
from kezohar import sefaria

def test_blocked():
    assert sefaria.is_blocked("Yalkut_Yosef 1:1")
    assert sefaria.is_blocked("חזון עובדיה ברכות")
    assert not sefaria.is_blocked("Shulchan_Arukh,_Orach_Chayim.208.7")

def test_clean_html():
    assert sefaria.clean_html("<i>שלום</i> עולם") == "שלום עולם"

def test_to_raw_unknown_license():
    recs, err = sefaria.to_raw_records({"ref": "X", "license": "All rights reserved", "he": ["טקסט"]})
    assert recs == [] and "license" in err

def test_to_raw_pd():
    data = {"ref": "Shulchan Arukh, Orach Chayim 208:7", "heRef": "שולחן ערוך, אורח חיים רח:ז",
            "license": "Public Domain", "he": ["הכוסס את האורז"], "versionTitle": "Lemberg 1893"}
    recs, err = sefaria.to_raw_records(data)
    assert err == "" and len(recs) == 1 and recs[0]["license"] == "PD-ShulchanAruch-1893"
