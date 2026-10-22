#!/usr/bin/env python3
"""Probe 2: GET /capabilities, look for the jsa challenge + model catalog."""
import base64, json, re
import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/140.0.0.0 Safari/537.36")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

r = s.get("https://duck.ai/", timeout=30)
tag = (re.search(r'data-version-tag="([^"]*)"', r.text) or [None, "dev"])[1]
sha = (re.search(r'data-version-sha="([^"]*)"', r.text) or [None, "hash"])[1]
fe_version = f"{tag}-{sha}"
signals = base64.b64encode(json.dumps({"start": 0, "events": [], "end": 0}).encode()).decode()

h = {
    "Accept": "*/*",
    "Origin": "https://duck.ai",
    "Referer": "https://duck.ai/",
    "x-vqd-accept": "1",
    "X-Vqd-Hash-1": "initial",
    "x-fe-version": fe_version,
    "x-fe-signals": signals,
}
r2 = s.get("https://duck.ai/duckchat/v1/capabilities", headers=h, timeout=30)
print("GET /capabilities ->", r2.status_code)
for k, v in r2.headers.items():
    if k.lower().startswith(("x-", "set-cookie", "content-type", "cache")):
        print(f"  {k}: {v[:300]}")
print("body[:1500]:", r2.text[:1500])

jsa = r2.headers.get("X-Vqd-Hash-1") or r2.headers.get("x-vqd-hash-1")
if jsa:
    print("\njsa len:", len(jsa), "prefix:", jsa[:40])
    try:
        dec = base64.b64decode(jsa).decode("utf-8", "replace")
    except Exception as e:
        dec = f"<fail {e}>"
    open("challenge.js", "w").write(dec)
    print("challenge.js bytes:", len(dec))
    print(dec[:2500])
