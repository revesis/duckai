#!/usr/bin/env python3
"""Duck.ai from a plain Python script — no browser, no Cloudflare.

  python3 duckai_client.py "your prompt" [model]

How the handshake works (mirrors the web app):
  1. GET  https://duck.ai/                       -> data-version-tag/sha => x-fe-version
  2. GET  /duckchat/v1/status  (x-vqd-accept: 1) -> X-Vqd-Hash-1 = base64(JS challenge)
  3. run that JS under jsdom (node)              -> {server_hashes, client_hashes, meta}
  4. X-Vqd-Hash-1 = base64(JSON(..., client_hashes = sha256(raw) base64))
  5. POST /duckchat/v1/chat                      -> SSE stream of the answer
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://duck.ai"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/145.0.0.0 Safari/537.36")

MODELS = {
    "luna": "gpt-6-luna",
    "gpt-6-luna": "gpt-6-luna",
    "gpt-5.6-luna": "gpt-5.6-luna",
    "nano": "gpt-5.4-nano",
    "mini": "gpt-5.4-mini",
    "haiku": "claude-haiku-4-5",
    "mistral": "mistral-small-2603",
}


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def sha256_b64(text: str) -> str:
    return b64(hashlib.sha256(text.encode()).digest())


def b64_json(obj) -> str:
    return b64(json.dumps(obj, separators=(",", ":")).encode())


class DuckAI:
    def __init__(self, ua: str = UA, timeout: int = 60):
        self.ua = ua
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"})
        self.fe_version = ""

    def bootstrap(self) -> "DuckAI":
        r = self.s.get(BASE + "/", timeout=self.timeout)
        r.raise_for_status()
        tag = re.search(r'data-version-tag="([^"]*)"', r.text)
        sha = re.search(r'data-version-sha="([^"]*)"', r.text)
        self.fe_version = f"{tag.group(1) if tag else 'dev'}-{sha.group(1) if sha else 'hash'}"
        return self

    def fetch_challenge(self) -> str:
        r = self.s.get(
            BASE + "/duckchat/v1/status",
            headers={"x-vqd-accept": "1", "Cache-Control": "no-store",
                     "x-fe-version": self.fe_version, "Origin": BASE, "Referer": BASE + "/"},
            timeout=self.timeout,
        )
        raw = r.headers.get("x-vqd-hash-1")
        if not raw:
            raise RuntimeError(f"no challenge (HTTP {r.status_code}): {r.text[:200]}")
        return base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace")

    def solve(self, js_source: str) -> dict:
        path = os.path.join(HERE, "_challenge.js")
        with open(path, "w") as fh:
            fh.write(js_source)
        out = subprocess.run(
            ["node", os.path.join(HERE, "jsa_jsdom.js"), path, self.ua],
            capture_output=True, text=True, timeout=90,
        )
        if out.returncode != 0 or not out.stdout.strip():
            raise RuntimeError(f"challenge runner failed: {out.stderr[:400]}")
        result = json.loads(out.stdout)
        if "__error" in result:
            raise RuntimeError(f"challenge error: {result['__error'][:400]}")
        return result

    def build_proof(self, solved: dict) -> str:
        proof = dict(solved)
        proof["client_hashes"] = [sha256_b64(x) for x in solved["client_hashes"]]
        meta = dict(solved.get("meta") or {})
        meta.update({
            "origin": BASE,
            "stack": ("Error\nat l (https://duck.ai/dist/duckai-dist/entry.duckai.js:2:2129171)\n"
                      "at async https://duck.ai/dist/duckai-dist/entry.duckai.js:2:1859809"),
            "duration": "58",
        })
        proof["meta"] = meta
        return b64_json(proof)

    def chat(self, prompt: str, model: str = "gpt-6-luna", tools: bool = False):
        body = {
            "model": model,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            "canUseTools": tools,
            "reasoningEffort": "none",
            "canUseApproxLocation": None,
            "canDelegateImageGeneration": None,
            "canShowGreeting": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Origin": BASE,
            "Referer": BASE + "/",
            "x-fe-version": self.fe_version,
            "x-fe-signals": b64_json({"start": int(time.time() * 1000),
                                      "events": [{"name": "action", "delta": 1200, "trusted": True}],
                                      "end": 1500}),
            "X-Vqd-Hash-1": self.jsa,
        }
        return self.s.post(BASE + "/duckchat/v1/chat", headers=headers,
                           data=json.dumps(body), stream=True, timeout=self.timeout)

    def ask(self, prompt: str, model: str = "gpt-6-luna", on_delta=None, retries: int = 4) -> str:
        last = ""
        for attempt in range(retries):
            self.bootstrap()
            solved = self.solve(self.fetch_challenge())
            self.jsa = self.build_proof(solved)
            r = self.chat(prompt, model)
            if r.status_code == 200:
                break
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            # 418 = DuckDuckGo's fraud score said no; a fresh challenge often clears it.
            time.sleep(2 + attempt * 2)
        else:
            raise RuntimeError(f"chat failed after {retries} attempts: {last}")
        parts = []
        for raw in r.iter_lines():
            if not raw or not raw.startswith(b"data: "):
                continue
            try:
                ev = json.loads(raw[6:].decode("utf-8", "replace"))
            except json.JSONDecodeError:
                continue
            msg = ev.get("message")
            if isinstance(msg, str):
                parts.append(msg)
                if on_delta:
                    on_delta(msg)
        return "".join(parts)


def main():
    args = [a for a in sys.argv[1:]]
    model = "gpt-6-luna"
    if args and args[-1] in MODELS:
        model = MODELS[args.pop()]
    prompt = " ".join(args) or "Say hello in five words."
    client = DuckAI()
    answer = client.ask(prompt, model=model, on_delta=lambda d: (sys.stdout.write(d), sys.stdout.flush()))
    print()
    return 0 if answer else 1


if __name__ == "__main__":
    sys.exit(main())
