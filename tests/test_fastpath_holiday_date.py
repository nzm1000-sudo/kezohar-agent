from kezohar.fastpath import handle


def test_a_holidays_date_is_not_answered_as_todays_fast():
    assert handle('באיזה תאריך חל יום כיפור?') is None
    assert handle('מתי חל צום גדליה?') is None
    today = handle('האם היום צום?')
    assert today is None or today.get('kind') == 'fast'
