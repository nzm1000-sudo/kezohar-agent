"""Only Judaism leaves the server: an answer about films, music, sport or television is withheld."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kezohar.agent import secular_answer


def test_a_film_answer_is_withheld_but_a_halacha_answer_about_films_is_not():
    assert secular_answer({'verdict': 'ok', 'answer': 'קיימים שני סרטים בשם עשרת הדיברות: אחד אילם משנת 1923 ובימויו של ססיל ב. דה-מיל'})
    assert secular_answer({'verdict': 'ok', 'answer': 'x', 'sources': [{'reference': 'עשרת הדיברות (סרט, 1956) — ויקיפדיה'}]})
    assert not secular_answer({'verdict': 'ok', 'answer': 'אסור לראות סרט בשבת במכשיר שמופעל בשבת.'})
    assert not secular_answer({'verdict': 'ok', 'answer': 'עשרת הדיברות נאמרו במעמד הר סיני', 'sources': [{'reference': 'עשרת הדיברות — ויקיפדיה'}]})


def test_a_seduction_question_is_refused_but_halacha_on_the_subject_is_not():
    from kezohar.agent import indecent_question
    assert indecent_question('איך אפשר לשכב עם מישהי ולהשפיע עליה?')
    assert indecent_question('איך לפתות בחורה')
    assert indecent_question('איפה יש פורנו')
    assert not indecent_question('מותר לשכב עם אשתי בימי נידה?')
    assert not indecent_question('האם מותר לשכב עם מישהי לפני החתונה?')
    assert not indecent_question('איך משפיעים על הילדים לאהוב תורה?')
