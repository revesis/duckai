// Navigate duck.ai, type a prompt, press Enter, capture the real chat request.
// Usage: node probe_chat.mjs "prompt" [model]
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const prompt = process.argv[2] || 'reply with the single word: pong';
const model = process.argv[3] || 'gpt-4o-mini';
const OUT = '/root/codex/duckai/cap';
fs.mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

const chrome = spawn('/usr/bin/google-chrome-stable', [
  '--headless=new', '--no-sandbox', '--disable-blink-features=AutomationControlled', '--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36', '--disable-gpu', '--disable-quic',
  '--remote-debugging-port=9225',
  `--user-data-dir=${OUT}/profile5`,
  `--ssl-key-log-file=${OUT}/keys.log`,
  'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] });
chrome.stderr.on('data', () => {});

let tab;
for (let i = 0; i < 60; i++) {
  try { const r = await fetch('http://127.0.0.1:9225/json/new?about:blank', { method: 'PUT' }); if (r.ok) { tab = await r.json(); break; } } catch {}
  await sleep(500);
}
if (!tab) { console.log('NO DEVTOOLS'); process.exit(1); }

const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0; const pending = new Map();
const send = (method, params = {}) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const reqs = new Map();
const log = [];

ws.onmessage = async (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); return; }
  if (m.method === 'Network.requestWillBeSent') {
    const r = m.params.request;
    if (/duckchat\/v1\/(chat|status|auth|capabilities)/.test(r.url)) {
      reqs.set(m.params.requestId, r);
      const rec = { kind: 'req', method: r.method, url: r.url, headers: r.headers, postData: r.postData || null };
      log.push(rec);
      console.log('\n>>> REQ', r.method, r.url);
      console.log('HEADERS', JSON.stringify(r.headers));
      if (r.postData) console.log('POSTDATA', r.postData.slice(0, 2000));
    }
  }
  if (m.method === 'Network.loadingFinished' && reqs.has(m.params.requestId)) {
    const r = reqs.get(m.params.requestId);
    const b = await send('Network.getResponseBody', { requestId: m.params.requestId });
    if (b && b.body) {
      const name = r.url.split('/').pop();
      fs.writeFileSync(`${OUT}/b2_${name}.txt`, b.body);
      console.log('BODY', name, b.body.length, JSON.stringify(b.body.slice(0, 300)));
    }
  }
};

await send('Network.enable', { maxTotalBufferSize: 100000000 });
await send('Page.enable');
await send('Page.navigate', { url: 'https://duck.ai/' });
await sleep(7000);

const focused = await send('Runtime.evaluate', {
  expression: `(() => { const t = document.querySelector('textarea') || document.querySelector('[contenteditable="true"]'); if (!t) return 'no-input'; t.focus(); return t.tagName; })()`,
  returnByValue: true,
});
console.log('input element:', focused.result?.value);
await send('Input.insertText', { text: prompt });
await sleep(1200);
const val = await send('Runtime.evaluate', { expression: `document.querySelector('textarea').value`, returnByValue: true });
console.log('textarea value:', JSON.stringify(val.result?.value));
const box = await send('Runtime.evaluate', {
  expression: `(() => { const b = [...document.querySelectorAll('button')].find(x => /^ask$/i.test(x.textContent.trim())); if (!b) return null; const r = b.getBoundingClientRect(); return { x: r.x + r.width/2, y: r.y + r.height/2, text: b.textContent.trim() }; })()`,
  returnByValue: true,
});
console.log('ask button:', JSON.stringify(box.result?.value));
const pt = box.result?.value;
if (pt) {
  for (const type of ['mousePressed', 'mouseReleased']) {
    await send('Input.dispatchMouseEvent', { type, x: pt.x, y: pt.y, button: 'left', clickCount: 1 });
  }
  console.log('clicked Ask at', pt.x, pt.y);
} else {
  for (const type of ['keyDown', 'keyUp']) {
    await send('Input.dispatchKeyEvent', { type, key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13, text: type === 'keyDown' ? '\r' : undefined });
  }
  console.log('fallback: enter dispatched');
}
await sleep(20000);

const txt = await send('Runtime.evaluate', { expression: 'document.body.innerText.slice(0,2000)', returnByValue: true });
console.log('\n=== PAGE TEXT ===\n' + (txt.result?.value || ''));
fs.writeFileSync(`${OUT}/reqs.json`, JSON.stringify(log, null, 1));
ws.close();
chrome.kill('SIGKILL');
