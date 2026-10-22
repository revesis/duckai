// Run a Duck.ai "jsa" challenge (server-provided JS) under a minimal DOM shim.
// Emits the attestation object as JSON on stdout. No browser involved.
//
// usage: node jsa_runner.js <challenge.js> [userAgent] [webdriver:0|1]
const fs = require('fs');
const vm = require('vm');

const src = fs.readFileSync(process.argv[2], 'utf8');
const UA = process.argv[3] || ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
  + '(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36');
const WEBDRIVER = process.argv[4] === '1';

// Values a real Chrome reports for the probe element:
//   <div style="display:inline-block;padding:8px;position:absolute;visibility:hidden;">x</div>
const BOX = { width: 17, height: 35 };
const NATIVE_ERROR_TOSTRING = 'function Error() { [native code] }';

function makeElement(tag) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    style: {},
    textContent: '',
    className: '',
    offsetWidth: BOX.width,
    offsetHeight: BOX.height,
    scrollHeight: BOX.height,
    clientWidth: BOX.width,
    clientHeight: BOX.height,
    getBoundingClientRect: () => ({
      width: BOX.width, height: BOX.height, top: 0, left: 0, right: BOX.width, bottom: BOX.height, x: 0, y: 0,
    }),
    appendChild() {},
    removeChild() {},
    setAttribute() {},
    getAttribute: () => null,
  };
  if (String(tag).toLowerCase() === 'iframe') {
    el.contentWindow = { self: { Error: { toString: () => NATIVE_ERROR_TOSTRING } } };
    el.contentDocument = { body: { appendChild() {}, onerror: null } };
  }
  return el;
}

const sandbox = {
  console,
  navigator: { userAgent: UA, webdriver: WEBDRIVER, language: 'en-US', languages: ['en-US', 'en'] },
  document: {
    createElement: makeElement,
    body: { appendChild() {}, removeChild() {} },
    documentElement: makeElement('html'),
    getElementById: () => null,
    querySelector: () => null,
  },
  getComputedStyle: () => ({ getPropertyValue: (p) => (p === 'display' ? 'inline-block' : '') }),
  location: { origin: 'https://duck.ai', href: 'https://duck.ai/' },
};
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.top = {};
sandbox.globalThis = sandbox;

vm.createContext(sandbox);
try {
  const p = vm.runInContext(src, sandbox, { timeout: 15000 });
  Promise.resolve(p).then((result) => {
    process.stdout.write(JSON.stringify(result));
  }, (err) => {
    process.stdout.write(JSON.stringify({ __error: String((err && err.stack) || err) }));
  });
} catch (err) {
  process.stdout.write(JSON.stringify({ __error: String((err && err.stack) || err) }));
}
