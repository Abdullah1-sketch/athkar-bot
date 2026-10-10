# -*- coding: utf-8 -*-
"""Get X access tokens so the app can post as another account (one-time).

Run:  python get_tokens.py
"""
import sys
import webbrowser

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from requests_oauthlib import OAuth1Session
except ImportError:
    print("شغّل هذا الأمر أول:  pip install requests-oauthlib")
    sys.exit(1)

print("الصق Consumer Key (API Key) واضغط Enter:")
key = input("> ").strip()
print("الصق Consumer Secret (API Key Secret) واضغط Enter:")
secret = input("> ").strip()

oauth = OAuth1Session(key, client_secret=secret, callback_uri="oob")
try:
    req = oauth.fetch_request_token("https://api.x.com/oauth/request_token")
except Exception as exc:
    print("\nما قدرت أكلم X. تأكد من المفتاحين وأعد المحاولة.\n", exc)
    sys.exit(1)

url = oauth.authorization_url("https://api.x.com/oauth/authorize")
print("\n1) افتح هذا الرابط (لازم تكون مسجّل دخول في المتصفح بحساب @Najd_Are):\n")
print(url)
try:
    webbrowser.open(url)
except Exception:
    pass
print("\n2) اضغط Authorize app، وانسخ الرقم (PIN) اللي يطلع لك، والصقه هنا:")
pin = input("PIN > ").strip()

oauth = OAuth1Session(key, client_secret=secret,
                      resource_owner_key=req["oauth_token"],
                      resource_owner_secret=req["oauth_token_secret"],
                      verifier=pin)
tokens = oauth.fetch_access_token("https://api.x.com/oauth/access_token")

print("\n================ تم ✅ ================")
print("الحساب:", "@" + tokens.get("screen_name", "?"))
if tokens.get("screen_name", "").lower() != "najd_are":
    print("⚠️ انتبه: هذا مو حساب @Najd_Are! سجّل دخول بالحساب الصح وأعد التشغيل.")
print("\nحط هذي الأربعة في GitHub (Secrets):")
print("X_API_KEY             =", key)
print("X_API_SECRET          =", secret)
print("X_ACCESS_TOKEN        =", tokens["oauth_token"])
print("X_ACCESS_TOKEN_SECRET =", tokens["oauth_token_secret"])
print("\nلا ترسل هذي القيم لأحد.")
