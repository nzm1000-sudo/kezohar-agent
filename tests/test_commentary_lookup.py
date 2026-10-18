"""'מה אומר <מפרש> על <פסוק>' is recognised, with the verse's words (commentary_lookup.asked)."""
from kezohar.commentary_lookup import asked


def test_commentator_and_verse_words():
    cases = {
        'מה אומר האבן עזרא על הפסוק «והכנעני אז בארץ»?': ('אבן עזרא', 'והכנעני אז בארץ'),
        'מה אומר רש"י על "בראשית ברא אלהים"': ('רש״י', 'בראשית ברא אלהים'),
        'איך מפרש הרמב"ן את והכנעני אז בארץ': ('רמב״ן', 'והכנעני אז בארץ'),
        'מה כותב הספורנו על ויאמר אלהים יהי אור': ('ספורנו', 'ויאמר אלהים יהי אור'),
    }
    for question, (name, words) in cases.items():
        got = asked(question)
        assert got and got[0] == name and got[2] == words, (question, got)


def test_not_a_commentary_question():
    for question in ('מה מברכים על בננה', 'מי היה רש"י', 'מתי נולד הרמב"ם'):
        assert asked(question) is None, question
