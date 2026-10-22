#!/usr/bin/env python3
"""Probe duck.ai's current chat API surface: what headers does it want?"""
import base64, json, re, sys
import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/140.0.0.0 Safari/537.36")

s = requests.Session()
s.headers.update({
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
})

r = s.get("https://duck.ai/", timeout=30)
print("GET / ->", r.status_code, "cookies:", dict(s.cookies))
m_tag = re.search(r'data-version-tag="([^"]*)"', r.text)
m_sha = re.search(r'data-version-sha="([^"]*)"', r.text)
tag = m_tag.group(1) if m_tag else "dev"
sha = m_sha.group(1) if m_sha else "hash"
fe_version = f"{tag}-{sha}"
print("x-fe-version:", fe_version)

signals = base64.b64encode(json.dumps({"start": 0, "events": [], "end": 0}).encode()).decode()

h = {
    "Accept": "*/*",
    "Content-Type": "application/json",
    "Origin": "https://duck.ai",
    "Referer": "https://duck.ai/",
    "x-vqd-accept": "1",
    "X-Vqd-Hash-1": "initial",
    "x-fe-version": fe_version,
    "x-fe-signals": signals,
}
r2 = s.post("https://duck.ai/duckchat/v1/capabilities", headers=h, data=b"{}", timeout=30)
print("\nPOST /capabilities ->", r2.status_code)
for k, v in r2.headers.items():
    if k.lower().startswith(("x-", "set-cookie", "content-type")):
        print(f"  {k}: {v[:200]}")
body = r2.text
print("  body[:800]:", body[:800])

jsa = r2.headers.get("X-Vqd-Hash-1") or r2.headers.get("x-vqd-hash-1")
if jsa:
    print("\njsa header len:", len(jsa))
    try:
        dec = base64.b64decode(jsa).decode("utf-8", "replace")
    except Exception as e:
        dec = f"<decode fail {e}>"
    open("challenge.js", "w").write(dec)
    print("challenge.js saved, first 1200 chars:\n", dec[:1200])
