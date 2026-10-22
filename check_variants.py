#!/usr/bin/env python3
"""Robustness check: solve N different challenge variants with jsdom."""
import json
import subprocess
import sys

import requests

sys.path.insert(0, "/root/codex/duckai")
import duckai_client as dc

c = dc.DuckAI().bootstrap()
print("fe-version:", c.fe_version)
ok = 0
for i in range(8):
    src = c.fetch_challenge()
    with open("/root/codex/duckai/_challenge.js", "w") as fh:
        fh.write(src)
    out = subprocess.run(["node", "/root/codex/duckai/jsa_jsdom.js", "/root/codex/duckai/_challenge.js", c.ua],
                         capture_output=True, text=True, timeout=90)
    try:
        res = json.loads(out.stdout)
    except Exception:
        print(i, "PARSE FAIL", out.stdout[:200], out.stderr[:200])
        continue
    if "__error" in res:
        print(i, "SOLVE FAIL", res["__error"][:200])
    else:
        print(i, "ok", res["client_hashes"][1:], "len(src)=%d" % len(src))
        ok += 1
print(f"{ok}/8 solved")
