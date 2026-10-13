"""Fast path: zmanim/calendar answers by code, no LLM call."""
import datetime
import math
import re

DEFAULT_LAT = 31.4227   # נתיבות
DEFAULT_LON = 34.5966
DEFAULT_LOCATION = "נתיבות"

FAST_KEYWORDS = [
    "שקיעה", "זריחה", "עלות השחר", "צאת הכוכבים", "צאת שבת",
    "סוף זמן", "קריאת שמע", "זמן תפילה", "זמני היום", "זמנים",
    "תאריך עברי", "איזה תאריך", "פרשה", "פרשת השבוע", "ראש חודש",
]
# שמות חגים/צומות מפעילים Fast רק בשאלת "מתי" (למשל "מתי צום גדליה השנה?").
# שאלה הלכתית כמו "מה סדר הדלקת נרות חנוכה?" חייבת להגיע ל-retrieval + מקורות.
HOLIDAY_WORDS = ["חג", "צום", "גדליה", "כיפור", "סוכות", "פסח", "שבועות", "חנוכה", "פורים",
                 "ראש השנה", "שמחת תורה", "לג בעומר", "טו בשבט", "תשעה באב"]
WHEN_RE = re.compile(r'(מתי|אימתי|באיזה תאריך|מתקיים|חל)')

FAST_RE = re.compile("|".join(FAST_KEYWORDS))
FAST_NORMED = ["תאריכ עברי", "איזה תאריכ", "עברי"]
OUT_OF_SCOPE_RE = re.compile(r'(מזג האוויר|מזג אוויר|שיר אהבה|כתוב לי שיר)')

def is_fast_question(q):
    if not q:
        return False
    # Mentioning a calendar event does not make a ruling question a date query.
    if re.search(r'(יעלה\s+ויב[וא]+|שכחתי|שכח|האם חוזר|הלל.*ברכה)', q):
        return False
    # A ritual mentioning a time/event still requires source retrieval.
    if re.search(r'(?:מניח|להניח|תפילין|מותר|אסור|חייב|לברך|מברכ|לדבר|מדליק|להדליק|אוכלים|לבשל)',q):
        return False
    if FAST_RE.search(q) and ('ראש חודש' not in q or re.search(r'(?:היום|מתי|תאריך|חל)',q)):
        return True
    if (any(w in q for w in HOLIDAY_WORDS) and WHEN_RE.search(q)
            and re.search(r'(?:מתי|באיזה תאריך)\s+(?:(?:חל|יחול|מתקיים)\s+)?(?:צום|חג|ראש השנה|יום כיפור|חנוכה|פורים|פסח|סוכות|שבועות)',q)):
        return True
    # normalized fallback: catches ה' prefix inflections like העברי/התאריך
    try:
        from . import hebrew as _h
        nq = _h.normalize(q)
        return any(k in nq for k in FAST_NORMED)
    except Exception:
        return False

def is_out_of_scope(q):
    return bool(OUT_OF_SCOPE_RE.search(q or ""))

# ---- astronomy (NOAA) ----
def _sun_times(date, lat, lon, tz_offset=3.0):
    """Sunrise/sunset in local time (hours float). Method: NOAA solar calculation.
    tz_offset: Israel DST-aware — caller passes correct offset."""
    N = date.timetuple().tm_yday
    lng_hour = lon / 15.0
    def calc(is_rise):
        t = N + ((6 if is_rise else 18) - lng_hour) / 24.0
        M = 0.9856 * t - 3.289
        L = (M + 1.916 * math.sin(math.radians(M)) + 0.020 * math.sin(math.radians(2*M)) + 282.634) % 360
        RA = math.degrees(math.atan(0.91764 * math.tan(math.radians(L)))) % 360
        Lq = (math.floor(L/90)*90)
        RAq = (math.floor(RA/90)*90)
        RA = (RA + Lq - RAq) / 15.0
        sin_dec = 0.39782 * math.sin(math.radians(L))
        cos_dec = math.cos(math.asin(sin_dec))
        cos_h = (math.cos(math.radians(90.833)) - sin_dec*math.sin(math.radians(lat))) / (cos_dec*math.cos(math.radians(lat)))
        cos_h = max(-1.0, min(1.0, cos_h))
        H = math.degrees(math.acos(cos_h))
        H = (360 - H)/15.0 if is_rise else H/15.0
        T = H + RA - 0.06571*t - 6.622
        UT = (T - lng_hour) % 24
        return (UT + tz_offset) % 24
    return calc(True), calc(False)

def _fmt(h):
    h = h % 24
    hh, mm = int(h), int(round((h - int(h)) * 60))
    if mm == 60:
        hh, mm = (hh + 1) % 24, 0
    return f"{hh:02d}:{mm:02d}"

def _israel_tz_offset(date):
    """Rough IDT (UTC+3) Apr–Oct, IST (UTC+2) otherwise. Documented approximation."""
    return 3.0 if 4 <= date.month <= 10 else 2.0

def zmanim(date, lat=DEFAULT_LAT, lon=DEFAULT_LON, method="GRA"):
    """Halachic day times. method GRA: proportional hours from sunrise/sunset.
    alot=72min before sunrise, tzeit=42min (3 stars) after sunset — stated explicitly."""
    tz = _israel_tz_offset(date)
    sr, ss = _sun_times(date, lat, lon, tz)
    day_len = (ss - sr) % 24
    shaah = day_len / 12.0
    chatzot = (sr + day_len / 2) % 24
    return {
        "date": date.isoformat(),
        "method_astronomy": "NOAA solar calculation",
        "method_halacha": method + ": שעה זמנית=יום/12; עלות=זריחה-72דקות; צאת=שקיעה+42דקות (3 כוכבים)",
        "sunrise": _fmt(sr),
        "sunset": _fmt(ss),
        "alot_hashachar": _fmt(sr - 72/60),
        "tzeit": _fmt(ss + 42/60),
        "sof_shma": _fmt(sr + 3*shaah),
        "sof_tefila": _fmt(sr + 4*shaah),
        "chatzot": _fmt(chatzot),
        "tz_offset": tz,
    }

def hebrew_date_info(date):
    try:
        from pyluach.dates import GregorianDate
        g = GregorianDate(date.year, date.month, date.day)
        h = g.to_heb()
        return {"hebrew_date": h.hebrew_date_string(), "holiday": h.holiday(hebrew=True) if hasattr(h, 'holiday') else None,
                "holiday_en": h.holiday() if hasattr(h, 'holiday') else None}
    except Exception as e:
        return {"hebrew_date": "", "error": str(e)}

def parasha_info(date):
    try:
        from pyluach import parshios
        from pyluach.dates import GregorianDate
        g = GregorianDate(date.year, date.month, date.day)
        return parshios.getparsha_string(g, hebrew=True, israel=True)
    except Exception:
        return ""

def fast_info(date):
    try:
        from pyluach import hebrewcal
        from pyluach.dates import GregorianDate
        g = GregorianDate(date.year, date.month, date.day)
        return hebrewcal.fast_day(g, hebrew=True)
    except Exception:
        return None

def handle(question, lat=DEFAULT_LAT, lon=DEFAULT_LON, location=DEFAULT_LOCATION, today=None):
    """Answer zmanim/calendar questions without LLM. Returns dict or None if not fast."""
    if is_out_of_scope(question):
        return {"kind": "refuse",
                "answer": "מצטער, אני עונה רק על הלכה, מנהגים, ברכות, זמנים, תפילות, צומות, שבת, חגים ולוח השנה העברי.",
                "no_llm": True}
    if not is_fast_question(question):
        return None
    d = today or datetime.date.today()
    if isinstance(d, datetime.datetime):
        d = d.date()
    q = question
    z = zmanim(d, lat, lon)
    hi = hebrew_date_info(d)
    heb = hi.get("hebrew_date", "")
    out = {"kind": "fast", "no_llm": True, "location": location, "lat": lat, "lon": lon,
           "gregorian": d.isoformat(), "hebrew": heb, "method": z["method_halacha"]}
    if "פרשה" in q or "פרשת" in q:
        p = parasha_info(d)
        out["answer"] = f"פרשת השבוע: {p}. התאריך העברי היום: {heb}."
        out["parasha"] = p
    elif "שקיעה" in q:
        out["answer"] = f"שקיעה היום ב{location}: {z['sunset']} (שיטת חישוב: {z['method_astronomy']})."
        out["zmanim"] = z
    elif "זריחה" in q:
        out["answer"] = f"זריחה היום ב{location}: {z['sunrise']} (שיטת חישוב: {z['method_astronomy']})."
        out["zmanim"] = z
    elif "קריאת שמע" in q or "סוף זמן" in q:
        out["answer"] = (f"סוף זמן קריאת שמע ב{location}: {z['sof_shma']} (שיטת הגר\"א, {z['method_halacha']}).")
        out["zmanim"] = z
    elif "צאת" in q:
        out["answer"] = f"צאת הכוכבים ב{location}: {z['tzeit']} ({z['method_halacha']})."
        out["zmanim"] = z
    elif "עלות" in q:
        out["answer"] = f"עלות השחר ב{location}: {z['alot_hashachar']} ({z['method_halacha']})."
        out["zmanim"] = z
    elif "צום" in q or "גדליה" in q or "כיפור" in q:
        f = fast_info(d)
        out["answer"] = f"התאריך העברי: {heb}." + (f" היום: {f}." if f else " היום אין צום.")
        out["fast"] = f
    elif "ראש חודש" in q:
        out["answer"] = f"התאריך העברי היום: {heb}."
    elif "תאריך עברי" in q or "איזה תאריך" in q:
        out["answer"] = f"התאריך העברי היום: {heb} ({d.isoformat()})."
    else:
        out["answer"] = f"התאריך העברי: {heb}. שקיעה ב{location}: {z['sunset']}, זריחה: {z['sunrise']}."
        out["zmanim"] = z
    return out
