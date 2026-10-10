"""Build data/verses.json from the Tanzil Quran text (via api.alquran.cloud).

The bot never uses hand-typed Quran text. For each entry in athkar.texts.VERSES
we download the ayah(s) and, for fragments, locate the requested words while
ignoring diacritics, then keep Tanzil's exact wording for that span.
Run: python tools/build_verses.py
"""
import json
import sys
import unicodedata
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from athkar.texts import VERSES  # noqa: E402

EDITION = "quran-simple"  # Tanzil "Simple" script with full diacritics
API = "https://api.alquran.cloud/v1/ayah/{s}:{a}/" + EDITION
OUT = Path(__file__).resolve().parents[1] / "data" / "verses.json"

FOLD = {"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"}


def is_mark(ch):
    return unicodedata.category(ch) in ("Mn", "Me", "So", "Cf") or ch in "ـ۝۞۩"


def letters(text):
    """Return (normalized letters, index map back into text)."""
    out, idx = [], []
    for i, ch in enumerate(text):
        if ch.isspace() or is_mark(ch):
            continue
        out.append(FOLD.get(ch, ch))
        idx.append(i)
    return "".join(out), idx


def fetch(s, a):
    r = requests.get(API.format(s=s, a=a), timeout=30)
    r.raise_for_status()
    data = r.json()["data"]
    text = data["text"]
    if a == 1 and s not in (1, 9):
        # The API prefixes the basmala to the first ayah of a surah.
        basmala = "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ"
        if text.startswith(basmala):
            text = text[len(basmala):].strip()
    return text.strip()


def main():
    result = {}
    for key, (s, a1, a2, hint, ref) in VERSES.items():
        full = " ".join(fetch(s, a) for a in range(a1, a2 + 1))
        if hint is None:
            text = full
        else:
            norm, idx = letters(full)
            want, _ = letters(hint)
            pos = norm.find(want)
            if pos < 0 or norm.find(want, pos + 1) >= 0:
                raise SystemExit(f"{key}: fragment not found exactly once in {s}:{a1}")
            start, end = idx[pos], idx[pos + len(want) - 1] + 1
            while end < len(full) and is_mark(full[end]) and not full[end].isspace():
                end += 1
            text = full[start:end].strip()
        result[key] = {"text": text, "ref": ref, "source": f"Tanzil {EDITION} {s}:{a1}-{a2}"}
        print(key, "|", text)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
