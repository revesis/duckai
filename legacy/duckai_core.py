#!/usr/bin/env python3
"""Core helpers: fetch a fresh duck.ai jsa challenge and build the proof header."""
import base64
import hashlib
import json
import re
import time

import requests

BASE = "https://duck.ai"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/145.0.0.0 Safari/537.36")


def b64(b): return base64.b64encode(b).decode()
def h(s): return b64(hashlib.sha256(s.encode()).digest())
def b64j(o): return b64(json.dumps(o, separators=(",", ":")).encode())


def bootstrap(s: requests.Session, ua: str = UA) -> str:
    s.headers.update({"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"})
    r = s.get(BASE + "/", timeout=30)
    tag = re.search(r'data-version-tag="([^"]*)"', r.text)
    sha = re.search(r'data-version-sha="([^"]*)"', r.text)
    return f"{tag.group(1) if tag else 'dev'}-{sha.group(1) if sha else 'hash'}"


def fresh_challenge(s: requests.Session, fe: str):
    """Returns (challenge_js, response_headers)."""
    r = s.get(BASE + "/duckchat/v1/status",
              headers={"x-vqd-accept": "1", "Cache-Control": "no-store",
                       "x-fe-version": fe, "Origin": BASE, "Referer": BASE + "/",
                       "Accept": "*/*"},
              timeout=30)
    raw = r.headers.get("x-vqd-hash-1")
    if not raw:
        raise RuntimeError(f"no challenge (HTTP {r.status_code}): {r.text[:200]}")
    return base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace"), r.headers


def parse_challenge(src: str):
    """Lift server_hashes / challenge_id / timestamp out of the challenge source."""
    hashes = re.findall(r"[A-Za-z0-9+/]{43}=", src)
    cid = re.search(r"[0-9a-f]{64}[a-z0-9]{5}", src)
    ts = re.search(r"'(?:timestamp)':'(\d+)'", src) or re.search(r"\b(1[6-9]\d{11})\b", src)
    if len(hashes) < 3 or not cid or not ts:
        raise RuntimeError(f"unexpected challenge layout: hashes={len(hashes)} cid={bool(cid)} ts={bool(ts)}")
    return hashes[:3], cid.group(0), ts.group(1)


def build_proof(server_hashes, challenge_id, timestamp, ua=UA, layout="9492", webdriver="614",
                stack=None, duration="42", debug="\x1d\x18") -> str:
    proof = {
        "server_hashes": server_hashes,
        "client_hashes": [h(ua), h(layout), h(webdriver)],
        "signals": {},
        "meta": {
            "v": "4",
            "challenge_id": challenge_id,
            "timestamp": timestamp,
            "debug": debug,
            "origin": BASE,
            "stack": stack or ("Error\nat l (https://duck.ai/dist/duckai-dist/entry.duckai.js:2:2129171)\n"
                               "at async https://duck.ai/dist/duckai-dist/entry.duckai.js:2:1859809"),
            "duration": duration,
        },
    }
    return b64j(proof)


def chat_body(prompt: str, model="gpt-6-luna", tools=True):
    import uuid
    return {
        "model": model,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        "canUseTools": tools,
        "reasoningEffort": "none",
        "canUseApproxLocation": None,
        "canDelegateImageGeneration": None,
        "canShowGreeting": False,
        "durableStream": {"messageId": str(uuid.uuid4()), "conversationId": str(uuid.uuid4())},
    }


def chat_headers(fe: str, proof: str, journey: str | None = None):
    import uuid
    hdrs = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Origin": BASE,
        "Referer": BASE + "/",
        "x-duckai-continuation": "resubmit-context",
        "x-duckai-consent-purposes": "user-location,image-generation,web-search",
        "x-duckai-tool-approval": "web-search",
        "x-duckai-response-id": str(uuid.uuid4()),
        "x-fe-version": fe,
        "x-fe-signals": b64j({"start": int(time.time() * 1000),
                              "events": [{"name": "action", "delta": 1200, "trusted": True},
                                         {"name": "onboarding_finish", "delta": 2400}],
                              "end": 2600}),
        "X-Vqd-Hash-1": proof,
    }
    if journey:
        hdrs["x-ddg-journey-id"] = journey
    return hdrs
