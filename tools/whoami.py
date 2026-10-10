"""Check the X keys work (no tweet is posted). Writes reports/whoami.txt."""
import os
from datetime import datetime
from pathlib import Path

import requests
from requests_oauthlib import OAuth1

names = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
missing = [n for n in names if not os.getenv(n)]
out = Path(__file__).resolve().parents[1] / "reports" / "whoami.txt"
out.parent.mkdir(exist_ok=True)
if missing:
    result = "missing secrets: " + ", ".join(missing)
else:
    auth = OAuth1(*(os.environ[n] for n in names))
    r = requests.get("https://api.x.com/2/users/me", auth=auth, timeout=30)
    if r.ok:
        result = "OK @" + r.json()["data"]["username"]
    else:
        result = f"HTTP {r.status_code} {r.text[:300]}"
out.write_text(f"{datetime.utcnow():%Y-%m-%d %H:%M} UTC  {result}\n", encoding="utf-8")
print(result)
