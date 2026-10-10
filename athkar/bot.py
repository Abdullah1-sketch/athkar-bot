"""Athkar bot runner: waits for each scheduled time and posts to X.

Safety rules:
- Each post is reserved in state.json (and pushed) BEFORE calling X, so a
  restart can never post it twice.
- X answered with an error  -> not published; retried while still on time.
- No answer (network)       -> 'uncertain'; never retried.
- A post more than LATE_LIMIT late (e.g. GitHub started us late) is skipped,
  so an old reminder is never tweeted at the wrong time.
"""
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from requests_oauthlib import OAuth1

from .schedule import RIYADH, ROOT, load_verses, schedule

STATE = ROOT / "state.json"
IMAGES = ROOT / "images"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() != "false"
RUN_SECONDS = int(os.getenv("RUN_SECONDS", str(5 * 3600 + 30 * 60)))
LATE_LIMIT = timedelta(minutes=int(os.getenv("LATE_LIMIT_MINUTES", "20")))
X_TWEET = "https://api.x.com/2/tweets"
X_MEDIA_V2 = "https://api.x.com/2/media/upload"
X_MEDIA_V1 = "https://upload.twitter.com/1.1/media/upload.json"
STOP = False


class XRejected(Exception):
    def __init__(self, status, body):
        super().__init__(f"X HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body[:300]


def now():
    return datetime.now(timezone.utc)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"posted": {}}


def save_state(state, message="Update bot state [skip ci]", push=True):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(STATE)
    if not push or DRY_RUN or os.getenv("BOT_GIT_CHECKPOINT") != "true":
        return
    def git(*a):
        return subprocess.run(["git", *a], check=True, capture_output=True, text=True, timeout=60)
    git("add", "--", "state.json")
    if subprocess.run(["git", "diff", "--cached", "--quiet", "--", "state.json"]).returncode == 1:
        git("commit", "-m", message)
    branch = os.getenv("BOT_STATE_BRANCH", "main")
    for attempt in range(3):
        try:
            git("push", "origin", f"HEAD:{branch}")
            return
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise RuntimeError("State push failed; stopping before posting anything else")
            git("pull", "--rebase", "origin", branch)


def auth():
    return OAuth1(os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
                  os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_TOKEN_SECRET"])


def upload_image(name):
    data = (IMAGES / name).read_bytes()
    r = requests.post(X_MEDIA_V2, auth=auth(), timeout=60,
                      files={"media": (name, data, "image/jpeg")},
                      data={"media_category": "tweet_image", "media_type": "image/jpeg"})
    if r.ok:
        body = r.json()
        mid = (body.get("data") or {}).get("id") or body.get("media_id_string")
        if mid:
            return str(mid)
    print(f"v2 media upload failed ({r.status_code}): {r.text[:200]}; trying v1.1")
    r = requests.post(X_MEDIA_V1, auth=auth(), timeout=60, files={"media": (name, data)})
    if r.ok and r.json().get("media_id_string"):
        return r.json()["media_id_string"]
    print(f"v1.1 media upload failed ({r.status_code}): {r.text[:200]}")
    return None


def post(text, image=None):
    if DRY_RUN:
        print(f"\n--- DRY RUN ({image or 'no image'}) ---\n{text}\n--- END ---")
        return "dry_run", False
    payload = {"text": text}
    with_image = False
    if image:
        mid = upload_image(image)
        if mid:
            payload["media"] = {"media_ids": [mid]}
            with_image = True
    r = requests.post(X_TWEET, auth=auth(), json=payload, timeout=30)
    if r.status_code >= 400:
        raise XRejected(r.status_code, r.text)
    return r.json().get("data", {}).get("id", ""), with_image


def handle(event, state):
    posted = state.setdefault("posted", {})
    entry = posted.get(event["key"])
    if entry and entry.get("status") not in ("retry",):
        return
    late = now() - event["at"]
    if late > LATE_LIMIT:
        posted[event["key"]] = {"status": "skipped_late", "due": event["at"].isoformat()}
        save_state(state, push=False)  # nothing was posted; pushed with the next checkpoint
        print(f"SKIP {event['key']}: {int(late.total_seconds() // 60)} min late")
        return
    if len(event["text"]) > 280:
        posted[event["key"]] = {"status": "too_long", "due": event["at"].isoformat()}
        save_state(state)
        print(f"SKIP {event['key']}: {len(event['text'])} characters")
        return
    tries = (entry or {}).get("tries", 0) + 1
    posted[event["key"]] = {"status": "pending", "due": event["at"].isoformat(),
                            "at": now().isoformat(), "tries": tries}
    save_state(state)
    try:
        tweet_id, with_image = post(event["text"], event.get("image"))
    except XRejected as exc:
        retry = (exc.status == 429 or exc.status >= 500) and tries < 4
        posted[event["key"]].update(status="retry" if retry else "rejected", error=str(exc))
        save_state(state)
        print(f"{event['key']}: rejected by X ({exc}); {'will retry' if retry else 'not retried'}")
        if retry:
            time.sleep(30)
        return
    except Exception as exc:
        posted[event["key"]].update(status="uncertain", error=type(exc).__name__)
        save_state(state)
        print(f"{event['key']}: no answer from X ({type(exc).__name__}); NOT retried")
        return
    posted[event["key"]].update(status="sent" if not DRY_RUN else "dry_run",
                                tweet=tweet_id, image=with_image)
    save_state(state, f"Posted {event['kind']} [skip ci]")
    print(f"POSTED {event['key']} at {now().astimezone(RIYADH):%H:%M:%S}")


def prune(state):
    cutoff = (now() - timedelta(days=10)).astimezone(RIYADH).date().isoformat()
    posted = state.get("posted", {})
    for k in [k for k in posted if k[:10] < cutoff]:
        posted.pop(k)


def run():
    signal.signal(signal.SIGTERM, lambda *_: globals().__setitem__("STOP", True))
    state = load_state()
    prune(state)
    verses = load_verses()
    began = time.monotonic()
    print(f"Athkar bot started (DRY_RUN={DRY_RUN})")
    while not STOP and time.monotonic() - began < RUN_SECONDS:
        today = now().astimezone(RIYADH).date()
        events = schedule(today - timedelta(days=1), 3, verses)
        due = [e for e in events
               if e["at"] <= now()
               and state.get("posted", {}).get(e["key"], {}).get("status") in (None, "retry")]
        for e in due:
            if STOP:
                break
            handle(e, state)
        upcoming = [e["at"] for e in events if e["at"] > now()]
        wait = 60 if not upcoming else (min(upcoming) - now()).total_seconds()
        time.sleep(max(1, min(60, wait)))
    save_state(state)
    print("Athkar bot run finished")


if __name__ == "__main__":
    run()
