// Evaluate a duck.ai x-vqd-hash-1 challenge (base64 JS) with a DOM stub that
// reports the same layout/automation booleans a real desktop Chrome reports.
// Usage: node solve2.js <b64file>   -> prints the result object as JSON
const fs = require('fs');

const src = Buffer.from(fs.readFileSync(process.argv[2], 'utf8').trim(), 'base64').toString('utf8');
const UA = process.env.SOLVE_UA || 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';

const anyFn = new Proxy(function () {}, {
  get: (t, p) => (p === Symbol.toPrimitive ? () => 0 : anyFn),
  apply: () => anyFn,
  has: () => true,
});

// real Chrome: an inline-block div holding "x" has a non-zero box
const RECT = { x: 8, y: 19, top: 19, left: 8, right: 16, bottom: 38, width: 8, height: 19 };

function makeEl(tag) {
  const el = {
    tagName: String(tag).toUpperCase(),
    innerHTML: '', textContent: '', srcdoc: '', style: {}, dataset: {},
    childNodes: [], children: [], parentNode: null,
    childElementCount: 0,
    offsetWidth: 8, offsetHeight: 19, clientWidth: 8, clientHeight: 19,
    scrollWidth: 8, scrollHeight: 19,
    appendChild(c) { el.childNodes.push(c); el.children.push(c); if (c && typeof c === 'object') c.parentNode = el; return c; },
    removeChild(c) { const i = el.childNodes.indexOf(c); if (i >= 0) { el.childNodes.splice(i, 1); el.children.splice(i, 1); } return c; },
    setAttribute() {}, getAttribute() { return null; }, remove() {},
    querySelector: () => null, querySelectorAll: () => [],
    getBoundingClientRect: () => ({ ...RECT }),
    getContext: () => null,
    addEventListener() {}, removeEventListener() {},
  };
  return new Proxy(el, {
    get: (t, p) => (p in t ? t[p] : anyFn),
    set: (t, p, v) => { t[p] = v; return true; },
  });
}

const body = makeEl('body');
const head = makeEl('head');
const doc = {
  createElement: (t) => makeEl(t),
  createElementNS: (ns, t) => makeEl(t),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {}, removeEventListener() {},
  body, head,
  documentElement: makeEl('html'),
  cookie: '', referrer: 'https://duck.ai/',
  location: { href: 'https://duck.ai/', origin: 'https://duck.ai', hostname: 'duck.ai', protocol: 'https:' },
  createTextNode: (t) => ({ textContent: t }),
};

// a visible iframe is not "proxied": contentWindow.self.get must be a real function
const iframeWindow = { self: {} };
iframeWindow.self.get = function get() { return 1; };

global.window = global;
global.self = global;
global.top = global;
global.parent = global;
global.frames = global;
global.document = doc;
Object.defineProperty(globalThis, 'navigator', { configurable: true, writable: true, value: {
  userAgent: UA, webdriver: false, platform: 'Linux x86_64', vendor: 'Google Inc.',
  language: 'en-US', languages: ['en-US', 'en'], hardwareConcurrency: 8, maxTouchPoints: 0,
  plugins: [1, 2, 3, 4, 5], mimeTypes: [1, 2], cookieEnabled: true,
}});
global.location = doc.location;
global.screen = { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040, colorDepth: 24, pixelDepth: 24 };
// getComputedStyle(div).getPropertyValue('display') === 'inline-block'
global.getComputedStyle = (el) => ({
  getPropertyValue: (p) => (String(p).toLowerCase() === 'display' ? (el && el.style && el.style.cssText ? 'inline-block' : 'inline-block') : ''),
  display: 'inline-block',
});
global.requestAnimationFrame = (f) => setTimeout(f, 0);
global.btoa = (s) => Buffer.from(s, 'binary').toString('base64');
global.atob = (s) => Buffer.from(s, 'base64').toString('binary');
global.crypto = require('crypto').webcrypto;
global.TextEncoder = require('util').TextEncoder;
global.addEventListener = () => {};
global.removeEventListener = () => {};
const start = Date.now();
global.performance = { now: () => Date.now() - start };

(async () => {
  try {
    const out = await eval(src);
    process.stdout.write(JSON.stringify(out));
  } catch (e) {
    process.stderr.write('SOLVE_ERROR: ' + ((e && e.stack) || e) + '\n');
    process.exit(1);
  }
})();
