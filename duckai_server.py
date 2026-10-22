#!/usr/bin/env python3
"""OpenAI-compatible HTTP bridge in front of duck.ai.

Lets any OpenAI client (Hermes, Aider, Cline, the openai python package …) talk to
DuckDuckGo's chat backend:

    python3 duckai_server.py --port 8765
    curl -s localhost:8765/v1/models
    curl -s localhost:8765/v1/chat/completions -H 'Content-Type: application/json' \\
         -d '{"model":"gpt-6-luna","messages":[{"role":"user","content":"hi"}]}'

Endpoints
    GET  /health                liveness probe
    GET  /v1/models             OpenAI model list
    POST /v1/chat/completions   OpenAI chat completions (stream=true|false)

Two things duck.ai does NOT accept, both handled here by prompt folding:
  * ``role: "system"``  -> prepended as a "System instructions:" block
  * ``role: "assistant"`` in the request history (400 ERR_BAD_REQUEST)
    -> rendered as a "Conversation so far:" transcript
There is also no function calling upstream: ``tools`` are dropped and the model
answers in prose, so agent loops that need tool calls will not get them.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from duckai_client import MODELS, DuckAI, DuckAIError

DEFAULT_MODEL = "gpt-6-luna"
SERVED_MODELS = ["gpt-6-luna", "gpt-5.6-luna", "gpt-5.4-nano", "gpt-5.4-mini",
                 "claude-haiku-4-5", "mistral-small-2603"]

# duck.ai rejects oversized prompts (HTTP 429 ERR_INPUT_LIMIT): ~16k chars pass,
# ~32k fail. Keep a margin below the observed ceiling and fold long system
# prompts / histories into head+tail.
MAX_PROMPT_CHARS = int(os.getenv("DUCKAI_MAX_PROMPT_CHARS", "15000"))

# Optional bearer token: set DUCKAI_API_KEY before exposing the bridge beyond
# localhost (a server deployment), and give clients the same value as their key.
API_KEY = os.getenv("DUCKAI_API_KEY", "").strip()

# DuckDuckGo's fraud score punishes bursts, so upstream calls are serialized.
_UPSTREAM_LOCK = threading.Lock()
_UPSTREAM_TIMEOUT = 180.0


def resolve_model(name: str | None) -> str:
    """Accept a duck.ai id, a friendly alias (luna/nano/haiku…), or nothing."""
    raw = (name or "").strip()
    if not raw:
        return DEFAULT_MODEL
    if raw in SERVED_MODELS:
        return raw
    return MODELS.get(raw.lower(), raw)


def _text_of(content) -> str:
    """Flatten an OpenAI message ``content`` (string or parts list) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict):
                if isinstance(part.get("text"), str):
                    out.append(part["text"])
                elif part.get("type") == "image_url":
                    out.append("[image omitted: duck.ai bridge is text-only]")
        return "\n".join(out)
    return "" if content is None else str(content)


def build_prompt(messages: list[dict]) -> str:
    """Fold an OpenAI message list into the single user turn duck.ai expects."""
    system: list[str] = []
    convo: list[tuple[str, str]] = []
    for msg in messages or []:
        role = str(msg.get("role") or "user").lower()
        text = _text_of(msg.get("content")).strip()
        if not text:
            continue
        if role == "system":
            system.append(text)
        elif role == "assistant":
            convo.append(("Assistant", text))
        elif role == "tool":
            convo.append(("Tool result", text))
        else:  # user, developer, anything unknown
            convo.append(("User", text))

    if not convo and system:
        convo.append(("User", "Follow the system instructions above."))

    blocks: list[str] = []
    if system:
        blocks.append("System instructions:\n" + "\n\n".join(system))
    if len(convo) > 1:
        history = "\n\n".join(f"{label}: {text}" for label, text in convo[:-1])
        blocks.append("Conversation so far:\n" + history)
        blocks.append("Current message:\n" + convo[-1][1])
    elif convo:
        blocks.append(convo[-1][1])
    return "\n\n".join(blocks).strip() or "Hello"


OMIT_MARKER = "\n\n[... middle omitted to fit duck.ai's input limit ...]\n\n"


def fit_prompt(prompt: str, limit: int = MAX_PROMPT_CHARS) -> str:
    """Head+tail trim: keep the system instructions' opening and the newest turns."""
    if limit <= 0 or len(prompt) <= limit:
        return prompt
    head = int(limit * 0.55)
    tail = max(0, limit - head - len(OMIT_MARKER))
    return prompt[:head] + OMIT_MARKER + (prompt[-tail:] if tail else "")


class Handler(BaseHTTPRequestHandler):
    server_version = "duckai-bridge/1.0"
    protocol_version = "HTTP/1.1"

    # ── plumbing ───────────────────────────────────────────────
    def log_message(self, format: str, *args) -> None:  # noqa: A002 — base-class signature
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str, err_type: str = "invalid_request_error") -> None:
        self._send_json(status, {"error": {"message": message, "type": err_type, "code": status}})

    def _read_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._error(400, "bad Content-Length")
            return None
        raw = self.rfile.read(length) if length else b""
        if not raw:
            self._error(400, "empty request body")
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            self._error(400, f"invalid JSON: {exc}")
            return None

    # ── routes ─────────────────────────────────────────────────
    def _authorized(self) -> bool:
        if not API_KEY:
            return True
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {API_KEY}" or self.headers.get("x-api-key") == API_KEY

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path in ("/health", "/healthz"):
            self._send_json(200, {"status": "ok", "upstream": "duck.ai"})
        elif not self._authorized():
            self._error(401, "missing or invalid API key", "authentication_error")
        elif path in ("/v1/models", "/models"):
            now = int(time.time())
            self._send_json(200, {
                "object": "list",
                "data": [{"id": m, "object": "model", "created": now, "owned_by": "duck.ai"}
                         for m in SERVED_MODELS],
            })
        else:
            self._error(404, f"no route {path}", "not_found_error")

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path not in ("/v1/chat/completions", "/chat/completions"):
            self._error(404, f"no route {path}", "not_found_error")
            return
        if not self._authorized():
            self._error(401, "missing or invalid API key", "authentication_error")
            return
        body = self._read_body()
        if body is None:
            return

        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            self._error(400, "'messages' must be a non-empty array")
            return
        model = resolve_model(body.get("model"))
        prompt = build_prompt(messages)
        fitted = fit_prompt(prompt)
        sys.stderr.write(f"duckai prompt {len(prompt)} chars -> {len(fitted)} sent\n")
        prompt = fitted
        stream = bool(body.get("stream"))
        completion_id = "chatcmpl-" + uuid.uuid4().hex[:24]
        created = int(time.time())

        if not _UPSTREAM_LOCK.acquire(timeout=_UPSTREAM_TIMEOUT):
            self._error(429, "another duck.ai request is still running", "rate_limit_error")
            return
        started = time.time()
        try:
            client = DuckAI()
            if stream:
                self._stream(client, prompt, model, completion_id, created, started)
            else:
                text = "".join(client.stream(prompt, model=model))
                est_in = max(1, len(prompt) // 4)
                est_out = max(1, len(text) // 4)
                self._send_json(200, {
                    "id": completion_id, "object": "chat.completion", "created": created,
                    "model": model,
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": text}}],
                    "usage": {"prompt_tokens": est_in, "completion_tokens": est_out,
                              "total_tokens": est_in + est_out},
                })
                sys.stderr.write(f"duckai {model} non-stream {len(text)} chars "
                                 f"in {time.time() - started:.1f}s\n")
        except DuckAIError as exc:
            self._error(429 if exc.status == 418 else 502, str(exc), "upstream_error")
        except Exception as exc:  # noqa: BLE001 — surface anything else as a 502
            self._error(502, f"{type(exc).__name__}: {exc}", "upstream_error")
        finally:
            _UPSTREAM_LOCK.release()

    def _stream(self, client: DuckAI, prompt: str, model: str,
                completion_id: str, created: int, started: float) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def send(payload: dict) -> None:
            self.wfile.write(b"data: " + json.dumps(payload, ensure_ascii=False).encode() + b"\n\n")
            self.wfile.flush()

        def chunk(delta: dict, finish: str | None = None) -> dict:
            return {"id": completion_id, "object": "chat.completion.chunk",
                    "created": created, "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

        chars = 0
        try:
            send(chunk({"role": "assistant", "content": ""}))
            for delta in client.stream(prompt, model=model):
                chars += len(delta)
                send(chunk({"content": delta}))
            send(chunk({}, "stop"))
            done_marker = "[" + "DONE]"
            self.wfile.write(b"data: " + done_marker.encode() + b"\n\n")
            self.wfile.flush()
            sys.stderr.write(f"duckai {model} stream {chars} chars in {time.time() - started:.1f}s\n")
        except (BrokenPipeError, ConnectionResetError):
            sys.stderr.write("client disconnected mid-stream\n")
        except Exception as exc:  # noqa: BLE001
            # Headers are already out; report the failure inside the stream.
            try:
                send({"error": {"message": f"{type(exc).__name__}: {exc}", "type": "upstream_error"}})
            except OSError:
                pass


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenAI-compatible bridge for duck.ai")
    ap.add_argument("--host", default=os.getenv("DUCKAI_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("DUCKAI_PORT", "8765")))
    args = ap.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    print(f"duckai bridge listening on http://{args.host}:{args.port}/v1", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
