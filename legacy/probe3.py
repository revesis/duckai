#!/usr/bin/env python3
"""Probe 3: GET /duckchat/v1/status with x-vqd-accept:1 -> expect the jsa challenge."""
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

h = {
    "Accept": "*/*",
    "Cache-Control": "no-store",
    "Origin": "https://duck.ai",
    "Referer": "https://duck.ai/",
    "x-vqd-accept": "1",
    "x-fe-version": fe_version,
}
r2 = s.get("https://duck.ai/duckchat/v1/status", headers=h, timeout=30)
print("GET /status ->", r2.status_code)
for k, v in r2.headers.items():
    if k.lower().startswith(("x-", "set-cookie", "content-type")):
        print(f"  {k}: {v[:160]}")
print("body:", r2.text[:400])

jsa = r2.headers.get("X-Vqd-Hash-1")
if jsa:
    print("\njsa len:", len(jsa), "starts:", jsa[:60])
    dec = base64.b64decode(jsa + "=" * (-len(jsa) % 4)).decode("utf-8", "replace")
    open("challenge.js", "w").write(dec)
    print("challenge.js chars:", len(dec))
    print(dec[:3000])
else:
    print("\nno X-Vqd-Hash-1 header in status response")
