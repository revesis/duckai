#!/usr/bin/env python3
"""End-to-end probe: can duck.ai be driven with plain HTTP from this server?

Flow (reverse-engineered from a real Chrome capture):
  GET  /duckchat/v1/auth/token        -> {}            (cookie bootstrap)
  GET  /duckchat/v1/capabilities      -> access level / flags
  GET  /duckchat/v1/status            -> header x-vqd-hash-1 = base64(JS challenge)
  POST /duckchat/v1/chat              -> SSE, needs X-Vqd-Hash-1 = base64(solved JSON)

Usage: python3 test_e2e.py [prompt] [model] [--no-signals]
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
SOLVER = HERE / os.environ.get("SOLVER", "solve.js")
BASE = "https://duck.ai"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/140.0.0.0 Safari/537.36")
FE_VERSION = "serp_20261021_162035_ET-3a9e50fa14597703604ea78758c0c65476c008f7"


def solve(challenge_b64: str) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".b64", delete=False) as fh:
        fh.write(challenge_b64)
        path = fh.name
    proc = subprocess.run(["node", str(SOLVER), path], capture_output=True, timeout=30,
                          env={"SOLVE_UA": UA, "PATH": "/usr/local/bin:/usr/bin:/bin"})
    if proc.returncode != 0:
        raise SystemExit("solve failed: " + proc.stderr.decode()[:600])
    return json.loads(proc.stdout)


def main():
    prompt = sys.argv[1] if len(sys.argv) > 1 else "reply with the single word: pong"
    model = sys.argv[2] if len(sys.argv) > 2 else "gpt-4o-mini"
    send_signals = "--no-signals" not in sys.argv

    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Referer": "https://duck.ai/",
        "Origin": "https://duck.ai",
        "Accept-Language": "en-US,en;q=0.9",
        "sec-ch-ua": '"Chromium";v="140", "Google Chrome";v="140", "Not=A?Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Linux"',
    })

    for p in ("/duckchat/v1/auth/token", "/duckchat/v1/capabilities"):
        r = s.get(BASE + p, timeout=20)
        print(f"{p:32} {r.status_code} {r.text[:120]}")

    r = s.get(BASE + "/duckchat/v1/status",
              headers={"x-vqd-accept": "1", "Cache-Control": "no-store"}, timeout=20)
    print(f"{'/duckchat/v1/status':32} {r.status_code} body={r.text[:120]}")
    vqd4 = r.headers.get("x-vqd-4")
    ch = r.headers.get("x-vqd-hash-1")
    print("  x-vqd-4:", (vqd4 or "")[:40], "| challenge len:", len(ch or ""))
    if not ch:
        raise SystemExit("no challenge header -> protocol changed")

    solved = solve(ch)
    print("  solved:", json.dumps(solved)[:200])
    payload_b64 = base64.b64encode(json.dumps(solved, separators=(",", ":")).encode()).decode()

    body = {
        "model": model,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
    }
    hdrs = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "X-Vqd-Hash-1": payload_b64,
        "x-fe-version": FE_VERSION,
        "x-duckai-continuation": "resubmit-context",
        "x-duckai-consent-purposes": "user-location,image-generation,web-search",
    }
    if vqd4:
        hdrs["x-vqd-4"] = vqd4
    if send_signals:
        hdrs["x-fe-signals"] = base64.b64encode(json.dumps({}).encode()).decode()

    with s.post(BASE + "/duckchat/v1/chat", headers=hdrs, json=body,
                stream=True, timeout=60) as resp:
        print(f"\nPOST /duckchat/v1/chat -> {resp.status_code} "
              f"{resp.headers.get('content-type')}")
        out = []
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            print("  |", line[:300])
            out.append(line)
            if len(out) > 60:
                break
        print("\nraw first chunk:", "".join(out)[:800])


if __name__ == "__main__":
    main()
