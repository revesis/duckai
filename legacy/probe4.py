#!/usr/bin/env python3
"""Probe 4: can we build a valid X-Vqd-Hash-1 proof *without* running the challenge JS?

The challenge source embeds its own server_hashes / challenge_id / timestamp as
plain strings, so we can lift them with a regex and supply our own client_hashes.
"""
import base64, hashlib, json, re, sys, time
import requests

BASE = "https://duck.ai"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/145.0.0.0 Safari/537.36")

def b64(b): return base64.b64encode(b).decode()
def h(s): return b64(hashlib.sha256(s.encode()).digest())
def b64j(o): return b64(json.dumps(o, separators=(",", ":")).encode())

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                  "Origin": BASE, "Referer": BASE + "/"})
r = s.get(BASE + "/", timeout=30)
tag = re.search(r'data-version-tag="([^"]*)"', r.text).group(1)
sha = re.search(r'data-version-sha="([^"]*)"', r.text).group(1)
fe = f"{tag}-{sha}"

r2 = s.get(BASE + "/duckchat/v1/status", headers={"x-vqd-accept": "1", "Cache-Control": "no-store",
                                                  "x-fe-version": fe}, timeout=30)
raw = r2.headers.get("x-vqd-hash-1")
src = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode()
open("_challenge2.js", "w").write(src)

hashes = re.findall(r"[A-Za-z0-9+/]{43}=", src)
cid = re.search(r"[0-9a-f]{64}[a-z0-9]{5}", src)
ts = re.search(r"'timestamp':'(\d+)'", src)
print("status:", r2.status_code, "| hashes:", len(hashes), "| cid:", cid.group(0) if cid else None,
      "| ts:", ts.group(1) if ts else None)
if len(hashes) < 3 or not cid:
    sys.exit("challenge layout changed; regex failed")

for layout, wd in [("9492", "614"), ("9492", "615"), ("0", "0")]:
    proof = {
        "server_hashes": hashes[:3],
        "client_hashes": [h(UA), h(layout), h(wd)],
        "signals": {},
        "meta": {"v": "4", "challenge_id": cid.group(0),
                 "timestamp": ts.group(1) if ts else str(int(time.time() * 1000)),
                 "debug": "\x1d\x18", "origin": BASE,
                 "stack": "Error\nat solve (https://duck.ai/dist/duckai-dist/entry.duckai.js:1:1)",
                 "duration": "42"},
    }
    body = {"model": "gpt-6-luna",
            "messages": [{"role": "user", "content": [{"type": "text", "text": "Say hi in 3 words."}]}],
            "canUseTools": False, "reasoningEffort": "none", "canUseApproxLocation": None,
            "canDelegateImageGeneration": None, "canShowGreeting": False}
    hdrs = {"Content-Type": "application/json", "Accept": "text/event-stream",
            "x-fe-version": fe, "x-fe-signals": b64j({"start": 0, "events": [], "end": 0}),
            "X-Vqd-Hash-1": b64j(proof)}
    resp = s.post(BASE + "/duckchat/v1/chat", headers=hdrs, data=json.dumps(body), timeout=40)
    print(f"\n--- client_hashes [{layout},{wd}] -> {resp.status_code}")
    print(resp.text[:600])
    if resp.status_code == 200:
        print("*** ACCEPTED ***")
        break
