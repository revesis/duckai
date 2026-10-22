// Run a Duck.ai jsa challenge script (server-provided) under a minimal DOM shim
// and emit the attestation object as JSON. No browser required.
const fs = require('fs');
const path = process.argv[2];
const UA = process.argv[3] || ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
  + '(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36');
const src = fs.readFileSync(path, 'utf8');

// A real Chrome: an inline-block div containing "x" with 8px padding.
function fakeElement(tag) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    style: {},
    textContent: '',
    className: '',
    offsetWidth: 17,
    offsetHeight: 35,
    scrollHeight: 19,
    clientWidth: 17,
    clientHeight: 35,
    getBoundingClientRect() {
      return { width: 17, height: 35, top: 0, left: 0, right: 17, bottom: 35, x: 0, y: 0 };
    },
    appendChild() {},
    removeChild() {},
    setAttribute() {},
    getAttribute() { return null; },
  };
  if (String(tag) === 'iframe') {
    el.contentWindow = { self: { Error: { toString: () => 'function Error() { [native code] }' } } };
    el.contentDocument = { body: { appendChild() {}, onerror: null } };
  }
  return el;
}

globalThis.navigator = { userAgent: UA, webdriver: false, language: 'en-US', languages: ['en-US', 'en'] };
globalThis.document = {
  createElement: (t) => fakeElement(t),
  body: { appendChild() {}, removeChild() {} },
  documentElement: fakeElement('html'),
  getElementById: () => null,
  querySelector: () => null,
};
globalThis.getComputedStyle = () => ({
  getPropertyValue: (p) => (p === 'display' ? 'inline-block' : ''),
});
globalThis.window = globalThis;
globalThis.window.top = {};
globalThis.self = globalThis;
globalThis.location = { origin: 'https://duck.ai', href: 'https://duck.ai/' };

(async () => {
  try {
    const result = await eval(src);
    process.stdout.write(JSON.stringify(result));
  } catch (e) {
    process.stdout.write(JSON.stringify({ __error: String(e && e.stack || e) }));
  }
})();
