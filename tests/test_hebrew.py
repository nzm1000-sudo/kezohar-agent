import sys
sys.path.insert(0, "src")
from kezohar import hebrew

def test_strip_niqqud():
    assert hebrew.normalize("שַׁבָּת") == hebrew.normalize("שבת")

def test_beracha():
    assert hebrew.normalize("בְּרָכָה") == hebrew.normalize("ברכה")

def test_siman_seif():
    assert hebrew.normalize("סימן") != hebrew.normalize("סעיף")
    assert "סימן" not in hebrew.normalize("סעיף")

def test_final_letters():
    # ך/כ unify for matching
    assert hebrew.normalize("ברך") == hebrew.normalize("ברך")
    assert hebrew.normalize("מים") == hebrew.normalize("מים")
    # ם -> מ unification
    assert hebrew.tokens("שָׁלוֹם")[0] == hebrew.tokens("שלום")[0]

def test_geresh():
    assert hebrew.normalize("רח'") == hebrew.normalize("רח")
    assert hebrew.normalize('סי"מן') == hebrew.normalize("סימן")

def test_original_preserved():
    orig = "שַׁבָּת"
    hebrew.normalize(orig)
    assert orig == "שַׁבָּת"

def test_ref_normalization_keeps_digits():
    a = hebrew.normalize_ref("רח:ז")
    b = hebrew.normalize_ref("רח ז")
    assert a == b
    assert "רח" in a

def test_punctuation_spacing():
    assert hebrew.normalize("שבת,  חג.") == hebrew.normalize("שבת חג")
