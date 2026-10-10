"""Pre-launch check report -> reports/check.md

1. Prayer times for 14 days vs the Aladhan API (Umm al-Qura method, Riyadh).
2. White-days reminders for the next 12 Hijri months (Umm al-Qura calendar).
3. Every tweet text rendered, with its length.
4. The full 7-day posting schedule.
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from athkar import texts as T  # noqa: E402
from athkar.schedule import RIYADH, events_for, hijri, load_verses, prayer_times, render, schedule  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "reports" / "check.md"


def aladhan(d):
    url = (f"https://api.aladhan.com/v1/timings/{d.strftime('%d-%m-%Y')}"
           "?latitude=24.7136&longitude=46.6753&method=4")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()["data"]["timings"]


def main():
    lines = ["# Pre-launch check", f"Generated {datetime.now(RIYADH):%Y-%m-%d %H:%M} Riyadh", ""]
    verses = load_verses()
    today = datetime.now(RIYADH).date()

    lines += ["## 1. Prayer times vs Aladhan (Umm al-Qura)", "",
              "| date | prayer | bot | aladhan | diff (min) |", "|---|---|---|---|---|"]
    worst = 0
    for i in range(14):
        d = today + timedelta(days=i)
        ours = prayer_times(d)
        try:
            ref = aladhan(d)
        except Exception as exc:
            lines.append(f"| {d} | aladhan error {exc} | | | |")
            continue
        for k, rk in (("fajr", "Fajr"), ("sunrise", "Sunrise"), ("dhuhr", "Dhuhr"),
                      ("asr", "Asr"), ("maghrib", "Maghrib"), ("isha", "Isha")):
            hh, mm = map(int, ref[rk].split(" ")[0].split(":"))
            theirs = datetime(d.year, d.month, d.day, hh, mm, tzinfo=RIYADH)
            diff = int((ours[k] - theirs).total_seconds() // 60)
            worst = max(worst, abs(diff))
            lines.append(f"| {d} | {k} | {ours[k]:%H:%M} | {theirs:%H:%M} | {diff:+d} |")
    lines += ["", f"**Largest difference: {worst} min**", ""]

    lines += ["## 2. White-days reminders (next 12 months)", ""]
    d = today
    found = 0
    while found < 12 and d < today + timedelta(days=400):
        for e in events_for(d, verses):
            if e["kind"] == "white_days":
                h = hijri(d)
                lines += [f"**{d} ({T.WEEKDAYS_AR[d.weekday()]}) = {h.day}/{h.month}/{h.year} هـ**", "```",
                          e["text"], "```", ""]
                found += 1
        d += timedelta(days=1)

    lines += ["## 3. All texts", ""]
    groups = [("morning", T.MORNING), ("evening", T.EVENING), ("duha", T.DUHA), ("witr", T.WITR),
              ("mulk", [T.MULK]), ("thursday", [T.THURSDAY_SALAWAT]), ("friday", [T.FRIDAY_SUNAN]),
              ("fasting", [T.fasting("الاثنين")])]
    groups += [(p, T.PRAYERS[p]) for p in T.PRAYERS]
    bad = 0
    for name, items in groups:
        for i, t in enumerate(items, 1):
            r = render(t, verses)
            if r is None or len(r) > 280:
                bad += 1
            lines += [f"**{name} {i}** ({'MISSING VERSE' if r is None else len(r)} chars)", "```", r or t, "```"]
    lines += ["", f"**Problems: {bad}**", ""]

    lines += ["## 4. Schedule for the next 7 days (Riyadh)", "", "| time | post | image |", "|---|---|---|"]
    for e in schedule(today, 7, verses):
        lines.append(f"| {e['at'].astimezone(RIYADH):%a %Y-%m-%d %H:%M:%S} | {e['kind']} | {e.get('image') or ''} |")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"worst prayer diff {worst} min, text problems {bad}")


if __name__ == "__main__":
    main()
