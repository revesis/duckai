// Solve a duck.ai jsa challenge with jsdom (no Chrome).
// usage: node jsa_jsdom.js <challenge.js> [userAgent]
const fs = require('fs');
const { JSDOM } = require('jsdom');

const src = fs.readFileSync(process.argv[2], 'utf8');
const UA = process.argv[3] || ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
  + '(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36');

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'https://duck.ai/',
  userAgent: UA,
  runScripts: 'outside-only',
  pretendToBeVisual: true,
});
const w = dom.window;

// jsdom keeps its own UA/flag values; force what a plain Chrome reports.
try {
  Object.defineProperty(w.navigator, 'userAgent', { get: () => UA, configurable: true });
  Object.defineProperty(w.navigator, 'appVersion', { get: () => UA.replace('Mozilla/', ''), configurable: true });
  Object.defineProperty(w.navigator, 'webdriver', { get: () => false, configurable: true });
} catch (e) { /* ignore */ }

// jsdom has no layout engine: give the probe element plausible Chrome metrics
// (the checks only care that the box is non-empty).
const proto = w.Element.prototype;
for (const [prop, val] of [['offsetWidth', 17], ['offsetHeight', 35], ['scrollHeight', 19],
  ['clientWidth', 17], ['clientHeight', 35]]) {
  Object.defineProperty(proto, prop, { get() { return this.__fake || val; }, configurable: true });
}
proto.getBoundingClientRect = function () {
  return { width: 17, height: 35, top: 0, left: 0, right: 17, bottom: 35, x: 0, y: 0 };
};

(async () => {
  try {
    const result = await w.eval(src);
    process.stdout.write(JSON.stringify(result));
  } catch (e) {
    process.stdout.write(JSON.stringify({ __error: String((e && e.stack) || e) }));
  }
})();
