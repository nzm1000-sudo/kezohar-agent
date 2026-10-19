import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kezohar.blessing_lookup import lookup


def test_the_brand_the_book_rules_on_and_not_its_ingredients():
    assert 'שהכל' in lookup('מה מברכים על קורנפלקס של אלופים? הרכיבים: פתיתי תירס קלויים')['answer']
    assert lookup('מה מברכים על חטיף תמרים במילוי?') is None or 'חטיף' not in lookup('מה מברכים על חטיף תמרים במילוי?')['blessing_lookup']['matched'].split()
