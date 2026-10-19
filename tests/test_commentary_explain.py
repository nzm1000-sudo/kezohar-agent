import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kezohar.commentary_lookup import asked


def test_a_verse_to_explain_goes_to_rashi_and_a_named_commentator_is_kept():
    assert asked('והכנעני אז בארץ תסביר לי')[2] == 'והכנעני אז בארץ'
    assert asked('מה הפירוש של בראשית ברא אלהים')[0] == 'רש״י'
    assert asked('מה אומר הרמבן על הפסוק "ויאמר ה אל אברם"')[0] == 'רמב״ן'
    assert asked('שבת תסביר לי') is None and asked('מה הפירוש של המילה מוקצה') is None
