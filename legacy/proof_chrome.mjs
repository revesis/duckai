#!/usr/bin/env node
// proof_chrome.mjs - capture a fresh "proof" (X-Vqd-Hash-1 + cookies) from a
// real headless Chrome that has successfully solved the duck.ai anti-bot
// challenge. The web app solves the challenge itself during page load; we
// simply intercept the first POST /duckchat/v1/chat request it makes and copy
// the headers a real browser attaches.
//
// Usage: node proof_chrome.mjs [prompt] [model]
// Output: one JSON object on stdout:
//   {
//     "hash_header": "<decoded X-Vqd-Hash-1 JSON>",
//     "fe_signals": "<decoded x-fe-signals JSON>",
//     "journey_id": "<x-ddg-journey-id>",
//     "fe_version": "<x-fe-version>",
//     "cookies": [ {"name","value","domain"}, ... ],
//     "model": "<model>",
//     "reply": "<the reply duck.ai gave the browser, or null>",
//     "chat_response_headers": {...}
//   }
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const prompt = process.argv[2] || 'reply with the single word: pong';
const model = process.argv[3] || 'gpt-4o-mini';
const PORT = 9231;
const PROFILE = fs.mkdtempSync(path.join(os.tmpdir(), 'duckai-proof-'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const chrome = spawn('/opt/google/chrome/google-chrome', [
  '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-quic',
  '--disable-dev-shm-usage', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${PROFILE}`,
  'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] });
chrome.stderr.on('data', () => {});
chrome.on('exit', () => {});

let tab;
for (let i = 0; i < 80; i++) {
  try {
    const r = await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' });
    if (r.ok) { tab = await r.json(); break; }
  } catch { /* not up yet */ }
  await sleep(250);
}
if (!tab) { console.error('NO_DEVTOOLS'); process.exit(1); }

const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0;
const pending = new Map();
const send = (method, params = {}) => new Promise((res) => {
  const i = ++id; pending.set(i, res);
  ws.send(JSON.stringify({ id: i, method, params }));
});

const captured = { reqHeaders: null, reqBody: null, respCode: null, respBody: null };
const reqIds = new Set();

ws.onmessage = async (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); return; }
  if (m.method === 'Network.requestWillBeSent') {
    const r = m.params.request;
    if (r.method === 'POST' && /\/duckchat\/v1\/chat$/.test(r.url)) {
      captured.reqHeaders = r.headers;
      captured.reqBody = r.postData || null;
      reqIds.add(m.params.requestId);
    }
  }
  if (m.method === 'Network.responseReceived' && reqIds.has(m.params.requestId)) {
    captured.respCode = m.params.response.status;
  }
  if (m.method === 'Network.loadingFinished' && reqIds.has(m.params.requestId)) {
    const b = await send('Network.getResponseBody', { requestId: m.params.requestId });
    captured.respBody = (b && b.body) || null;
  }
};

await send('Network.enable', { maxTotalBufferSize: 100000000 });
await send('Page.enable');
await send('Page.navigate', { url: 'https://duck.ai/' });

// wait (up to ~30s) for the message input to appear
let inputTag = null;
for (let i = 0; i < 60; i++) {
  const r = await send('Runtime.evaluate', {
    expression: `(() => {
      const t = document.querySelector('textarea') || document.querySelector('[contenteditable="true"]');
      return t ? t.tagName : null;
    })()`,
    returnByValue: true,
  });
  if (r.result?.value) { inputTag = r.result.value; break; }
  await sleep(500);
}
if (!inputTag) {
  const txt = await send('Runtime.evaluate', {
    expression: 'document.body ? document.body.innerText.slice(0, 600) : ""',
    returnByValue: true,
  });
  console.error('NO_INPUT page_text=' + JSON.stringify(txt.result?.value || ''));
  chrome.kill('SIGKILL');
  process.exit(1);
}
await send('Runtime.evaluate', {
  expression: `(() => { const t = document.querySelector('textarea') || document.querySelector('[contenteditable="true"]'); t.focus(); })()`,
  returnByValue: true,
});

await send('Input.insertText', { text: prompt });
await sleep(1000);

// press Ask button
const box = await send('Runtime.evaluate', {
  expression: `(() => {
    const b = [...document.querySelectorAll('button')].find(x => /^ask$/i.test(x.textContent.trim()));
    if (!b) return null;
    const r = b.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  })()`,
  returnByValue: true,
});
const pt = box.result?.value;
if (pt) {
  for (const type of ['mousePressed', 'mouseReleased']) {
    await send('Input.dispatchMouseEvent', { type, x: pt.x, y: pt.y, button: 'left', clickCount: 1 });
  }
} else {
  for (const type of ['keyDown', 'keyUp']) {
    await send('Input.dispatchKeyEvent', {
      type, key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13,
      nativeVirtualKeyCode: 13, text: type === 'keyDown' ? '\r' : undefined,
    });
  }
}

// wait for the chat request
for (let i = 0; i < 100; i++) {
  if (captured.reqHeaders) break;
  await sleep(300);
}
if (!captured.reqHeaders) {
  console.error('NO_CHAT_REQUEST');
  chrome.kill('SIGKILL');
  process.exit(1);
}

// wait for the response body to finish
for (let i = 0; i < 40; i++) {
  if (captured.respBody) break;
  await sleep(250);
}
if (!captured.respBody) {
  const txt = await send('Runtime.evaluate', {
    expression: 'document.body ? document.body.innerText.slice(-800) : ""',
    returnByValue: true,
  });
  captured.respBody = txt.result?.value || null;
}

const cook = await send('Network.getCookies', { urls: ['https://duck.ai'] });
const cookies = (cook.cookies || []).map((c) => ({
  name: c.name, value: c.value, domain: c.domain, path: c.path,
}));

const b64 = (s) => {
  if (!s) return null;
  try { return Buffer.from(s, 'base64').toString('utf8'); } catch { return null; }
};

console.log(JSON.stringify({
  hash_header: b64(captured.reqHeaders['X-Vqd-Hash-1'] || captured.reqHeaders['x-vqd-hash-1']) || captured.reqHeaders['X-Vqd-Hash-1'] || null,
  fe_signals: b64(captured.reqHeaders['x-fe-signals']),
  journey_id: captured.reqHeaders['x-ddg-journey-id'] || null,
  fe_version: captured.reqHeaders['x-fe-version'] || null,
  cookies,
  model: captured.reqBody ? (JSON.parse(captured.reqBody).model || null) : null,
  reply: captured.respBody || null,
  chat_response_code: captured.respCode,
}));

ws.close();
chrome.kill('SIGKILL');
