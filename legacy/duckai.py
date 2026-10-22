#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal Duck.ai client (pure Python HTTP/SSE, no browser at request time).

Protocol (ported from github.com/benoitpetit/duckduckgo-chat-cli, which was
verified against a live browser capture on this host):

    GET  https://duck.ai/duckchat/v1/status          -> x-vqd-hash-1 header
    POST https://duck.ai/duckchat/v1/chat            -> SSE stream

Duck.ai uses an anti-bot challenge (HTTP 418 ERR_CHALLENGE) for automated
requests.  Three proof providers are available:

  none    - send whatever /status returns; will usually hit the 418 wall.
  node    - evaluate the challenge JS in Node with a DOM stub (solve.js).
            Historically produces ERR_INVALID_VQD (fingerprints rejected).
  chrome  - capture a fresh, real-browser proof from a local headless Chrome
            via proof_chrome.mjs (the only path proven to work from a
            datacenter IP).  The chat request itself is still made by
            THIS python script over ordinary HTTP.

Usage:
    python3 duckai.py [options] "prompt" [prompt2 ...]
    python3 duckai.py --list-models

Options:
    --proof none|node|chrome   proof provider (default: none)
    --model NAME               model id (default: gpt-4o-mini)
    --debug                    print raw SSE lines and request/response heads
    --no-login                 (accepted; login not required for anonymous)
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://duck.ai"
STATUS_URL = BASE + "/duckchat/v1/status"
CHAT_URL = BASE + "/duckchat/v1/chat"

HERE = Path(__file__).resolve().parent
SOLVER = HERE / "solve.js"            # node DOM-stub solver (proof=node)
PROOF_CHROME = HERE / "proof_chrome.mjs"

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/155.0.0.0 Safari/537.36")

# refreshed from the live page: data-version-tag / data-version-sha
FE_VERSION = "serp_20261021_162035_ET-3a9e50fa14597703604ea78758c0c65476c008f7"

MODELS = [
    "gpt-4o-mini", "gpt-5.4-mini", "gpt-5.6-luna", "gpt-6-luna",
    "claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6",
    "mistral-small-2603", "gpt-oss", "o4-mini",
]

class DuckAIError(RuntimeError):
    pass

class ChallengeError(DuckAIError):
    """HTTP 418 ERR_CHALLENGE - the anti-bot wall."""

# ---------------------------------------------------------------------------
# proof providers
# ---------------------------------------------------------------------------

class ProofProvider:
    name = "none"

    def fetch(self) -> dict:
        """Return a dict of extra headers/cookies to attach to /chat."""
        return {}

class NodeProof(ProofProvider):
    name = "node"

    def fetch(self) -> dict:
        challenge = _get_challenge_header()
        if not challenge:
            raise DuckAIError("no x-vqd-hash-1 from /status")
        proc = subprocess.run(
            ["node", str(SOLVER), "/dev/stdin"],
            input=challenge.encode(), capture_output=True, timeout=30,
        )
        if proc.returncode != 0:
            raise ChallengeError("node solver failed: " + proc.stderr.decode(errors="replace")[:400])
        solved = json.loads(proc.stdout)
        return {"X-Vqd-Hash-1": base64.b64encode(
            json.dumps(solved, separators=(",", ":")).encode()).decode()}

class ChromeProof(ProofProvider):
    name = "chrome"

    def fetch(self) -> dict:
        proc = subprocess.run(
            ["node", str(PROOF_CHROME), "reply with the single word: pong"],
            capture_output=True, timeout=180,
        )
        if proc.returncode != 0:
            raise DuckAIError("chrome proof capture failed: "
                              + proc.stderr.decode(errors="replace")[:400])
        p = json.loads(proc.stdout)
        h = {}
        if p.get("hash_header"):
            h["X-Vqd-Hash-1"] = p["hash_header"]
        if p.get("fe_signals"):
            h["x-fe-signals"] = p["fe_signals"]
        if p.get("journey_id"):
            h["x-ddg-journey-id"] = p["journey_id"]
        if p.get("fe_version"):
            h["x-fe-version"] = p["fe_version"]
        cookies = []
        for c in p.get("cookies") or []:
            cookies.append(f"{c['name']}={c['value']}")
        if cookies:
            h["Cookie"] = "; ".join(cookies)
        return h

PROOFS = {"none": ProofProvider, "node": NodeProof, "chrome": ChromeProof}

# ---------------------------------------------------------------------------
# low-level HTTP / SSE
# ---------------------------------------------------------------------------

def _get_challenge_header() -> str | None:
    req = urllib.request.Request(STATUS_URL, headers={
        "Accept": "text/event-stream",
        "User-Agent": UA,
        "Origin": BASE,
        "Referer": BASE + "/",
        "x-vqd-accept": "1",
        "Cache-Control": "no-store",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.headers.get("x-vqd-hash-1")

def _parse_sse_lines(raw_line: str) -> dict | None:
    """Yield one parsed SSE event per `data:` payload (or None to skip)."""
    line = raw_line.strip()
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if payload == "[DONE]":
        return {"__done__": True}
    if payload.startswith("[CHAT_TITLE:"):
        return None
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        # fallback: raw text fragment
        return {"message": payload}

def _extract_text(event: dict) -> str:
    """Pull the assistant text out of a chat SSE event (robust to shape)."""
    for key in ("message", "content", "delta", "text", "token"):
        v = event.get(key)
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            parts = []
            for it in v:
                if isinstance(it, dict) and it.get("type") == "text":
                    parts.append(str(it.get("text", "")))
                elif isinstance(it, str):
                    parts.append(it)
            if parts:
                return "".join(parts)
    return ""

# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------

class DuckAI:
    def __init__(self, proof: ProofProvider | None = None, model: str = "gpt-4o-mini",
                 debug: bool = False):
        self.proof = proof or ProofProvider()
        self.model = model
        self.debug = debug

    def _base_headers(self) -> dict:
        return {
            "Accept": "text/event-stream",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "User-Agent": UA,
            "Origin": BASE,
            "Referer": BASE + "/",
            "x-fe-version": FE_VERSION,
            "x-duckai-continuation": "resubmit-context",
            "x-duckai-consent-purposes": "user-location,image-generation,web-search",
        }

    def _payload(self, messages: list[dict]) -> dict:
        return {
            "model": self.model,
            "messages": messages,
            "canUseTools": False,
            "canUseApproxLocation": None,
            "canShowGreeting": False,
        }

    def chat(self, prompt: str, on_token=None, retries: int = 1) -> str:
        messages = [{"role": "user",
                     "content": [{"type": "text", "text": prompt}]}]
        body = json.dumps(self._payload(messages), separators=(",", ":")).encode()
        headers = self._base_headers()
        headers.update(self.proof.fetch())
        if self.debug:
            print(f"[debug] proof provider={self.proof.name} "
                  f"proof headers={ {k: (v[:60]+'...') if len(v)>60 else v for k,v in headers.items() if k.startswith('x-') or k=='X-Vqd-Hash-1'} }",
                  file=sys.stderr)
        req = urllib.request.Request(CHAT_URL, data=body, headers=headers,
                                     method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=90)
        except urllib.error.HTTPError as e:
            if retries > 0 and self._retryable(e):
                if self.debug:
                    print(f"[debug] {e.code} -> refreshing proof and retrying",
                          file=sys.stderr)
                return self.chat(prompt, on_token, retries - 1)
            self._raise_for_status(e)
            raise

        return self._consume(resp, on_token)

    def _retryable(self, e: urllib.error.HTTPError) -> bool:
        if e.code in (418, 429):
            return True
        try:
            return json.loads(e.read().decode()).get("type") == "ERR_INVALID_VQD"
        except Exception:
            return False

    def _raise_for_status(self, e: urllib.error.HTTPError) -> None:
        detail = ""
        try:
            detail = e.read().decode(errors="replace")[:400]
        except Exception:
            pass
        if e.code == 418 or "ERR_CHALLENGE" in detail:
            raise ChallengeError(f"HTTP 418 ERR_CHALLENGE (anti-bot). "
                                 f"Use --proof chrome; body={detail}")
        raise DuckAIError(f"HTTP {e.code}: {detail}")

    def _consume(self, resp, on_token) -> str:
        out: list[str] = []
        try:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace")
                if self.debug:
                    print("[sse]", line.rstrip(), file=sys.stderr)
                for event in line.splitlines():
                    ev = _parse_sse_lines(event)
                    if not ev:
                        continue
                    if ev.get("__done__"):
                        return "".join(out)
                    if ev.get("action") == "error":
                        raise DuckAIError("chat error: " + json.dumps(ev)[:300])
                    t = _extract_text(ev)
                    if t:
                        out.append(t)
                        if on_token:
                            on_token(t)
        finally:
            resp.close()
        return "".join(out)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    args = sys.argv[1:]
    proof_name = "none"
    model = "gpt-4o-mini"
    debug = False
    prompts = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--proof" and i + 1 < len(args):
            proof_name = args[i + 1].lower(); i += 2; continue
        if a == "--model" and i + 1 < len(args):
            model = args[i + 1]; i += 2; continue
        if a == "--debug":
            debug = True; i += 1; continue
        if a == "--list-models":
            print("\n".join(MODELS)); return 0
        if a in ("-h", "--help"):
            print(__doc__); return 0
        prompts.append(a)
        i += 1

    if proof_name not in PROOFS:
        print(f"unknown proof provider: {proof_name} (choose from {sorted(PROOFS)})",
              file=sys.stderr)
        return 2
    if not prompts:
        prompts = ["reply with the single word: pong"]

    client = DuckAI(proof=PROOFS[proof_name](), model=model, debug=debug)
    try:
        for p in prompts:
            out = client.chat(p)
            print(out)
    except ChallengeError as e:
        print(f"CHALLENGE: {e}", file=sys.stderr)
        return 3
    except DuckAIError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
