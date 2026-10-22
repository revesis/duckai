#!/usr/bin/env python3
"""Probe 5: full header/cookie dump around status + chat, and a replay with the
exact header set the browser sends."""
import base64, hashlib, json, re, sys, time, uuid
import requests

BASE = "https://duck.ai"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/145.0.0.0 Safari/537.36")

def b64(b): return base64.b64encode(b).decode()
def h(s): return b64(hashlib.sha256(s.encode()).digest())
def b64j(o): return b64(json.dumps(o, separators=(",", ":")).encode())

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
r = s.get(BASE + "/", timeout=30)
tag = re.search(r'data-version-tag="([^"]*)"', r.text).group(1)
sha = re.search(r'data-version-sha="([^"]*)"', r.text).group(1)
fe = f"{tag}-{sha}"

print("== GET / headers ==")
for k, v in r.headers.items():
    if k.lower().startswith(("x-", "set-cookie")):
        print(" ", k, ":", v[:120])
print("cookies after /:", s.cookies.get_dict())

r2 = s.get(BASE + "/duckchat/v1/status", headers={"x-vqd-accept": "1", "Cache-Control": "no-store",
                                                  "x-fe-version": fe,
                                                  "Origin": BASE, "Referer": BASE + "/",
                                                  "Accept": "*/*"}, timeout=30)
print("\n== /status ==", r2.status_code)
for k, v in r2.headers.items():
    print(" ", k, ":", v[:120])
print("cookies after status:", s.cookies.get_dict())
print("body:", r2.text[:200])

raw = r2.headers.get("x-vqd-hash-1")
src = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode()
hashes = re.findall(r"[A-Za-z0-9+/]{43}=", src)
cid = re.search(r"[0-9a-f]{64}[a-z0-9]{5}", src).group(0)
ts = re.search(r"'timestamp':'(\d+)'", src).group(1)

proof = {"server_hashes": hashes[:3], "client_hashes": [h(UA), h("9492"), h("614")],
         "signals": {},
         "meta": {"v": "4", "challenge_id": cid, "timestamp": ts, "debug": "\x1d\x18",
                  "origin": BASE,
                  "stack": "Error\nat solve (https://duck.ai/dist/duckai-dist/entry.duckai.js:1:1)",
                  "duration": "42"}}

body = {"model": "gpt-6-luna",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "Say hi in 3 words."}]}],
        "canUseTools": True, "reasoningEffort": "none", "canUseApproxLocation": None,
        "canDelegateImageGeneration": None, "canShowGreeting": False,
        "durableStream": {"messageId": str(uuid.uuid4()), "conversationId": str(uuid.uuid4())}}
hdrs = {
    "Content-Type": "application/json",
    "Accept": "text/event-stream",
    "Origin": BASE, "Referer": BASE + "/",
    "x-duckai-continuation": "resubmit-context",
    "x-duckai-consent-purposes": "user-location,image-generation,web-search",
    "x-duckai-tool-approval": "web-search",
    "x-duckai-response-id": str(uuid.uuid4()),
    "x-fe-version": fe,
    "x-fe-signals": b64j({"start": int(time.time() * 1000),
                          "events": [{"name": "action", "delta": 1200, "trusted": True},
                                     {"name": "onboarding_finish", "delta": 2400}],
                          "end": 2600}),
    "X-Vqd-Hash-1": b64j(proof),
}
resp = s.post(BASE + "/duckchat/v1/chat", headers=hdrs, data=json.dumps(body), timeout=40)
print("\n== chat ==", resp.status_code)
for k, v in resp.headers.items():
    print(" ", k, ":", v[:120])
print(resp.text[:800])
