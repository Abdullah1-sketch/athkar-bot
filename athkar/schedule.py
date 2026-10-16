"""Daily schedule for Riyadh: prayer times (Umm al-Qura method) and posts."""
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from hijridate import Gregorian, Hijri

from . import texts as T

RIYADH = timezone(timedelta(hours=3))
LAT, LNG = 24.7136, 46.6753
ROOT = Path(__file__).resolve().parents[1]
MIN_GAP = timedelta(minutes=3)

# ---------------------------------------------------------------- astronomy
# Standard solar-position formulas (as used by PrayTimes / Umm al-Qura method):
# Fajr at 18.5 degrees below the horizon, Asr at shadow factor 1,
# Maghrib at sunset, Isha 90 minutes after Maghrib (120 in Ramadan).


def _dsin(d): return math.sin(math.radians(d))
def _dcos(d): return math.cos(math.radians(d))
def _dtan(d): return math.tan(math.radians(d))
def _darcsin(x): return math.degrees(math.asin(x))
def _darccos(x): return math.degrees(math.acos(x))
def _darccot(x): return math.degrees(math.atan(1 / x))
def _fix(a, b): return a - b * math.floor(a / b)


def _julian(d):
    y, m = d.year, d.month
    if m <= 2:
        y -= 1
        m += 12
    a = math.floor(y / 100)
    b = 2 - a + math.floor(a / 4)
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d.day + b - 1524.5


def _sun(jd):
    d = jd - 2451545.0
    g = _fix(357.529 + 0.98560028 * d, 360)
    q = _fix(280.459 + 0.98564736 * d, 360)
    lam = _fix(q + 1.915 * _dsin(g) + 0.020 * _dsin(2 * g), 360)
    e = 23.439 - 0.00000036 * d
    ra = _fix(math.degrees(math.atan2(_dcos(e) * _dsin(lam), _dcos(lam))) / 15, 24)
    eqt = q / 15 - ra
    decl = _darcsin(_dsin(e) * _dsin(lam))
    return decl, eqt


def prayer_times(d):
    """Return dict of aware datetimes (Riyadh) for date d."""
    jd = _julian(d) - LNG / (15 * 24)
    tz = 3

    def mid(t):
        _, eqt = _sun(jd + t / 24)
        return _fix(12 - eqt, 24)

    def angle_time(angle, t, ccw):
        decl, _ = _sun(jd + t / 24)
        noon = mid(t)
        x = (-_dsin(angle) - _dsin(decl) * _dsin(LAT)) / (_dcos(decl) * _dcos(LAT))
        h = _darccos(x) / 15
        return noon + (-h if ccw else h)

    def asr_time(t):
        decl, _ = _sun(jd + t / 24)
        ang = -_darccot(1 + _dtan(abs(LAT - decl)))
        return angle_time(ang, t, False)

    # two refinement passes
    t = {"fajr": 5, "sunrise": 6, "dhuhr": 12, "asr": 13, "maghrib": 18}
    for _ in range(2):
        t = {
            "fajr": angle_time(18.5, t["fajr"] / 24 * 24, True),
            "sunrise": angle_time(0.833, t["sunrise"], True),
            "dhuhr": mid(t["dhuhr"]),
            "asr": asr_time(t["asr"]),
            "maghrib": angle_time(0.833, t["maghrib"], False),
        }
    base = datetime(d.year, d.month, d.day, tzinfo=RIYADH)
    out = {}
    for k, hours in t.items():
        local = hours + tz - LNG / 15
        # Round UP to the minute: a reminder must never come before the adhan.
        minutes = math.ceil(local * 60 - 1e-9)
        out[k] = base + timedelta(minutes=minutes)
    h = Gregorian(d.year, d.month, d.day).to_hijri()
    out["isha"] = out["maghrib"] + timedelta(minutes=120 if h.month == 9 else 90)
    return out


# ---------------------------------------------------------------- helpers

def hijri(d):
    return Gregorian(d.year, d.month, d.day).to_hijri()


def jitter(key, seconds):
    """Stable pseudo-random delay per event (same after a restart)."""
    return timedelta(seconds=int(hashlib.sha256(key.encode()).hexdigest(), 16) % max(1, seconds))


def pick(items, d, salt=0):
    return items[(d.toordinal() + salt) % len(items)]


def load_verses():
    path = ROOT / "data" / "verses.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def render(text, verses):
    """Fill {V:key}/{VN:key}. Returns None if a verse is missing (never guess)."""
    import re
    def repl(m):
        kind, key = m.group(1), m.group(2)
        v = verses.get(key)
        if not v:
            raise KeyError(key)
        return f"﴿{v['text']}﴾" + ("" if kind == "VN" else f" [{v['ref']}]")
    try:
        return re.sub(r"\{(VN?):(\w+)\}", repl, text)
    except KeyError:
        return None


def no_fasting_tomorrow(h_tomorrow):
    """Skip voluntary-fast reminders around Ramadan/Eid/Tashriq (dates there
    depend on moon sighting, so stay well clear)."""
    m, day = h_tomorrow.month, h_tomorrow.day
    if m == 9:
        return True
    if m == 8 and day >= 28:
        return True
    if m == 10 and day <= 3:
        return True
    if m == 12 and 8 <= day <= 14:
        return True
    return False


# ---------------------------------------------------------------- events

# Warm-up for a new account: until this date only the core daily posts go out
# (morning/evening adhkar, Mulk, Witr) plus the weekly/monthly reminders.
# The five prayer reminders and Duha return automatically afterwards.
WARMUP_UNTIL = date(2026, 10, 1)  # warm-up switched off: full schedule
WARMUP_SKIP = {"fajr", "dhuhr", "asr", "maghrib", "isha", "duha"}


def events_for(d, verses):
    """All posts for Riyadh calendar date d: list of dicts (key, at, text, image)."""
    pt = prayer_times(d)
    nxt = prayer_times(d + timedelta(days=1))
    wd = d.weekday()  # Mon=0 ... Fri=4
    ds = d.isoformat()
    ev = []

    def add(name, at, text, image=None, exact=False):
        key = f"{ds}:{name}"
        if not exact:
            at = at + jitter(key, 600)  # 0-10 min, so times vary day to day
        else:
            # Adhan posts: 1-2 minutes after the computed adhan, so they never come early
            # even where official times differ from ours by a minute.
            at = at + timedelta(seconds=60) + jitter(key, 60)  # 1-2 min after the adhan
        ev.append({"key": key, "at": at, "text": text, "image": image, "kind": name})

    for p in ("fajr", "dhuhr", "asr", "maghrib", "isha"):
        if p == "dhuhr" and wd == 4:
            continue  # Friday: Jumu'ah, not Dhuhr
        add(p, pt[p], pick(T.PRAYERS[p], d), exact=True)

    add("morning", pt["fajr"] + timedelta(minutes=15), pick(T.MORNING, d), "adhkar.jpg")
    if wd == 4:
        add("friday_sunan", pt["sunrise"] + timedelta(minutes=30), T.FRIDAY_SUNAN)
    duha = pt["sunrise"] + (pt["dhuhr"] - pt["sunrise"]) * 0.5
    add("duha", duha, pick(T.DUHA, d))
    add("evening", pt["asr"] + timedelta(minutes=15), pick(T.EVENING, d), "adhkar.jpg")
    if wd == 4:
        add("friday_hour", pt["maghrib"] - timedelta(minutes=60), T.FRIDAY_HOUR)
    if wd == 3:
        add("thursday_salawat", pt["maghrib"] + timedelta(minutes=4), T.THURSDAY_SALAWAT)

    # Fasting reminders after Maghrib, for tomorrow.
    h = hijri(d)
    h_tom = hijri(d + timedelta(days=1))
    if h.day == 12 and h.month not in (9, 12):
        rows = []
        for k in (13, 14, 15):
            g = Hijri(h.year, h.month, k).to_gregorian()
            gd = date(g.year, g.month, g.day)
            rows.append((T.WEEKDAYS_AR[gd.weekday()], k, T.HIJRI_MONTHS_AR[h.month - 1]))
        add("white_days", pt["maghrib"] + timedelta(minutes=20), T.white_days(rows))
    elif wd in (6, 2) and not no_fasting_tomorrow(h_tom):  # Sunday -> Monday, Wednesday -> Thursday
        add("fasting", pt["maghrib"] + timedelta(minutes=20), T.fasting("الاثنين" if wd == 6 else "الخميس"))

    mulk_at = datetime(d.year, d.month, d.day, 22, 0, tzinfo=RIYADH)
    add("mulk", mulk_at, T.MULK, "mulk.jpg")

    # Witr: start of the last third of the night (Maghrib -> next Fajr).
    night = nxt["fajr"] - pt["maghrib"]
    add("witr", pt["maghrib"] + night * 2 / 3, pick(T.WITR, d))

    out = []
    for e in ev:
        text = render(e["text"], verses)
        if text is None:
            print(f"SKIP {e['key']}: verse text missing (run tools/build_verses.py)")
            continue
        e["text"] = text
        out.append(e)
    if d < WARMUP_UNTIL:
        out = [e for e in out if e["kind"] not in WARMUP_SKIP]
    return out


def schedule(start, days, verses):
    """Events over several dates, sorted, with a minimum gap between posts.
    Adhan posts keep their time; other posts move later if too close."""
    ev = []
    for i in range(days):
        ev.extend(events_for(start + timedelta(days=i), verses))
    ev.sort(key=lambda e: e["at"])
    fixed = {"fajr", "dhuhr", "asr", "maghrib", "isha"}
    for i in range(1, len(ev)):
        prev = ev[i - 1]
        if ev[i]["at"] - prev["at"] < MIN_GAP:
            if ev[i]["kind"] in fixed and prev["kind"] not in fixed:
                prev["at"] = ev[i]["at"] - MIN_GAP
            else:
                ev[i]["at"] = prev["at"] + MIN_GAP
    ev.sort(key=lambda e: e["at"])
    return ev
