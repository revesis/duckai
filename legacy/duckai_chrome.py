#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Working Duck.ai client for a browser-less-ish server (uses headless Chrome
via CDP to pass Duck.ai's anti-bot challenge).

Why not pure HTTP?  Verified on this host:
  * plain Python requests / urllib POST /duckchat/v1/chat -> HTTP 418
    ERR_CHALLENGE (anti-bot) every time;
  * even with a fresh proof header captured from a real Chrome, replaying it
    over Python's HTTP stack -> 418 (proof is bound to the browser session);
  * the only path that succeeds is executing the chat inside a real Chrome
    page (Duck.ai itself solves the challenge during page load).

So this CLI drives a local headless Chrome through one chat turn and prints
only the assistant's text reply.  It does not need X11/GUI (headless mode);
the Chrome binary at /opt/google/chrome is required.

Usage:
    python3 duckai_chrome.py [--model MODEL] "prompt"
Note: the model picker is not automated; the page uses its default model
(currently gpt-6-luna). --model is accepted but only used as a hint.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROOF_CHROME = HERE / "proof_chrome.mjs"

def extract_reply(resp_body: str) -> str:
    """Pull assistant text out of the captured SSE response body."""
    if not resp_body:
        return ""
    out = []
    for line in resp_body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload in ("[DONE]", "") or payload.startswith("[CHAT_TITLE:"):
            continue
        try:
            ev = json.loads(payload)
        except json.JSONDecodeError:
            out.append(payload)
            continue
        for key in ("message", "content", "delta", "text"):
            v = ev.get(key)
            if isinstance(v, str):
                out.append(v)
                break
            if isinstance(v, list):
                for it in v:
                    if isinstance(it, dict) and it.get("type") == "text":
                        out.append(str(it.get("text", "")))
                break
    return "".join(out).replace("\u0000", "")

def main() -> int:
    args = sys.argv[1:]
    model = "gpt-4o-mini"
    prompts = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--model" and i + 1 < len(args):
            model = args[i + 1]; i += 2; continue
        if a in ("-h", "--help"):
            print(__doc__); return 0
        prompts.append(a)
        i += 1
    if not prompts:
        prompts = ["reply with the single word: pong"]

    for p in prompts:
        proc = subprocess.run(["node", str(PROOF_CHROME), p, model],
                              capture_output=True, timeout=200)
        if proc.returncode != 0:
            print("chrome capture failed: " + proc.stderr.decode(errors="replace")[:400],
                  file=sys.stderr)
            return 1
        d = json.loads(proc.stdout)
        text = extract_reply(d.get("reply") or "").strip()
        if not text:
            text = (d.get("reply") or "").strip()[:800]
        print(text)
    return 0

if __name__ == "__main__":
    sys.exit(main())
