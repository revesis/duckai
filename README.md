# duck.ai — browserless Python client

Short version: **it works**. No Chrome, and nothing to get past Cloudflare
(duck.ai is served by nginx). All you need is a JS runtime (node + jsdom) to
execute the anti-abuse challenge script the server hands out.

    python3 duckai_client.py "Explain quantum entanglement in one sentence"
    python3 duckai_client.py "17*23=?" haiku              # pick another model

Measured locally on 2026-10-22: 3–6 s per answer, ~1.4 s of that is node startup.

## Protocol (reverse-engineered from entry.duckai.js, verified against captures)

    1. GET  https://duck.ai/                        200  HTML; read data-version-tag / data-version-sha
                                                      -> x-fe-version = "<tag>-<sha>"
    2. GET  /duckchat/v1/status  (x-vqd-accept: 1)  200  response header x-vqd-hash-1 = base64(challenge JS)
    3. execute the challenge JS                      -> {server_hashes, client_hashes, signals, meta}
    4. X-Vqd-Hash-1 = base64(JSON(...))              where client_hashes = base64(sha256(raw string))
    5. POST /duckchat/v1/chat                       200  SSE (data: {...message...})

Chat request headers:

    Content-Type: application/json
    Accept: text/event-stream
    Origin: https://duck.ai        Referer: https://duck.ai/
    x-fe-version: <tag>-<sha>      x-fe-signals: base64({"start":..,"events":[..],"end":..})
    X-Vqd-Hash-1: <the proof from step 4>

Request body (`durableStream` would require an RSA public key — just omit it):

    {"model":"gpt-6-luna",
     "messages":[{"role":"user","content":[{"type":"text","text":"..."}]}],
     "canUseTools":false,"reasoningEffort":"none","canUseApproxLocation":null,
     "canDelegateImageGeneration":null,"canShowGreeting":false}

Model ids: gpt-6-luna / gpt-5.6-luna / gpt-5.4-nano / gpt-5.4-mini /
claude-haiku-4-5 / mistral-small-2603
(verified working: gpt-6-luna, gpt-5.4-nano, claude-haiku-4-5, mistral-small-2603;
`tinfoil/gpt-oss-120b` and `tinfoil/gemma4-31b` return 400 on this path)

## What the challenge (X-Vqd-Hash-1 / "jsa") actually is

- Every `/status` call returns an obfuscated `(async function(){...})()` that
  embeds a random base plus `server_hashes`, `challenge_id` and `timestamp`.
- The script does three things: reads `navigator.userAgent`; creates a
  `display:inline-block;padding:8px;visibility:hidden` div and measures
  offsetWidth / offsetHeight / getBoundingClientRect / the parsed innerHTML;
  reads `navigator.webdriver` plus an iframe/proxy probe.
  Each result becomes a string (`<random base> + a few booleans`).
- The wrapper (module 35488 in the web bundle) sha256s those three strings,
  base64s the digests, and packs them with `server_hashes` and
  `meta{origin,stack,duration}` into base64(JSON) as `X-Vqd-Hash-1`.
- **The server verifies those values exactly**: bump one of them by 1 and the
  replay immediately gets 418 (`overrideCode: 8e04` / `3501`). So the challenge
  script has to be executed for real — no hardcoding.

`jsa_jsdom.js` runs it under jsdom and patches in the layout metrics jsdom
lacks (offsetWidth=17 / offsetHeight=35 / a non-zero getBoundingClientRect).
It matches real Chrome exactly: for the same challenge Chrome returns
`["<UA>","5510","7687"]` and jsdom returns `["<UA>","5510","7686"]` — only the
webdriver bit differs (true when Chrome is driven over CDP, false for a normal
browser). 8 out of 8 challenge variants solved.

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| 418 `ERR_CHALLENGE` + the "pick the ducks" captcha in the UI | UA contains `HeadlessChrome`, or `navigator.webdriver=true` | use a normal Chrome UA and report webdriver=false |
| 418 `overrideCode 3501 / 8e04` | wrong proof values (forged or expired challenge) | fetch a fresh challenge per request and actually solve it |
| 418 `overrideCode d78d` (repeated) | too many requests in a short window, fraud-score cooldown | back off and retry (the client does 4 attempts at 2/4/6 s) |
| 400 `ERR_BAD_REQUEST` | body carries a `durableStream` without its public key | do not send durableStream |
| mojibake for non-ASCII answers | SSE has no charset, `iter_lines(decode_unicode=True)` falls back to latin-1 | read bytes and decode utf-8 (already handled) |

Success rate measured at roughly 3 in 4 (bursts trigger a cooldown of a dozen
seconds). This is DuckDuckGo's own fraud scoring, not Cloudflare, and it is not
tied to an IP range — a browser with a normal UA on the same machine goes
straight through.

## Files

- `duckai_client.py`  — main client (protocol + retries + streaming output)
- `jsa_jsdom.js`      — jsdom challenge solver (challenge JS in, proof material JSON out)
- `check_variants.py` — solves 8 challenge variants to catch solver regressions
- `deob.js`           — debugging aid: decodes the challenge's obfuscated string table
- `legacy/`           — earlier failed attempts (chromedp / DOM stub / captures), kept for reference

## Dependencies

    pip install -r requirements.txt     # requests only
    npm install                         # jsdom, needs node >= 18

## License

MIT — see [LICENSE](LICENSE).

## Difference from benoitpetit/duckduckgo-chat-cli

That project drives a real Chrome via chromedp, intercepts the live request and
replays its `X-Vqd-Hash-1` header — which is why it hard-requires Chrome. This
repo replays the same protocol but computes the challenge itself under jsdom, so
no browser is needed on the server. Only if DuckDuckGo moves the challenge onto
canvas/WebGL-style real-browser APIs would the chromedp approach become
necessary again.
