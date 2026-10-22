// Drive headless Chrome over CDP, capture the real duck.ai chat request.
// Usage: node probe_cdp.mjs "prompt" [model]
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const prompt = process.argv[2] || 'hello';
const model = process.argv[3] || 'gpt-4o-mini';
const OUT = '/root/codex/duckai/cap';
fs.mkdirSync(OUT, { recursive: true });

const chrome = spawn('/usr/bin/google-chrome-stable', [
  '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-quic',
  '--remote-debugging-port=9222',
  `--user-data-dir=${OUT}/profile`,
  `--ssl-key-log-file=${OUT}/keys.log`,
  'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] });
chrome.stderr.on('data', () => {});

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function waitPort() {
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch('http://127.0.0.1:9222/json/version'); if (r.ok) return r.json(); } catch {}
    await sleep(500);
  }
  throw new Error('devtools never came up');
}

const hits = [];
try {
  const ver = await waitPort();
  console.log('browser:', ver.Browser);
  const tab = await (await fetch('http://127.0.0.1:9222/json/new?about:blank', { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0; const pending = new Map();
  const send = (method, params = {}) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  const reqs = new Map();
  ws.onmessage = async (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); return; }
    if (m.method === 'Network.requestWillBeSent') {
      const r = m.params.request;
      if (/duckchat\/v1/.test(r.url)) { reqs.set(m.params.requestId, r); console.log('\n>>> REQ', r.method, r.url); console.log('HEADERS', JSON.stringify(r.headers, null, 1)); if (r.postData) console.log('POSTDATA', r.postData.slice(0, 800)); }
    }
    if (m.method === 'Network.responseReceived') {
      const r = reqs.get(m.params.requestId);
      if (r) { console.log('\n<<< RESP', m.params.response.status, r.url); console.log('RESP_HEADERS', JSON.stringify(m.params.response.headers, null, 1)); }
    }
    if (m.method === 'Network.loadingFinished' && reqs.has(m.params.requestId)) {
      const r = reqs.get(m.params.requestId);
      const b = await send('Network.getResponseBody', { requestId: m.params.requestId });
      if (b && b.body) { fs.writeFileSync(`${OUT}/body_${r.url.split('/').pop()}.txt`, b.body); console.log('BODY_SAVED', `${OUT}/body_${r.url.split('/').pop()}.txt`, b.body.length); }
    }
  };
  await send('Network.enable', { maxTotalBufferSize: 100000000 });
  await send('Page.enable');
  const url = `https://duck.ai/?q=${encodeURIComponent(prompt)}&model=${encodeURIComponent(model)}`;
  console.log('navigate:', url);
  await send('Page.navigate', { url });
  await sleep(22000);
  const dom = await send('Runtime.evaluate', { expression: 'document.body.innerText.slice(0,1500)', returnByValue: true });
  console.log('\n=== PAGE TEXT ===\n' + (dom.result?.value || ''));
  ws.close();
} finally {
  chrome.kill('SIGKILL');
  await sleep(300);
}
